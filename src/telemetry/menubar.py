"""macOS menubar app for live Claude Code telemetry stats.

This module re-exports all public names from the three implementation
submodules. Certain names are defined here directly so that tests can patch
their dependencies via this module (e.g. menubar._CONFIG_PATH,
menubar.datetime, menubar.os, menubar.fcntl, menubar.subprocess,
menubar.NSColor, menubar.NSFont, etc.).
"""

import os  # patched by tests via menubar.os
import subprocess  # patched by tests via menubar.subprocess  # nosec B404 - subprocess imported deliberately; individual call sites carry their own B602/B603 review
from datetime import datetime
from pathlib import Path

from core.cli_errors import CLIError, ExitCode

try:
    import fcntl  # patched by tests via menubar.fcntl
    _HAS_FCNTL = True
except ImportError:
    _HAS_FCNTL = False  # Windows — instance lock is a no-op there
    fcntl = None  # type: ignore[assignment]

# AppKit symbols are patched by tests via patch.multiple(menubar_module, NSColor=...).
# Keep this import block here so the patched names live in this module's namespace.
try:
    from AppKit import (
        NSAttributedString,  # noqa: F401
        NSColor,  # noqa: F401
        NSFont,  # noqa: F401
        NSFontAttributeName,  # noqa: F401
        NSForegroundColorAttributeName,  # noqa: F401
        NSMutableAttributedString,  # noqa: F401
        NSPasteboard,  # noqa: F401
        NSPasteboardTypeString,  # noqa: F401
    )
    _HAS_APPKIT = True
except ImportError:
    _HAS_APPKIT = False

from telemetry._menubar_app import (
    TelemetryMenubarApp,  # noqa: F401
    _HAS_RUMPS,  # noqa: F401
    _OTEL_WINDOWS,  # noqa: F401
    _PROJECTS_DIR,  # noqa: F401
    _STORAGE_WARN_DAYS,  # noqa: F401
    _WINDOWS,  # noqa: F401
    _app_version_cache,  # noqa: F401
    _month_since,  # noqa: F401
    _project_short,  # noqa: F401
)
from telemetry._menubar_budget import (
    _budget_score,  # noqa: F401
    _safe_float,  # noqa: F401
    _safe_int,  # noqa: F401
)
from telemetry._menubar_renderers import (
    _icon_substitutions,  # noqa: F401
    _icon_token_stream,  # noqa: F401
    _render_icon_plain,  # noqa: F401
)
from telemetry._menubar_config import (
    _DEFAULT_COST_MULTIPLIER,  # noqa: F401
    _DEFAULT_ICON_TEMPLATE,  # noqa: F401
    _DEFAULT_MONTHLY_BUDGET,  # noqa: F401
    _DEFAULT_POLL_INTERVAL,  # noqa: F401
    _DEFAULT_SECTIONS,  # noqa: F401
    _ICON_LEGACY_MAP,  # noqa: F401
    _ICON_VAR_NAMES,  # noqa: F401
    _IconTemplate,  # noqa: F401
    _MAX_TIPS_LIMIT,  # noqa: F401
    _OTEL_SECTION_KEYS,  # noqa: F401
    _POLL_INTERVAL_MAX,  # noqa: F401
    _POLL_INTERVAL_MIN,  # noqa: F401
    _any_otel_sections_enabled,  # noqa: F401
    _apply_budget,  # noqa: F401
    _apply_config_line,  # noqa: F401
    _apply_cost_multiplier,  # noqa: F401
    _apply_icon_display,  # noqa: F401
    _apply_max_tips,  # noqa: F401
    _apply_poll_interval,  # noqa: F401
    _coerce_bool,  # noqa: F401
    _coerce_icon_display,  # noqa: F401
    _config_to_text,  # noqa: F401
    _icon_template_vars,  # noqa: F401
    _merge_section,  # noqa: F401
    _migrate_flat_keys,  # noqa: F401
    _parse_bool,  # noqa: F401
    _parse_config_text,  # noqa: F401
    _load_config as _load_config_impl,  # noqa: F401
    _save_config as _save_config_impl,  # noqa: F401
)
from telemetry._menubar_display import (
    _BLOCK_CHARS,  # noqa: F401
    _BLOCK_LEVELS,  # noqa: F401
    _age_str,  # noqa: F401
    _model_short,  # noqa: F401
    _rate_str,  # noqa: F401
    _sparkline,  # noqa: F401
    _window_since_impl,
)

