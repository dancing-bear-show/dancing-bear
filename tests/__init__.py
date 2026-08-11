"""Test package initialization.

Ensures the repository-local ``src/`` is imported ahead of any editable
install. The project's ``.venv`` lives in the main checkout and its editable
``.pth`` hardcodes that checkout's ``src/``; without this, running
``python3 -m unittest`` from a git worktree would silently import and test the
MAIN checkout's code instead of the worktree's. Prepending the local ``src``
(the same effect as the Makefile's ``PYTHONPATH=src``) makes tests always
exercise the tree they were launched from.

Also installs the interactive-auth guard below.
"""

from __future__ import annotations

import sys
import webbrowser
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "src"
if _SRC.is_dir():
    _src_str = str(_SRC)
    # Drop any *other* checkout's src that an editable .pth may have added
    # (a sibling path ending in "/src" that isn't ours), plus the local one if
    # already present, then prepend the local src so this tree wins regardless
    # of sys.path ordering.
    sys.path[:] = [
        p for p in sys.path
        if p != _src_str and not (p.endswith("/src") and "/dancing-bear/" in p)
    ]
    sys.path.insert(0, _src_str)


# --- Interactive-auth guard -------------------------------------------------
# A command that builds a provider before dispatching (or a test that forgets
# to patch ``gmail_provider_from_args``) reaches
# ``InstalledAppFlow.run_local_server``, which binds a real port and opens a
# browser for a live OAuth consent screen. On a developer machine with real
# credentials present that hangs the suite and mints a real token; the only
# reason it does not do so in CI is the absence of a credentials file.
#
# Fail loudly instead. Patching the definition site does intercept these calls,
# so isolated tests are unaffected -- this only fires when isolation is missing.
class InteractiveAuthAttempted(RuntimeError):
    """Raised when a test reaches an interactive authentication flow."""


def _blocked_auth(*_args: object, **_kwargs: object) -> None:
    raise InteractiveAuthAttempted(
        "A test reached an interactive OAuth flow. Patch the provider factory "
        "at its definition site, e.g. "
        "patch('mail.utils.cli_helpers.gmail_provider_from_args', return_value=fake)."
    )


try:
    from google_auth_oauthlib.flow import InstalledAppFlow
except ImportError:  # optional dep; nothing to guard when it is absent
    pass
else:
    InstalledAppFlow.run_local_server = _blocked_auth  # type: ignore[method-assign]
    InstalledAppFlow.run_console = _blocked_auth  # type: ignore[method-assign]

# Opening a browser is never correct under test, whatever triggers it.
webbrowser.open = _blocked_auth  # type: ignore[assignment]
webbrowser.open_new = _blocked_auth  # type: ignore[assignment]
webbrowser.open_new_tab = _blocked_auth  # type: ignore[assignment]
