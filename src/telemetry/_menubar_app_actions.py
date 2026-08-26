"""Actions mixin extracted from _menubar_app.py."""
from __future__ import annotations

import time
from pathlib import Path

from telemetry._menubar_config import (
    _config_to_text,
    _parse_config_text,
    _save_config,
)
from telemetry import login_item as _login_item

try:
    from AppKit import (  # type: ignore[import-not-found]
        NSPasteboard,
        NSPasteboardTypeString,
    )
    _HAS_APPKIT = True
except ImportError:
    _HAS_APPKIT = False

_STORAGE_WARN_DAYS = 30


class ActionsMixin:
    """User-action methods: configure, clear, toggle login item, notify, clipboard."""

    @staticmethod
    def _notify(title: str, body: str) -> None:
        try:
            import rumps as _rumps  # type: ignore[import-not-found]
            _rumps.notification(title=title, subtitle="", message=body[:200])
        except Exception:  # nosec B110 - notification failure is non-fatal
            pass

    @staticmethod
    def _copy_to_clipboard(text: str) -> None:
        if _HAS_APPKIT:
            try:
                pb = NSPasteboard.generalPasteboard()
                pb.clearContents()
                pb.setString_forType_(text, NSPasteboardTypeString)
                return
            except Exception:  # nosec B110 - AppKit clipboard failure falls through to pbcopy
                pass
        try:
            import subprocess as _sp  # nosec B404 - subprocess imported deliberately; individual call sites carry their own B602/B603 review
            _sp.run(["pbcopy"], input=text.encode(), check=False)  # nosec B603 B607 - fixed macOS system utility, no dynamic args
        except Exception:  # nosec B110 - pbcopy failure is non-fatal; clipboard update is best-effort
            pass

    def _on_configure(self, _sender: object) -> None:  # noqa: ARG002
        import rumps as _rumps  # type: ignore[import-not-found]
        from telemetry._menubar_config import _load_config
        cfg = _load_config()
        win = _rumps.Window(
            title="ClaudeStats — Configure",
            message=(
                "Edit settings below.\n"
                "Sections: on/off  •  Rows: on/off  •  max_tips: 1–10\n"
                "Changes take effect immediately on Save."
            ),
            default_text=_config_to_text(cfg),
            ok="Save", cancel="Cancel", dimensions=(340, 220),
        )
        response = win.run()
        if response.clicked != 1:
            return
        updated, rejected = _parse_config_text(response.text, cfg)
        try:
            _save_config(updated)
        except Exception as exc:  # nosec B110 - save failure surfaced to user via alert
            _rumps.alert(title="Save failed", message=str(exc))
            return
        self._rebuild_menu(updated)  # type: ignore[attr-defined]
        self._last_cfg = updated  # type: ignore[attr-defined]
        self._refresh(None)  # type: ignore[attr-defined]
        if rejected:
            preview = "\n".join(f"  • {line}" for line in rejected[:8])
            extra = f"\n  …and {len(rejected) - 8} more" if len(rejected) > 8 else ""
            _rumps.alert(
                title="Some settings weren't applied",
                message=(
                    "These lines were saved but ignored because the value "
                    "failed validation or the key isn't recognized:\n\n"
                    f"{preview}{extra}\n\nOther settings were saved normally."
                ),
            )

    def _on_toggle_login_item(self, _sender: object) -> None:  # noqa: ARG002
        import rumps as _rumps  # type: ignore[import-not-found]
        if not _login_item.is_bundle_mode():
            _rumps.alert(title="Start at Login", message=(
                "This feature requires the packaged ClaudeStats app. "
                "Launch the installed .app bundle, then try again."
            ))
            return
        try:
            if _login_item.is_enabled():
                _login_item.disable()
            else:
                _login_item.enable()
        except (OSError, RuntimeError) as exc:
            _rumps.alert(title="Start at Login", message=f"Could not update login item: {exc}")
        self._btn_login_item.state = 1 if _login_item.is_enabled() else 0  # type: ignore[attr-defined]

    @staticmethod
    def _clear_stale_project_dir(project_dir: Path, cutoff: float) -> int:
        """Delete stale .jsonl files in project_dir; remove the dir if left empty.

        Returns the number of files deleted.
        """
        deleted = 0
        for jsonl_file in project_dir.glob("*.jsonl"):
            if jsonl_file.stat().st_mtime < cutoff:
                jsonl_file.unlink()
                deleted += 1
        try:
            next(project_dir.iterdir())
        except StopIteration:
            project_dir.rmdir()
        return deleted

    def _on_clear(self, _sender: object) -> None:  # noqa: ARG002
        import rumps as _rumps  # type: ignore[import-not-found]
        response = _rumps.alert(
            title="Clear old sessions",
            message=(
                "Delete all .jsonl session files older than 30 days "
                "from ~/.claude/projects/?\n\nThis cannot be undone."
            ),
            ok="Delete", cancel="Cancel",
        )
        if response != 1:
            return
        _PROJECTS_DIR = Path.home() / ".claude" / "projects"
        cutoff = time.time() - _STORAGE_WARN_DAYS * 86400
        deleted = 0
        try:
            for project_dir in _PROJECTS_DIR.iterdir():
                if not project_dir.is_dir():
                    continue
                deleted += self._clear_stale_project_dir(project_dir, cutoff)
        except Exception as exc:  # nosec B110 - partial cleanup failure is reported via notification
            _rumps.notification(title="Clear failed", subtitle="Could not delete all files", message=str(exc))
            return
        _rumps.notification(
            title="Sessions cleared",
            subtitle=f"{deleted} file{'s' if deleted != 1 else ''} deleted",
            message="Session files older than 30 days have been removed.",
        )
        self._refresh(None)  # type: ignore[attr-defined]
