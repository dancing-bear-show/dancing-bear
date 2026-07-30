"""Manage the ClaudeStats "launch at login" LaunchAgent.

macOS loads every plist under ``~/Library/LaunchAgents`` at login, so enabling
the feature is just writing a plist and disabling it is removing that file —
no ``launchctl`` subprocess required. The change takes effect at the next login.

Stdlib-only (no rumps/AppKit) so the helpers import and unit-test on any
platform.
"""

from __future__ import annotations

import os
import plistlib
import sys
import tempfile
from pathlib import Path

_BUNDLE_ID = "com.dancing-bear.claudestats"
_PLIST_NAME = f"{_BUNDLE_ID}.plist"
_LAUNCH_AGENTS_DIR = Path.home() / "Library" / "LaunchAgents"


def bundle_path() -> Path | None:
    """Return the running ``.app`` bundle root, or None when not bundled.

    py2app sets ``sys.executable`` to the embedded interpreter at
    ``<App>.app/Contents/MacOS/python`` (not the app launcher), so match that
    exact structure and return the enclosing ``.app``. Matching on path parts
    rather than a ``/``-delimited substring keeps this correct regardless of
    the platform path separator — on non-macOS there is no such layout, so it
    returns None, which is the right answer for a macOS-only feature.
    """
    exe = Path(sys.executable).resolve()
    if exe.parent.name == "MacOS" and exe.parent.parent.name == "Contents":
        app = exe.parent.parent.parent
        if app.suffix == ".app" and app.name != ".app":
            return app
    return None


def is_bundle_mode() -> bool:
    """Return True when running from inside a ``.app`` bundle (py2app)."""
    return bundle_path() is not None


def plist_path() -> Path:
    """Return the LaunchAgent plist path for ClaudeStats."""
    return _LAUNCH_AGENTS_DIR / _PLIST_NAME


def build_plist(bundle: Path) -> bytes:
    """Return the LaunchAgent plist XML that launches ``bundle`` at login."""
    spec = {
        "Label": _BUNDLE_ID,
        "ProgramArguments": ["/usr/bin/open", str(bundle)],
        "RunAtLoad": True,
        "KeepAlive": False,
        "LimitLoadToSessionType": "Aqua",
    }
    return plistlib.dumps(spec, fmt=plistlib.FMT_XML)


def is_enabled() -> bool:
    """Return True if the LaunchAgent plist exists on disk."""
    return plist_path().exists()


def enable() -> None:
    """Write the LaunchAgent plist for the running app.

    Raises:
        RuntimeError: when not running from an installed ``.app`` bundle.
        OSError: when the plist cannot be written.
    """
    bundle = bundle_path()
    if bundle is None:
        raise RuntimeError("Start at Login requires the installed ClaudeStats.app")

    target = plist_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    data = build_plist(bundle)
    fd = tempfile.NamedTemporaryFile(
        mode="wb",
        dir=target.parent,
        delete=False,
        suffix=".tmp",
    )
    try:
        fd.write(data)
        fd.close()
        os.replace(fd.name, target)
    except Exception:  # nosec B110 - cleanup then re-raise; broad catch ensures tmp file is removed on any write error
        fd.close()
        try:
            os.unlink(fd.name)
        except OSError:  # nosec B110 - cleanup failure is non-fatal; original exception re-raised below
            pass
        raise


def disable() -> None:
    """Remove the LaunchAgent plist. No-op if it does not exist."""
    plist_path().unlink(missing_ok=True)
