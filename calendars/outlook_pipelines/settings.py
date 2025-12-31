"""Outlook Settings Pipeline."""

from __future__ import annotations

from ._base import (
    Any,
    Dict,
    List,
    Optional,
    Path,
    dataclass,
    re,
    BaseProducer,
    DateWindowResolver,
    RequestConsumer,
    SafeProcessor,
    check_service_required,
    _load_yaml,
    ERR_CODE_CONFIG,
    ERR_CODE_CALENDAR,
    LOG_DRY_RUN,
)

__all__ = [
    "OutlookSettingsRequest",
    "OutlookSettingsRequestConsumer",
    "OutlookSettingsResult",
    "OutlookSettingsProcessor",
    "OutlookSettingsProducer",
]


@dataclass
class OutlookSettingsRequest:
    config_path: Path
    calendar: Optional[str]
    from_date: Optional[str]
    to_date: Optional[str]
    dry_run: bool
    service: Any


OutlookSettingsRequestConsumer = RequestConsumer[OutlookSettingsRequest]


@dataclass
class OutlookSettingsResult:
    logs: List[str]
    selected: int
    changed: int
    dry_run: bool


class OutlookSettingsProcessor(SafeProcessor[OutlookSettingsRequest, OutlookSettingsResult]):
    def __init__(self, config_loader=None, regex_module=re, today_factory=None) -> None:
        self._config_loader = config_loader if config_loader is not None else _load_yaml
        self._regex = regex_module
        self._window = DateWindowResolver(today_factory)

    def _process_safe(self, payload: OutlookSettingsRequest) -> OutlookSettingsResult:
        doc = self._config_loader(str(payload.config_path)) or {}
        root = doc.get("settings") if isinstance(doc, dict) and "settings" in doc else doc
        defaults = (root.get("defaults") if isinstance(root, dict) else {}) or {}
        rules = (root.get("rules") if isinstance(root, dict) else None) or []
        if not isinstance(rules, list):
            raise ValueError("Config must contain settings.rules: [] or top-level rules: []")

        check_service_required(payload.service)
        svc = payload.service

        start_iso, end_iso = self._window.resolve(payload.from_date, payload.to_date)
        events = svc.list_events_in_range(
            calendar_name=payload.calendar,
            start_iso=start_iso,
            end_iso=end_iso,
        )

        logs: List[str] = []
        selected = 0
        changed = 0

        for event in events or []:
            eid = event.get("id")
            if not eid:
                continue
            cfg = self._evaluate_config(defaults, rules, event)
            if cfg is None:
                continue
            selected += 1
            patch = self._build_patch(cfg)
            if not patch:
                continue
            if payload.dry_run:
                parts = []
                if patch.get("categories") is not None:
                    parts.append(f"categories={patch['categories']}")
                if patch.get("show_as"):
                    parts.append(f"showAs={patch['show_as']}")
                if patch.get("sensitivity"):
                    parts.append(f"sensitivity={patch['sensitivity']}")
                if patch.get("is_reminder_on") is not None:
                    parts.append(f"isReminderOn={patch['is_reminder_on']}")
                if patch.get("reminder_minutes") is not None:
                    parts.append(f"reminderMinutes={patch['reminder_minutes']}")
                subject = (event.get("subject") or "").strip()
                logs.append(f"{LOG_DRY_RUN} would update {eid} | {subject} -> {{" + ", ".join(parts) + "}}")
                continue
            try:
                svc.update_event_settings(
                    event_id=eid,
                    calendar_name=payload.calendar,
                    categories=patch.get("categories"),
                    show_as=patch.get("show_as"),
                    sensitivity=patch.get("sensitivity"),
                    is_reminder_on=patch.get("is_reminder_on"),
                    reminder_minutes=patch.get("reminder_minutes"),
                )
                changed += 1
            except Exception as exc:
                logs.append(f"Failed to update {eid}: {exc}")

        result = OutlookSettingsResult(logs=logs, selected=selected, changed=changed, dry_run=payload.dry_run)
        return result

    def _evaluate_config(self, defaults, rules, event: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        subject = (event.get("subject") or "").strip()
        location = ((event.get("location") or {}).get("displayName") or "").strip()
        apply_set = None
        for rule in rules:
            if not isinstance(rule, dict):
                continue
            if self._match_rule(rule, subject, location):
                apply_set = (rule.get("set") or {})
                break
        if apply_set is None and not defaults:
            return None
        cfg = {}
        cfg.update(defaults or {})
        if apply_set:
            cfg.update(apply_set)
        return cfg

    def _match_rule(self, rule: Dict[str, Any], subject: str, location: str) -> bool:
        matcher = rule.get("match") or {}
        sc = self._to_list(matcher.get("subject_contains"))
        if sc and not any(s.lower() in subject.lower() for s in sc):
            return False
        sr = self._to_list(matcher.get("subject_regex"))
        if sr and not any(self._regex.search(p, subject, self._regex.I) for p in sr):
            return False
        lc = self._to_list(matcher.get("location_contains"))
        if lc and not any(s.lower() in location.lower() for s in lc):
            return False
        return True

    def _build_patch(self, cfg: Dict[str, Any]) -> Dict[str, Any]:
        cats = cfg.get("categories")
        if isinstance(cats, str):
            cats = [s.strip() for s in cats.split(",") if s.strip()]
        elif isinstance(cats, (list, tuple)):
            cats = [str(s).strip() for s in cats if str(s).strip()]
        else:
            cats = None if cats is None else [str(cats)]
        show_as = cfg.get("show_as") or cfg.get("showAs")
        sensitivity = cfg.get("sensitivity")
        is_rem_on = self._coerce_bool(cfg.get("is_reminder_on"))
        rem_min = cfg.get("reminder_minutes")
        try:
            rem_min = int(rem_min) if rem_min is not None else None
        except Exception:
            rem_min = None
        return {
            "categories": cats,
            "show_as": show_as,
            "sensitivity": sensitivity,
            "is_reminder_on": is_rem_on,
            "reminder_minutes": rem_min,
        }

    def _coerce_bool(self, value: Any) -> Optional[bool]:
        if isinstance(value, bool):
            return value
        if value is None:
            return None
        s = str(value).strip().lower()
        if s in ("1", "true", "yes", "on"):
            return True
        if s in ("0", "false", "no", "off"):
            return False
        return None

    def _to_list(self, value: Any) -> List[str]:
        if value is None:
            return []
        if isinstance(value, (list, tuple)):
            return [str(v) for v in value if str(v).strip()]
        return [str(value)] if str(value).strip() else []


class OutlookSettingsProducer(BaseProducer):
    def _produce_success(self, payload: OutlookSettingsResult, diagnostics: Optional[Dict[str, Any]]) -> None:
        self.print_logs(payload.logs)
        if payload.dry_run:
            print(f"Preview complete. {payload.selected} item(s) matched.")
        else:
            print(f"Applied settings to {payload.changed} item(s).")
