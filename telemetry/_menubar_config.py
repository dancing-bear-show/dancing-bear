"""Config loading, saving, and parsing helpers for the menubar app."""

import json
import os
import string
import tempfile
from pathlib import Path

_DEFAULT_MONTHLY_BUDGET = 4000.0
_DEFAULT_COST_MULTIPLIER = 1.0  # scales locally-computed cost (see pricing.py)
_DEFAULT_POLL_INTERVAL = 30  # seconds between refreshes
_POLL_INTERVAL_MIN = 5
_POLL_INTERVAL_MAX = 300

# Canonical nested config with per-section and per-row toggles.
_DEFAULT_SECTIONS: dict[str, dict[str, bool | int]] = {
    "usage": {
        "enabled": True,
        "show_tokens": True,
        "show_sessions": True,
        "show_rate": True,
        "show_sparkline": True,
    },
    "models": {"enabled": True},
    "active_sessions": {"enabled": True},
    "insights":      {"enabled": True, "max_tips": 3},
    "otel_usage":    {"enabled": False},
    "otel_models":   {"enabled": False},
    "otel_meta":     {"enabled": False},
    "otel_hooks":    {"enabled": False},
    "otel_tools":    {"enabled": False},
    "otel_code":     {"enabled": False},
    "otel_skills":   {"enabled": False},
    "otel_sessions": {"enabled": False},
}

_MAX_TIPS_LIMIT = 10  # hard cap for pre-allocated rows
_INSIGHTS_TIP_ROWS = _MAX_TIPS_LIMIT

_ICON_LEGACY_MAP: dict[str, str] = {
    "budget_score": "$score",
    "1h_spend": "$1h_spend",
    "1d_spend": "$1d_spend",
    "mtd_spend": "$mtd_spend",
    "tokens_1h": "$tokens_1h",
}
_DEFAULT_ICON_TEMPLATE = "$1d_spend"
_ICON_VAR_NAMES = ("score", "1h_spend", "1d_spend", "mtd_spend", "tokens_1h", "otel_1d")

_OTEL_SECTION_KEYS = (
    "otel_usage", "otel_models", "otel_meta", "otel_hooks",
    "otel_tools", "otel_code", "otel_skills", "otel_sessions",
)

# Default config path — overridden by menubar.py shim to allow test patching.
_CONFIG_PATH = Path.home() / ".claude" / "claudestats.json"


class _IconTemplate(string.Template):
    """string.Template subclass allowing identifiers that start with a digit."""

    idpattern = r"(?a:[_a-z0-9][_a-z0-9]*)"


def _coerce_icon_display(raw: object) -> str:
    """Normalize stored icon_display to a template string."""
    if not isinstance(raw, str):
        return _DEFAULT_ICON_TEMPLATE
    stripped = raw.strip()
    if not stripped:
        return _DEFAULT_ICON_TEMPLATE
    if stripped in _ICON_LEGACY_MAP:
        return _ICON_LEGACY_MAP[stripped]
    return stripped


def _icon_template_vars(template: str) -> set[str]:
    """Return the set of variable names referenced by the template."""
    refs: set[str] = set()
    for m in _IconTemplate.pattern.finditer(template):
        name = m.group("named") or m.group("braced")
        if name:
            refs.add(name)
    return refs


def _any_otel_sections_enabled(cfg: dict) -> bool:
    s = cfg.get("sections", {})
    return any(s.get(k, {}).get("enabled", False) for k in _OTEL_SECTION_KEYS)


def _coerce_bool(v: object, default: bool) -> bool:
    """Coerce a stored value to bool, treating string on/true/yes/1 as True."""
    if isinstance(v, bool):
        return v
    if isinstance(v, int):
        return bool(v)
    if isinstance(v, str):
        lower = v.strip().lower()
        if lower in ("on", "true", "yes", "1"):
            return True
        if lower in ("off", "false", "no", "0"):
            return False
    return default


def _coerce_cost_multiplier(raw: object) -> float:
    """Parse and validate a cost_multiplier value, returning the default on failure."""
    if isinstance(raw, (int, float)):
        value = float(raw)
        if value > 0:
            return value
    return _DEFAULT_COST_MULTIPLIER


def _merge_section(defaults: dict, stored: object) -> dict:
    """Merge stored section dict over defaults, coercing types."""
    if not isinstance(stored, dict):
        return dict(defaults)
    out = dict(defaults)
    for k, default_v in defaults.items():
        v = stored.get(k, default_v)
        if isinstance(default_v, bool):
            out[k] = _coerce_bool(v, default_v)
        elif isinstance(default_v, int):
            try:
                out[k] = max(1, min(_MAX_TIPS_LIMIT, int(v)))
            except (TypeError, ValueError):
                out[k] = default_v
    return out


