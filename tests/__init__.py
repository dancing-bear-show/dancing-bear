"""Test package initialization.

Ensures the repository-local ``src/`` is imported ahead of any editable
install. The project's ``.venv`` lives in the main checkout and its editable
``.pth`` hardcodes that checkout's ``src/``; without this, running
``python3 -m unittest`` from a git worktree would silently import and test the
MAIN checkout's code instead of the worktree's. Prepending the local ``src``
(the same effect as the Makefile's ``PYTHONPATH=src``) makes tests always
exercise the tree they were launched from.

Also installs the interactive-auth guard below, and sets a process-wide
private worker state directory so that no test can accidentally write to the
user's real queue (see CLAUDE.md "Testing" section).
"""

from __future__ import annotations

import importlib.util as _ilu
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


# --- Process-wide private worker state dir ----------------------------------
# Per-test isolation (QueueRootIsolationMixin) redirects queue_ops.QUEUE_ROOT
# and DANCING_BEAR_WORKER_STATE_DIR per test and restores them on teardown.
# That is NOT enough: a worker thread that outlives its test finishes after the
# restore and writes into the "original" value — which, without this guard, is
# the user's real ~/Library/Application Support/dancing-bear/.
#
# The fix lives in tests/_private_worker_state.py and is also called from the
# __init__.py of worker_tests, workflow_tests and infra, which covers
# `discover -s tests` without -t.  `discover -s tests/<pkg>` without -t imports
# none of these files and is unsupported.  See CLAUDE.md "Testing" section.
_BOOTSTRAP = Path(__file__).parent / "_private_worker_state.py"
_BOOTSTRAP_KEY = "_dancing_bear_private_worker_state"
if _BOOTSTRAP_KEY not in sys.modules:
    _spec = _ilu.spec_from_file_location(_BOOTSTRAP_KEY, _BOOTSTRAP)
    if _spec is not None and _spec.loader is not None:
        _mod = _ilu.module_from_spec(_spec)
        sys.modules[_BOOTSTRAP_KEY] = _mod
        _spec.loader.exec_module(_mod)  # type: ignore[union-attr]
sys.modules[_BOOTSTRAP_KEY].ensure_private()  # type: ignore[attr-defined]


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
    InstalledAppFlow.run_local_server = _blocked_auth
    InstalledAppFlow.run_console = _blocked_auth

# Opening a browser is never correct under test, whatever triggers it.
webbrowser.open = _blocked_auth  # type: ignore[assignment]
webbrowser.open_new = _blocked_auth  # type: ignore[assignment]
webbrowser.open_new_tab = _blocked_auth  # type: ignore[assignment]
