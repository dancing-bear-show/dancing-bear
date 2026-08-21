"""Resolution of the directories generated artifacts and user config live in.

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

Config the user writes resolves the same way against the CONFIG root
(``DANCING_BEAR_CONFIG_HOME``, ``XDG_CONFIG_HOME``/dancing-bear,
``~/.config/dancing-bear``). Mail filter rules live there rather than in the
checkout: a filter set enumerates the sender domains someone receives mail from
and the addresses they forward to, which is personal data that should not be
committed — least of all to a public repository.
"""

from __future__ import annotations

import os
from pathlib import Path

# Env var overriding the data root for this project specifically. Checked before
# XDG_DATA_HOME so a user can relocate this project's output without moving
# every XDG-aware program's.
ENV_DATA_HOME = "DANCING_BEAR_DATA_HOME"

# Env var overriding the config root, mirroring ENV_DATA_HOME.
ENV_CONFIG_HOME = "DANCING_BEAR_CONFIG_HOME"

# Directory created under the XDG data root.
APP_DIR_NAME = "dancing-bear"

_XDG_DATA_HOME = "XDG_DATA_HOME"
_DEFAULT_DATA_HOME = "~/.local/share"

_XDG_CONFIG_HOME = "XDG_CONFIG_HOME"
_DEFAULT_CONFIG_HOME = "~/.config"


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


def config_home() -> Path:
    """Return the root directory user-authored configuration is read from.

    Resolution mirrors :func:`data_home` but against the CONFIG root, matching
    the credential lookup in ``core.constants``. Does not create the directory.
    """
    override = os.environ.get(ENV_CONFIG_HOME)
    if override:
        return Path(os.path.expanduser(override))

    xdg = os.environ.get(_XDG_CONFIG_HOME)
    if xdg:
        return Path(os.path.expanduser(xdg)) / APP_DIR_NAME

    return Path(os.path.expanduser(_DEFAULT_CONFIG_HOME)) / APP_DIR_NAME


def config_file(name: str, override: str | os.PathLike[str] | None = None) -> Path:
    """Return the path to config file ``name`` ("filters_unified.yaml", ...).

    ``override`` wins when set — that is the CLI's ``--config``/``--in``, and a
    user who names a path means it. Otherwise the file is read from
    :func:`config_home`.

    Config holding a user's own mail rules stays outside the checkout: the
    sender domains and forwarding addresses in a filter set describe who someone
    banks with, where their kids go to school, and who they email, which is not
    something a clone of this repo should carry.
    """
    if override:
        return Path(os.path.expanduser(str(override)))
    return config_home() / name


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
