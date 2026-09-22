"""Rejection of non-path values handed to filesystem helpers.

``Path()`` accepts anything with a ``__fspath__``, and a ``MagicMock`` supplies
one, so a mock reaching a write helper does not raise — it is stringified into
its own repr and the slashes inside that repr become real directories::

    >>> Path(MagicMock().log_path)
    PosixPath('MagicMock/mock.log_path/4428358352')

A helper that then calls ``path.parent.mkdir(parents=True)`` creates
``MagicMock/mock.log_path`` on disk and carries on. The write appears to
succeed, the assertion under test passes, and the only trace is a junk
directory in the working tree — which is how one of these survived long enough
in this repo to be mistaken for a source tree and documented as one.

The failure mode is not limited to mocks: any object with a ``__fspath__``
returning something path-like (a config wrapper, a lazily-resolved setting)
lands in the same place. Guarding at the boundary turns a silent mkdir into a
``TypeError`` naming the offending type and argument.
"""

from __future__ import annotations

import os
from pathlib import Path

__all__ = ["require_path"]

# Types that legitimately name a filesystem location. `os.PathLike` covers
# `Path` and anything implementing `__fspath__` in a real way; `str` covers the
# plain-string callers, which are the majority.
_PATH_TYPES = (str, os.PathLike)


def require_path(value: object, *, argument: str = "path") -> Path:
    """Return ``value`` as a :class:`Path`, rejecting values that only look like one.

    Args:
        value: The caller-supplied path.
        argument: Parameter name, used in the error message so the caller can
            see which argument was wrong.

    Returns:
        ``value`` coerced to a :class:`Path`.

    Raises:
        TypeError: When ``value`` is not a ``str`` or ``os.PathLike``, or is a
            mock object. Mocks satisfy ``os.PathLike`` structurally, so they are
            checked for by module rather than by type.
    """
    if _is_mock(value):
        raise TypeError(
            f"{argument} is a mock ({type(value).__name__}), not a filesystem path. "
            "The code under test never received a real path, so this write would "
            "have silently created a directory named after the mock's repr. Bind a "
            "real path (tmp_path / a TemporaryDirectory) or assert on the call "
            "instead of the file."
        )

    if not isinstance(value, _PATH_TYPES):
        raise TypeError(
            f"{argument} must be str or os.PathLike, got {type(value).__name__}"
        )

    return Path(value)


def _is_mock(value: object) -> bool:
    """Return True when *value* comes from :mod:`unittest.mock`.

    Checked by the defining module rather than with ``isinstance`` against
    ``unittest.mock.Mock``: a ``MagicMock`` passes an ``os.PathLike`` check
    structurally, and importing mock into production code to compare types
    would pull a test dependency into the runtime path. The module name is
    stable across ``Mock``, ``MagicMock``, ``AsyncMock`` and ``NonCallableMock``.
    """
    return type(value).__module__ == "unittest.mock"