def _migrate_flat_keys(raw: dict) -> dict:
    """Convert old flat show_* keys into the new sections structure."""
    sections: dict = {}
    mapping = {
        "show_tokens": ("usage", "show_tokens"),
        "show_sessions": ("usage", "show_sessions"),
        "show_rate": ("usage", "show_rate"),
        "show_sparkline": ("usage", "show_sparkline"),
        "show_models": ("models", "enabled"),
        "show_active_sessions": ("active_sessions", "enabled"),
        "show_insights": ("insights", "enabled"),
    }
    for flat_key, (section, field) in mapping.items():
        if flat_key in raw:
            sections.setdefault(section, {})[field] = _coerce_bool(raw[flat_key], True)
    return sections


def _load_config(config_path: Path | None = None) -> dict:
    """Load config from disk, merging stored values over defaults."""
    path = config_path if config_path is not None else _CONFIG_PATH
    try:
        raw = json.loads(path.read_text())
        if not isinstance(raw, dict):
            raw = {}
    except Exception:  # nosec B110 - any read/parse error falls back to defaults
        raw = {}

    try:
        budget = float(raw.get("monthly_budget", _DEFAULT_MONTHLY_BUDGET))
        if budget <= 0:
            budget = _DEFAULT_MONTHLY_BUDGET
    except (TypeError, ValueError):
        budget = _DEFAULT_MONTHLY_BUDGET

    raw_icon = raw.get("icon_display", _DEFAULT_ICON_TEMPLATE)
    icon_display = _coerce_icon_display(raw_icon)
    icon_migrated = isinstance(raw_icon, str) and raw_icon in _ICON_LEGACY_MAP

    try:
        poll_interval = int(raw.get("poll_interval", _DEFAULT_POLL_INTERVAL))
        poll_interval = max(_POLL_INTERVAL_MIN, min(_POLL_INTERVAL_MAX, poll_interval))
    except (TypeError, ValueError):
        poll_interval = _DEFAULT_POLL_INTERVAL

    cost_multiplier = _coerce_cost_multiplier(raw.get("cost_multiplier", _DEFAULT_COST_MULTIPLIER))

    stored_sections = raw.get("sections")
    needs_migration = not isinstance(stored_sections, dict)
    if needs_migration:
        stored_sections = _migrate_flat_keys(raw)

    sections: dict = {}
    for name, defaults in _DEFAULT_SECTIONS.items():
        sections[name] = _merge_section(defaults, stored_sections.get(name, {}))

    result = {
        "monthly_budget": budget,
        "icon_display": icon_display,
        "poll_interval": poll_interval,
        "cost_multiplier": cost_multiplier,
        "sections": sections,
    }

    if needs_migration or icon_migrated:
        try:
            _save_config(result, config_path=path)
        except Exception:  # nosec B110 - config migration failure is non-fatal; app continues with in-memory config
            pass

    return result


def _save_config(cfg: dict, config_path: Path | None = None) -> None:
    """Persist config atomically."""
    path = config_path if config_path is not None else _CONFIG_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = tempfile.NamedTemporaryFile(
        mode="w",
        dir=path.parent,
        delete=False,
        suffix=".tmp",
        encoding="utf-8",
    )
    try:
        json.dump(cfg, fd, indent=2)
        fd.close()
        os.replace(fd.name, path)
    except Exception:
        fd.close()
        try:
            os.unlink(fd.name)
        except OSError:  # nosec B110 - cleanup failure is non-fatal; original exception re-raised below
            pass
        raise


def _config_to_text(cfg: dict) -> str:
    """Render config as a human-editable text block."""
    s = cfg["sections"]
    u = s["usage"]
    ins = s["insights"]
    vars_list = ", ".join(f"${v}" for v in _ICON_VAR_NAMES)

    def _on(key: str) -> str:
        return "on" if s.get(key, {}).get("enabled", False) else "off"

    lines = [
        f"monthly_budget: {cfg['monthly_budget']:.0f}",
        f"# icon_display: template with {vars_list}",
        "# example: otel \"$otel_1d\", score \"$score\"",
        f"icon_display: {cfg.get('icon_display', _DEFAULT_ICON_TEMPLATE)}",
        f"# poll_interval: seconds between refreshes ({_POLL_INTERVAL_MIN}–{_POLL_INTERVAL_MAX})",
        f"poll_interval: {cfg.get('poll_interval', _DEFAULT_POLL_INTERVAL)}",
        "# cost_multiplier: scales locally-computed cost (e.g. 0.7 if your",
        "# enterprise rate is ~30% off list). Set to 1.0 to disable.",
        f"cost_multiplier: {cfg.get('cost_multiplier', _DEFAULT_COST_MULTIPLIER)}",
        "",
        "sections:",
        "# --- OTel (live telemetry, requires collector running) ---",
        f"  otel_usage: {_on('otel_usage')}",
        f"  otel_models: {_on('otel_models')}",
        f"  otel_meta: {_on('otel_meta')}",
        f"  otel_hooks: {_on('otel_hooks')}",
        f"  otel_tools: {_on('otel_tools')}",
        f"  otel_code: {_on('otel_code')}",
        f"  otel_skills: {_on('otel_skills')}",
        f"  otel_sessions: {_on('otel_sessions')}",
        "# --- Transcript-based ---",
        f"  usage: {'on' if u['enabled'] else 'off'}",
        f"    tokens: {'on' if u['show_tokens'] else 'off'}",
        f"    sessions: {'on' if u['show_sessions'] else 'off'}",
        f"    rate: {'on' if u['show_rate'] else 'off'}",
        f"    sparkline: {'on' if u['show_sparkline'] else 'off'}",
        f"  models: {'on' if s['models']['enabled'] else 'off'}",
        f"  active_sessions: {'on' if s['active_sessions']['enabled'] else 'off'}",
        f"  insights: {'on' if ins['enabled'] else 'off'}",
        f"    max_tips: {ins['max_tips']}",
    ]
    return "\n".join(lines)


