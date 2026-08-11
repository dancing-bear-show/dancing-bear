"""Resolution of the directory generated artifacts are written to.

Output defaulted to a relative path ("out", "_out"), which resolves against the
current working directory — so running a command from the repo wrote generated
files, including resumes carrying a name, phone number, and email, inside the
checkout. Those paths are gitignored, which stops an accidental commit but not
an accidental deletion: `git clean -fdx` removes ignored files, and the user's
only copy goes with them.

Artifacts now land outside the checkout by default. Resolution order:

  1. an explicit path passed by the caller (a CLI's ``--out-dir``)
  2. ``DANCING_BEAR_DATA_HOME``
  3. ``XDG_DATA_HOME``/dancing-bear
  4. ``~/.local/share/dancing-bear``

This mirrors the credential lookup in ``core.constants``, which reads
``CREDENTIALS`` then ``XDG_CONFIG_HOME`` then ``~/.config``. Generated output
goes under the DATA root rather than the CONFIG one: ``~/.config`` is for
settings a user writes, and a rendered DOCX is not that.

Relative paths a caller passes are honoured as-is, resolved against the working
directory, so ``--out-dir out`` still writes to ./out for anyone who wants the
old behaviour or is scripting against it.
"""

from __future__ import annotations

import os
from pathlib import Path

# Env var overriding the data root for this project specifically. Checked before
# XDG_DATA_HOME so a user can relocate this project's output without moving
# every XDG-aware program's.
ENV_DATA_HOME = "DANCING_BEAR_DATA_HOME"

# Directory created under the XDG data root.
APP_DIR_NAME = "dancing-bear"

_XDG_DATA_HOME = "XDG_DATA_HOME"
_DEFAULT_DATA_HOME = "~/.local/share"


def data_home() -> Path:
    """Return the root directory generated artifacts are written under.

    Does not create the directory; callers that write to it should mkdir with
    ``parents=True``.
    """
    override = os.environ.get(ENV_DATA_HOME)
    if override:
        return Path(os.path.expanduser(override))

    xdg = os.environ.get(_XDG_DATA_HOME)
    if xdg:
        return Path(os.path.expanduser(xdg)) / APP_DIR_NAME

    return Path(os.path.expanduser(_DEFAULT_DATA_HOME)) / APP_DIR_NAME


def output_dir(domain: str, override: str | os.PathLike[str] | None = None) -> Path:
    """Return the output directory for ``domain`` ("resume", "charts", ...).

    ``override`` wins when set — that is the CLI's ``--out-dir``, and a user who
    names a path means it, relative or not. Otherwise the domain gets its own
    subdirectory under :func:`data_home`, so one domain's output cannot collide
    with another's.
    """
    if override:
        return Path(os.path.expanduser(str(override)))
    return data_home() / domain
