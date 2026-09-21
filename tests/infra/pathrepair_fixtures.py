"""Decoy-checkout builders shared by the import-path repair suites.

``tests/infra/test_router_pythonpath.py`` (generated wrappers) and
``tests/infra/test_pathrepair_shared.py`` (the standalone bin/llm and
bin/path-guard scripts) both need the same two fixtures, and both must agree on
what "a checkout of this project" looks like. Keeping one definition means a
change to the marker cannot leave one suite testing the old shape while the
other tests the new one.
"""

from __future__ import annotations

from pathlib import Path

#: Sibling ``pyproject.toml`` content that marks a directory as THIS project.
#: Must stay in sync with ``bin/_pathrepair.py``'s ``PROJECT_MARKER`` — the
#: repair strips a ``src`` entry only when its sibling pyproject names this
#: project, so a fixture using any other name would not be stripped and the
#: test would pass vacuously.
PROJECT_MARKER_NAME = "personal-assistants"


def make_fake_checkout(root: Path, package: str = "core") -> Path:
    """Build a decoy checkout of THIS project and return its ``src`` dir.

    The decoy carries a matching ``pyproject.toml`` plus ``src/<package>/``, so
    it can genuinely shadow the real package and not merely sit inertly on the
    path.

    ``core`` is the default because it is what the standalone scripts import
    from; pass ``"mail"`` (or another package) where a different shadow is
    wanted.
    """
    pkg = root / "src" / package
    pkg.mkdir(parents=True)
    (root / "pyproject.toml").write_text(
        f'[project]\nname = "{PROJECT_MARKER_NAME}"\nversion = "0.1.0"\n'
    )
    (pkg / "__init__.py").write_text('ORIGIN = "decoy"\n')
    return root / "src"


def make_third_party_checkout(root: Path) -> Path:
    """Build an UNRELATED project that also has ``src/`` and a pyproject.toml.

    This is the negative case: a pyproject.toml is not the marker — one naming
    this project is. Stripping on its mere presence would silently remove
    entries the repair has no business touching.
    """
    (root / "src").mkdir(parents=True)
    (root / "pyproject.toml").write_text('[project]\nname = "some-other-lib"\n')
    return root / "src"


def make_unmarked_src(root: Path) -> Path:
    """Build a bare ``src`` directory with NO sibling pyproject.toml at all."""
    src = root / "src"
    src.mkdir(parents=True)
    return src