_CLAUDE_DIR = Path.home() / ".claude"
_CONFIG_PATH = _CLAUDE_DIR / "claudestats.json"
_LOCK_PATH = _CLAUDE_DIR / "claudestats.lock"
_instance_lock_fd: int | None = None

_VERSION = "v1.1.0"


# ---------------------------------------------------------------------------
# Functions defined here directly so tests can patch module-level dependencies
# ---------------------------------------------------------------------------

def _load_config() -> dict:
    """Load config — delegates to _menubar_config but passes local _CONFIG_PATH."""
    return _load_config_impl(config_path=_CONFIG_PATH)


def _save_config(cfg: dict) -> None:
    """Persist config — delegates to _menubar_config but passes local _CONFIG_PATH."""
    _save_config_impl(cfg, config_path=_CONFIG_PATH)


def _window_since(seconds: int | None) -> datetime:
    """Return the UTC datetime marking the start of the given window."""
    return _window_since_impl(seconds)


def _build_version() -> str:
    """Return version string with git SHA, or _VERSION on failure.

    Defined here so tests can patch menubar.subprocess.check_output.
    """
    try:
        sha = subprocess.check_output(  # nosec B603 B607 - fixed git command with no user input
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=Path(__file__).resolve().parent,
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
        return f"{_VERSION} ({sha})"
    except (subprocess.CalledProcessError, FileNotFoundError):
        return _VERSION


_app_version_cache_shim: str | None = None


def _get_app_version() -> str:
    """Return the cached app version string."""
    global _app_version_cache_shim  # noqa: PLW0603
    if _app_version_cache_shim is None:
        _app_version_cache_shim = _build_version()
    return _app_version_cache_shim


def _score_color(score: int) -> object:
    """Return NSColor for a budget score band.

    Defined here so tests can patch menubar.NSColor via patch.multiple.
    Requires AppKit — callers must guard with _HAS_APPKIT.
    """
    if score <= 3:
        return NSColor.systemGreenColor()
    if score <= 6:
        return NSColor.systemOrangeColor()
    return NSColor.systemRedColor()


def _compose_icon_attributed(
    template: str, icon_ctx: dict[str, dict], mtd_cost: float, score: int,
    otel_cost_1d: float = 0.0,
) -> object:
    """Build an NSMutableAttributedString from a template.

    Defined here so tests can patch AppKit symbols via patch.multiple.
    Requires AppKit — callers must guard with _HAS_APPKIT.
    """
    values = _icon_substitutions(icon_ctx, mtd_cost, score, otel_cost_1d)
    font = NSFont.menuBarFontOfSize_(0)
    plain_attrs = {NSFontAttributeName: font}
    score_attrs = {
        NSFontAttributeName: font,
        NSForegroundColorAttributeName: _score_color(score),
    }
    out = NSMutableAttributedString.alloc().init()
    for kind, text in _icon_token_stream(template):
        if kind == "lit":
            if text:
                out.appendAttributedString_(
                    NSAttributedString.alloc().initWithString_attributes_(text, plain_attrs)
                )
            continue
        if text == "score":
            out.appendAttributedString_(
                NSAttributedString.alloc().initWithString_attributes_(values["score"], score_attrs)
            )
        elif text in values:
            out.appendAttributedString_(
                NSAttributedString.alloc().initWithString_attributes_(values[text], plain_attrs)
            )
        else:
            literal = "${" + text + "}" if kind == "braced" else f"${text}"
            out.appendAttributedString_(
                NSAttributedString.alloc().initWithString_attributes_(literal, plain_attrs)
            )
    return out


def _acquire_instance_lock() -> None:
    """Ensure only one ClaudeStats process runs at a time.

    No-op on platforms without fcntl (Windows). Defined here so tests can
    patch menubar.os and menubar.fcntl transparently.
    """
    if not _HAS_FCNTL:
        return
    global _instance_lock_fd  # noqa: PLW0603
    _CLAUDE_DIR.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(_LOCK_PATH), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        os.close(fd)
        raise CLIError("ClaudeStats is already running.", ExitCode.ERROR)
    os.write(fd, f"{os.getpid()}\n".encode())
    _instance_lock_fd = fd  # keep fd open so the OS holds the lock for our lifetime


if __name__ == "__main__":  # pragma: no cover
    TelemetryMenubarApp().run()