def _apply_budget(cfg: dict, val: str) -> bool:
    try:
        b = float(val)
        if b > 0:
            cfg["monthly_budget"] = b
            return True
    except ValueError:
        pass
    return False


def _apply_max_tips(cfg: dict, val: str) -> bool:
    try:
        cfg["sections"]["insights"]["max_tips"] = max(1, min(_MAX_TIPS_LIMIT, int(val)))
        return True
    except ValueError:
        return False


def _apply_icon_display(cfg: dict, val: str) -> bool:
    v = val.strip()
    if v:
        cfg["icon_display"] = _coerce_icon_display(v)
        return True
    return False


def _apply_poll_interval(cfg: dict, val: str) -> bool:
    try:
        secs = int(val)
        cfg["poll_interval"] = max(_POLL_INTERVAL_MIN, min(_POLL_INTERVAL_MAX, secs))
        return True
    except ValueError:
        return False


def _apply_cost_multiplier(cfg: dict, val: str) -> bool:
    try:
        m = float(val)
        if m > 0:
            cfg["cost_multiplier"] = m
            return True
    except ValueError:
        pass
    return False


def _parse_bool(v: str) -> bool | None:
    lower = v.strip().lower()
    if lower in ("on", "true", "yes", "1"):
        return True
    if lower in ("off", "false", "no", "0"):
        return False
    return None


def _apply_config_line(key: str, val: str, cfg: dict, bool_keys: dict) -> bool:
    """Apply a single parsed key/value pair to cfg."""
    if key == "monthly_budget":
        return _apply_budget(cfg, val)
    if key == "icon_display":
        return _apply_icon_display(cfg, val)
    if key == "poll_interval":
        return _apply_poll_interval(cfg, val)
    if key == "cost_multiplier":
        return _apply_cost_multiplier(cfg, val)
    if key == "max_tips":
        return _apply_max_tips(cfg, val)
    if key in bool_keys:
        parsed = _parse_bool(val)
        if parsed is not None:
            section, field = bool_keys[key]
            section[field] = parsed
            return True
        return False
    return False


def _parse_config_text(text: str, current: dict) -> tuple[dict, list[str]]:
    """Parse user-edited text back into a config dict."""
    import copy
    cfg = copy.deepcopy(current)
    s = cfg["sections"]

    bool_keys: dict[str, tuple[dict, str]] = {
        "usage":            (s["usage"], "enabled"),
        "tokens":           (s["usage"], "show_tokens"),
        "sessions":         (s["usage"], "show_sessions"),
        "rate":             (s["usage"], "show_rate"),
        "sparkline":        (s["usage"], "show_sparkline"),
        "models":           (s["models"], "enabled"),
        "active_sessions":  (s["active_sessions"], "enabled"),
        "insights":         (s["insights"], "enabled"),
        "otel_usage":       (s["otel_usage"], "enabled"),
        "otel_models":      (s["otel_models"], "enabled"),
        "otel_meta":        (s["otel_meta"], "enabled"),
        "otel_hooks":       (s["otel_hooks"], "enabled"),
        "otel_tools":       (s["otel_tools"], "enabled"),
        "otel_code":        (s["otel_code"], "enabled"),
        "otel_skills":      (s["otel_skills"], "enabled"),
        "otel_sessions":    (s["otel_sessions"], "enabled"),
    }

    rejected: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        key, _, val = line.partition(":")
        key, val = key.strip(), val.strip()
        if key == "sections" and not val:
            continue
        if not _apply_config_line(key, val, cfg, bool_keys):
            rejected.append(f"{key}: {val}")

    return cfg, rejected
