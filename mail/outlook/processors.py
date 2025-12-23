"""Processors for Outlook pipelines."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List

from core.pipeline import Processor, ResultEnvelope

from .consumers import (
    OutlookRulesListPayload,
    OutlookRulesExportPayload,
    OutlookRulesSyncPayload,
    OutlookRulesPlanPayload,
    OutlookRulesDeletePayload,
    OutlookRulesSweepPayload,
    OutlookCategoriesListPayload,
    OutlookCategoriesExportPayload,
    OutlookCategoriesSyncPayload,
    OutlookFoldersSyncPayload,
    OutlookCalendarAddPayload,
    OutlookCalendarAddRecurringPayload,
    OutlookCalendarAddFromConfigPayload,
)
from .helpers import norm_label_name_outlook


# Result dataclasses

@dataclass
class OutlookRulesListResult:
    """Result of rules list."""
    rules: List[Dict[str, Any]] = field(default_factory=list)
    id_to_name: Dict[str, str] = field(default_factory=dict)
    folder_path_rev: Dict[str, str] = field(default_factory=dict)


@dataclass
class OutlookRulesExportResult:
    """Result of rules export."""
    count: int = 0
    out_path: str = ""


@dataclass
class OutlookRulesSyncResult:
    """Result of rules sync."""
    created: int = 0
    deleted: int = 0


@dataclass
class OutlookRulesPlanResult:
    """Result of rules plan."""
    would_create: int = 0
    plan_items: List[str] = field(default_factory=list)


@dataclass
class OutlookRulesDeleteResult:
    """Result of rules delete."""
    rule_id: str = ""


@dataclass
class OutlookRulesSweepResult:
    """Result of rules sweep."""
    moved: int = 0


@dataclass
class OutlookCategoriesListResult:
    """Result of categories list."""
    categories: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class OutlookCategoriesExportResult:
    """Result of categories export."""
    count: int = 0
    out_path: str = ""


@dataclass
class OutlookCategoriesSyncResult:
    """Result of categories sync."""
    created: int = 0
    skipped: int = 0


@dataclass
class OutlookFoldersSyncResult:
    """Result of folders sync."""
    created: int = 0
    skipped: int = 0


@dataclass
class OutlookCalendarAddResult:
    """Result of calendar add."""
    event_id: str = ""
    subject: str = ""


@dataclass
class OutlookCalendarAddRecurringResult:
    """Result of calendar add recurring."""
    event_id: str = ""
    subject: str = ""


@dataclass
class OutlookCalendarAddFromConfigResult:
    """Result of calendar add from config."""
    created: int = 0


def _canon_rule(rule: dict) -> str:
    """Create a canonical key for comparing rules."""
    crit = rule.get("criteria") or {}
    act = rule.get("action") or {}
    return str({
        "from": crit.get("from"),
        "to": crit.get("to"),
        "subject": crit.get("subject"),
        "add": tuple(sorted((act.get("addLabelIds") or []))),
        "forward": act.get("forward"),
        "move": act.get("moveToFolderId"),
    })


# Processor classes

class OutlookRulesListProcessor(Processor[OutlookRulesListPayload, ResultEnvelope[OutlookRulesListResult]]):
    """List Outlook inbox rules."""

    def process(self, payload: OutlookRulesListPayload) -> ResultEnvelope[OutlookRulesListResult]:
        try:
            client = payload.client
            rules = client.list_filters(use_cache=payload.use_cache, ttl=payload.cache_ttl)
            name_to_id = client.get_label_id_map()
            id_to_name = {v: k for k, v in name_to_id.items() if v}
            folder_path_rev = {fid: path for path, fid in (client.get_folder_path_map() or {}).items()}
            return ResultEnvelope(
                status="success",
                payload=OutlookRulesListResult(
                    rules=rules,
                    id_to_name=id_to_name,
                    folder_path_rev=folder_path_rev,
                ),
            )
        except Exception as exc:
            return ResultEnvelope(
                status="error",
                payload=None,
                diagnostics={"error": str(exc), "code": 1},
            )


class OutlookRulesExportProcessor(Processor[OutlookRulesExportPayload, ResultEnvelope[OutlookRulesExportResult]]):
    """Export Outlook inbox rules to YAML."""

    def process(self, payload: OutlookRulesExportPayload) -> ResultEnvelope[OutlookRulesExportResult]:
        try:
            client = payload.client
            rules = client.list_filters(use_cache=payload.use_cache, ttl=payload.cache_ttl)
            id_to_name = {v: k for k, v in client.get_label_id_map().items() if v}
            folder_path_map = client.get_folder_path_map() or {}
            folder_rev = {fid: path for path, fid in folder_path_map.items()}

            out_filters = []
            for r in rules:
                crit = r.get("criteria") or {}
                act = r.get("action") or {}
                entry = {"match": {}}
                for k in ("from", "to", "subject"):
                    if crit.get(k):
                        entry["match"][k] = crit.get(k)
                a = {}
                add_ids = act.get("addLabelIds") or []
                if add_ids:
                    a["add"] = [id_to_name.get(i) or i for i in add_ids]
                if act.get("forward"):
                    a["forward"] = act.get("forward")
                if act.get("moveToFolderId"):
                    a["moveToFolder"] = folder_rev.get(act.get("moveToFolderId")) or act.get("moveToFolderId")
                if a:
                    entry["action"] = a
                out_filters.append(entry)

            data = {"filters": out_filters}
            from ..config_resolver import expand_path
            outp = Path(expand_path(payload.out_path))
            outp.parent.mkdir(parents=True, exist_ok=True)
            from ..yamlio import dump_config
            dump_config(str(outp), data)

            return ResultEnvelope(
                status="success",
                payload=OutlookRulesExportResult(count=len(out_filters), out_path=str(outp)),
            )
        except Exception as exc:
            return ResultEnvelope(
                status="error",
                payload=None,
                diagnostics={"error": str(exc), "code": 1},
            )


class OutlookRulesSyncProcessor(Processor[OutlookRulesSyncPayload, ResultEnvelope[OutlookRulesSyncResult]]):
    """Sync Outlook inbox rules from YAML config."""

    def process(self, payload: OutlookRulesSyncPayload) -> ResultEnvelope[OutlookRulesSyncResult]:
        try:
            from ..yamlio import load_config
            from ..dsl import normalize_filters_for_outlook

            client = payload.client
            doc = load_config(payload.config_path)
            desired = normalize_filters_for_outlook(doc.get("filters") or [])

            # Fetch existing rules with resilience
            try:
                existing_rules = client.list_filters()
            except Exception as e:
                resp = getattr(e, 'response', None)
                status = getattr(resp, 'status_code', None) if resp else None
                if status in (401, 403):
                    return ResultEnvelope(
                        status="error",
                        payload=None,
                        diagnostics={"error": f"Auth failed: {e}", "code": 2, "hint": "Run outlook auth ensure"},
                    )
                try:
                    existing_rules = client.list_filters(use_cache=True, ttl=600)
                except Exception:
                    existing_rules = []

            existing = {_canon_rule(r): r for r in existing_rules}
            name_to_id = client.get_label_id_map()
            folder_path_map = client.get_folder_path_map() if payload.move_to_folders else {}

            created = 0
            desired_keys: set = set()

            for spec in desired:
                m = spec.get("match") or {}
                a_act = spec.get("action") or {}
                criteria = {k: v for k, v in m.items() if k in ("from", "to", "subject") and v}
                if not criteria:
                    continue

                action = {}
                add_labs = a_act.get("add") or []
                if a_act.get("moveToFolder"):
                    fid = client.ensure_folder_path(str(a_act.get("moveToFolder")))
                    action["moveToFolderId"] = fid
                elif payload.move_to_folders and add_labs:
                    lab_name = str(add_labs[0])
                    fid = folder_path_map.get(lab_name) or client.ensure_folder_path(lab_name)
                    action["moveToFolderId"] = fid
                elif add_labs:
                    ids = [name_to_id.get(x) or name_to_id.get(norm_label_name_outlook(x)) for x in add_labs]
                    ids = [x for x in ids if x]
                    if ids:
                        action["addLabelIds"] = ids
                if a_act.get("forward"):
                    action["forward"] = a_act["forward"]

                key = str({
                    "from": criteria.get("from"),
                    "to": criteria.get("to"),
                    "subject": criteria.get("subject"),
                    "add": tuple(sorted(action.get("addLabelIds", []) or [])),
                    "forward": action.get("forward"),
                    "move": action.get("moveToFolderId"),
                })
                desired_keys.add(key)

                if key in existing:
                    continue

                if not payload.dry_run:
                    try:
                        client.create_filter(criteria, action)
                    except Exception:
                        pass  # nosec B110 - filter creation failure logged elsewhere
                created += 1

            deleted = 0
            if payload.delete_missing:
                for k, rule in existing.items():
                    if k not in desired_keys:
                        rid = rule.get("id")
                        if not payload.dry_run and rid:
                            try:
                                client.delete_filter(rid)
                                deleted += 1
                            except Exception:
                                pass  # nosec B110 - filter deletion failure
                        else:
                            deleted += 1

            return ResultEnvelope(
                status="success",
                payload=OutlookRulesSyncResult(created=created, deleted=deleted),
            )
        except Exception as exc:
            return ResultEnvelope(
                status="error",
                payload=None,
                diagnostics={"error": str(exc), "code": 1},
            )


class OutlookRulesPlanProcessor(Processor[OutlookRulesPlanPayload, ResultEnvelope[OutlookRulesPlanResult]]):
    """Plan Outlook inbox rules sync (dry-run)."""

    def process(self, payload: OutlookRulesPlanPayload) -> ResultEnvelope[OutlookRulesPlanResult]:
        try:
            from ..yamlio import load_config
            from ..dsl import normalize_filters_for_outlook

            client = payload.client
            doc = load_config(payload.config_path)
            desired = normalize_filters_for_outlook(doc.get("filters") or [])

            try:
                existing = client.list_filters(use_cache=payload.use_cache, ttl=payload.cache_ttl)
            except Exception:
                try:
                    existing = client.list_filters(use_cache=True, ttl=payload.cache_ttl)
                except Exception:
                    existing = []

            existing_keys = {_canon_rule(r) for r in existing}
            name_to_id = client.get_label_id_map()
            folder_map = client.get_folder_id_map() if payload.move_to_folders else {}

            plan_items = []
            for spec in desired:
                m = spec.get("match") or {}
                a_act = spec.get("action") or {}
                criteria = {k: v for k, v in m.items() if k in ("from", "to", "subject") and v}
                if not criteria:
                    continue

                action = {}
                adds = a_act.get("add") or []
                if payload.move_to_folders and adds:
                    lab_name = norm_label_name_outlook(adds[0])
                    fid = folder_map.get(lab_name) or lab_name
                    action["moveToFolderId"] = fid
                elif adds:
                    ids = [name_to_id.get(x) or name_to_id.get(norm_label_name_outlook(x)) for x in adds]
                    ids = [x for x in ids if x]
                    if ids:
                        action["addLabelIds"] = ids
                if a_act.get("forward"):
                    action["forward"] = a_act["forward"]

                key = str({
                    "from": criteria.get("from"),
                    "to": criteria.get("to"),
                    "subject": criteria.get("subject"),
                    "add": tuple(sorted(action.get("addLabelIds", []) or [])),
                    "forward": action.get("forward"),
                    "move": action.get("moveToFolderId"),
                })

                if key not in existing_keys:
                    disp = dict(action)
                    if action.get("moveToFolderId"):
                        rev = {v: k for k, v in (folder_map or {}).items()}
                        disp["moveToFolder"] = rev.get(action["moveToFolderId"], action["moveToFolderId"])
                    plan_items.append(f"Would create: criteria={criteria} action={disp}")

            return ResultEnvelope(
                status="success",
                payload=OutlookRulesPlanResult(would_create=len(plan_items), plan_items=plan_items),
            )
        except Exception as exc:
            return ResultEnvelope(
                status="error",
                payload=None,
                diagnostics={"error": str(exc), "code": 1},
            )


class OutlookRulesDeleteProcessor(Processor[OutlookRulesDeletePayload, ResultEnvelope[OutlookRulesDeleteResult]]):
    """Delete an Outlook inbox rule."""

    def process(self, payload: OutlookRulesDeletePayload) -> ResultEnvelope[OutlookRulesDeleteResult]:
        try:
            payload.client.delete_filter(payload.rule_id)
            return ResultEnvelope(
                status="success",
                payload=OutlookRulesDeleteResult(rule_id=payload.rule_id),
            )
        except Exception as exc:
            return ResultEnvelope(
                status="error",
                payload=None,
                diagnostics={"error": str(exc), "code": 3},
            )


class OutlookRulesSweepProcessor(Processor[OutlookRulesSweepPayload, ResultEnvelope[OutlookRulesSweepResult]]):
    """Sweep inbox messages based on rules."""

    def process(self, payload: OutlookRulesSweepPayload) -> ResultEnvelope[OutlookRulesSweepResult]:
        try:
            from ..yamlio import load_config
            from ..dsl import normalize_filters_for_outlook

            client = payload.client
            if payload.clear_cache:
                try:
                    client.cfg_clear()
                except Exception:
                    pass  # nosec B110 - non-critical cache clear

            doc = load_config(payload.config_path)
            desired = normalize_filters_for_outlook(doc.get("filters") or [])
            folder_paths = client.get_folder_path_map(clear_cache=payload.clear_cache) if payload.move_to_folders else {}

            total_moves = 0
            for spec in desired:
                m = spec.get("match") or {}
                a_act = spec.get("action") or {}
                qparts = []
                if m.get("from"):
                    qparts.append(f"from:{m.get('from')}")
                if m.get("subject"):
                    subj = str(m.get("subject"))
                    if ' ' in subj:
                        qparts.append(f"subject:\"{subj}\"")
                    else:
                        qparts.append(f"subject:{subj}")
                if not qparts:
                    continue

                srch = " ".join(qparts)
                dest_id = None
                if a_act.get("moveToFolder"):
                    pth = str(a_act.get("moveToFolder"))
                    if payload.dry_run:
                        dest_id = folder_paths.get(pth)
                    else:
                        dest_id = client.ensure_folder_path(pth)
                elif payload.move_to_folders and (a_act.get("add") or []):
                    pth = str((a_act.get("add") or ["Inbox"])[0])
                    if payload.dry_run:
                        dest_id = folder_paths.get(pth)
                    else:
                        dest_id = client.ensure_folder_path(pth)

                if not dest_id:
                    continue

                try:
                    ids = client.search_inbox_messages(
                        srch,
                        days=payload.days,
                        top=payload.top,
                        pages=payload.pages,
                        use_cache=not payload.clear_cache,
                    )
                except Exception:
                    ids = client.search_inbox_messages(
                        srch,
                        days=None,
                        top=payload.top,
                        pages=payload.pages,
                        use_cache=not payload.clear_cache,
                    )

                if not ids:
                    continue

                if payload.dry_run:
                    total_moves += len(ids)
                else:
                    for mid in ids:
                        try:
                            client.move_message(mid, dest_id)
                            total_moves += 1
                        except Exception:
                            pass  # nosec B110 - individual move failure

            return ResultEnvelope(
                status="success",
                payload=OutlookRulesSweepResult(moved=total_moves),
            )
        except Exception as exc:
            return ResultEnvelope(
                status="error",
                payload=None,
                diagnostics={"error": str(exc), "code": 1},
            )


class OutlookCategoriesListProcessor(Processor[OutlookCategoriesListPayload, ResultEnvelope[OutlookCategoriesListResult]]):
    """List Outlook categories."""

    def process(self, payload: OutlookCategoriesListPayload) -> ResultEnvelope[OutlookCategoriesListResult]:
        try:
            cats = payload.client.list_labels(use_cache=payload.use_cache, ttl=payload.cache_ttl)
            return ResultEnvelope(
                status="success",
                payload=OutlookCategoriesListResult(categories=cats),
            )
        except Exception as exc:
            return ResultEnvelope(
                status="error",
                payload=None,
                diagnostics={"error": str(exc), "code": 1},
            )


class OutlookCategoriesExportProcessor(Processor[OutlookCategoriesExportPayload, ResultEnvelope[OutlookCategoriesExportResult]]):
    """Export Outlook categories to YAML."""

    def process(self, payload: OutlookCategoriesExportPayload) -> ResultEnvelope[OutlookCategoriesExportResult]:
        try:
            cats = payload.client.list_labels(use_cache=payload.use_cache, ttl=payload.cache_ttl)
            labels = []
            for c in cats:
                entry = {"name": c.get("name", "")}
                col = c.get("color")
                if isinstance(col, dict) and col.get("name"):
                    entry["color"] = {"name": col.get("name")}
                labels.append(entry)

            data = {"labels": labels}
            outp = Path(payload.out_path)
            outp.parent.mkdir(parents=True, exist_ok=True)
            from ..yamlio import dump_config
            dump_config(str(outp), data)

            return ResultEnvelope(
                status="success",
                payload=OutlookCategoriesExportResult(count=len(labels), out_path=str(outp)),
            )
        except Exception as exc:
            return ResultEnvelope(
                status="error",
                payload=None,
                diagnostics={"error": str(exc), "code": 1},
            )


class OutlookCategoriesSyncProcessor(Processor[OutlookCategoriesSyncPayload, ResultEnvelope[OutlookCategoriesSyncResult]]):
    """Sync Outlook categories from YAML config."""

    def process(self, payload: OutlookCategoriesSyncPayload) -> ResultEnvelope[OutlookCategoriesSyncResult]:
        try:
            from ..yamlio import load_config
            from ..dsl import normalize_labels_for_outlook

            client = payload.client
            doc = load_config(payload.config_path)
            labels = doc.get("labels") or []
            if not isinstance(labels, list):
                return ResultEnvelope(
                    status="error",
                    payload=None,
                    diagnostics={"error": "Labels YAML must contain a labels: [] list", "code": 2},
                )

            desired = normalize_labels_for_outlook(labels)
            existing = {c.get("name"): c for c in client.list_labels()}

            created = 0
            skipped = 0
            for entry in desired:
                name = entry.get("name") if isinstance(entry, dict) else entry
                if not name:
                    continue
                if name in existing:
                    skipped += 1
                    continue
                if payload.dry_run:
                    created += 1
                else:
                    try:
                        color = entry.get("color") if isinstance(entry, dict) else None
                        client.create_label(name, color=color)
                        created += 1
                    except Exception:
                        pass  # nosec B110 - category creation failure

            return ResultEnvelope(
                status="success",
                payload=OutlookCategoriesSyncResult(created=created, skipped=skipped),
            )
        except Exception as exc:
            return ResultEnvelope(
                status="error",
                payload=None,
                diagnostics={"error": str(exc), "code": 1},
            )


class OutlookFoldersSyncProcessor(Processor[OutlookFoldersSyncPayload, ResultEnvelope[OutlookFoldersSyncResult]]):
    """Sync Outlook folders from YAML config."""

    def process(self, payload: OutlookFoldersSyncPayload) -> ResultEnvelope[OutlookFoldersSyncResult]:
        try:
            from ..yamlio import load_config

            client = payload.client
            doc = load_config(payload.config_path)
            labels = doc.get("labels") or []
            if not isinstance(labels, list):
                return ResultEnvelope(
                    status="error",
                    payload=None,
                    diagnostics={"error": "Labels YAML must contain a labels: [] list", "code": 2},
                )

            path_map = client.get_folder_path_map()
            created = 0
            skipped = 0

            for entry in labels:
                name = entry.get("name") if isinstance(entry, dict) else entry if isinstance(entry, str) else None
                if not name:
                    continue
                if str(name).startswith("["):
                    skipped += 1
                    continue
                if name in path_map:
                    skipped += 1
                    continue

                if payload.dry_run:
                    created += 1
                else:
                    fid = client.ensure_folder_path(name)
                    if fid:
                        path_map[name] = fid
                        created += 1

            return ResultEnvelope(
                status="success",
                payload=OutlookFoldersSyncResult(created=created, skipped=skipped),
            )
        except Exception as exc:
            return ResultEnvelope(
                status="error",
                payload=None,
                diagnostics={"error": str(exc), "code": 1},
            )


class OutlookCalendarAddProcessor(Processor[OutlookCalendarAddPayload, ResultEnvelope[OutlookCalendarAddResult]]):
    """Add a calendar event."""

    def process(self, payload: OutlookCalendarAddPayload) -> ResultEnvelope[OutlookCalendarAddResult]:
        try:
            evt = payload.client.create_event(
                calendar_id=None,
                calendar_name=payload.calendar_name,
                subject=payload.subject,
                start_iso=payload.start_iso,
                end_iso=payload.end_iso,
                tz=payload.tz,
                body_html=payload.body_html,
                all_day=payload.all_day,
                location=payload.location,
                no_reminder=payload.no_reminder,
            )
            return ResultEnvelope(
                status="success",
                payload=OutlookCalendarAddResult(
                    event_id=evt.get("id", ""),
                    subject=evt.get("subject", ""),
                ),
            )
        except Exception as exc:
            return ResultEnvelope(
                status="error",
                payload=None,
                diagnostics={"error": str(exc), "code": 3},
            )


class OutlookCalendarAddRecurringProcessor(Processor[OutlookCalendarAddRecurringPayload, ResultEnvelope[OutlookCalendarAddRecurringResult]]):
    """Add a recurring calendar event."""

    def process(self, payload: OutlookCalendarAddRecurringPayload) -> ResultEnvelope[OutlookCalendarAddRecurringResult]:
        try:
            evt = payload.client.create_recurring_event(
                calendar_id=None,
                calendar_name=payload.calendar_name,
                subject=payload.subject,
                start_time=payload.start_time,
                end_time=payload.end_time,
                tz=payload.tz,
                repeat=payload.repeat,
                interval=payload.interval,
                byday=payload.byday,
                range_start_date=payload.range_start,
                range_until=payload.until,
                count=payload.count,
                body_html=payload.body_html,
                location=payload.location,
                exdates=payload.exdates,
                no_reminder=payload.no_reminder,
            )
            return ResultEnvelope(
                status="success",
                payload=OutlookCalendarAddRecurringResult(
                    event_id=evt.get("id", ""),
                    subject=evt.get("subject", ""),
                ),
            )
        except Exception as exc:
            return ResultEnvelope(
                status="error",
                payload=None,
                diagnostics={"error": str(exc), "code": 3},
            )


class OutlookCalendarAddFromConfigProcessor(Processor[OutlookCalendarAddFromConfigPayload, ResultEnvelope[OutlookCalendarAddFromConfigResult]]):
    """Add calendar events from a config file."""

    def process(self, payload: OutlookCalendarAddFromConfigPayload) -> ResultEnvelope[OutlookCalendarAddFromConfigResult]:
        try:
            from ..yamlio import load_config

            cfg = load_config(payload.config_path)
            items = cfg.get("events") if isinstance(cfg, dict) else None
            if not isinstance(items, list):
                return ResultEnvelope(
                    status="error",
                    payload=None,
                    diagnostics={"error": "Config must contain events: [] list", "code": 2},
                )

            client = payload.client
            created = 0

            for ev in items:
                if not isinstance(ev, dict):
                    continue
                cal_name = ev.get("calendar")
                subj = ev.get("subject")
                if not subj:
                    continue

                if ev.get("repeat"):
                    try:
                        client.create_recurring_event(
                            calendar_id=None,
                            calendar_name=cal_name,
                            subject=subj,
                            start_time=ev.get("start_time") or ev.get("startTime") or ev.get("start-time"),
                            end_time=ev.get("end_time") or ev.get("endTime") or ev.get("end-time"),
                            tz=ev.get("tz"),
                            repeat=ev.get("repeat"),
                            interval=int(ev.get("interval", 1)),
                            byday=ev.get("byday") or ev.get("byDay"),
                            range_start_date=(ev.get("range", {}) or {}).get("start_date") or ev.get("start_date") or ev.get("startDate"),
                            range_until=(ev.get("range", {}) or {}).get("until") or ev.get("until"),
                            count=ev.get("count"),
                            body_html=ev.get("body_html") or ev.get("bodyHtml"),
                            location=ev.get("location"),
                            exdates=ev.get("exdates") or ev.get("exceptions") or [],
                            no_reminder=payload.no_reminder,
                        )
                        created += 1
                    except Exception:
                        pass  # nosec B110 - recurring event creation failure
                else:
                    start_iso = ev.get("start")
                    end_iso = ev.get("end")
                    if not (start_iso and end_iso):
                        continue
                    try:
                        client.create_event(
                            calendar_id=None,
                            calendar_name=cal_name,
                            subject=subj,
                            start_iso=start_iso,
                            end_iso=end_iso,
                            tz=ev.get("tz"),
                            body_html=ev.get("body_html") or ev.get("bodyHtml"),
                            all_day=bool(ev.get("all_day") or ev.get("allDay")),
                            location=ev.get("location"),
                            no_reminder=payload.no_reminder,
                        )
                        created += 1
                    except Exception:
                        pass  # nosec B110 - event creation failure

            return ResultEnvelope(
                status="success",
                payload=OutlookCalendarAddFromConfigResult(created=created),
            )
        except Exception as exc:
            return ResultEnvelope(
                status="error",
                payload=None,
                diagnostics={"error": str(exc), "code": 1},
            )
