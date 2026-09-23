"""Tests that pyproject.toml's setuptools packaging include list stays in
sync with the top-level packages under src/.

A package directory can exist and be fully wired into the CLI (registered
wrapper, entry point, tests) while still being silently omitted from
[tool.setuptools.packages.find].include, which means `pip install .` (or any
sdist/wheel build) drops the package entirely. The local `./bin/*` wrappers
still work because they force `src/` onto sys.path directly, which is what
lets the gap hide from every dev workflow.
"""

from __future__ import annotations

import sys
import unittest

from tests.fixtures import repo_root

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover - repo requires Python >=3.11
    import tomli as tomllib  # type: ignore[no-redef]


def _top_level_src_packages() -> set[str]:
    """Every directory directly under src/ that has an __init__.py."""
    src = repo_root() / "src"
    return {
        child.name
        for child in src.iterdir()
        if child.is_dir() and (child / "__init__.py").is_file()
    }


def _packaging_include_list() -> list[str]:
    pyproject = repo_root() / "pyproject.toml"
    with pyproject.open("rb") as fh:
        data = tomllib.load(fh)
    return data["tool"]["setuptools"]["packages"]["find"]["include"]


class TestPackagingIncludeCoversAllSrcPackages(unittest.TestCase):
    """Every top-level src/ package must be reachable via the include list."""

    def test_every_top_level_package_has_an_include_entry(self):
        packages = _top_level_src_packages()
        include = _packaging_include_list()

        missing = set()
        for package in packages:
            # find's include patterns are fnmatch-style ("name*"); a bare
            # "name" or "name*" entry both cover the top-level package dir.
            covered = any(
                pattern == package or pattern == f"{package}*"
                for pattern in include
            )
            if not covered:
                missing.add(package)

        self.assertEqual(
            missing,
            set(),
            msg=(
                f"src/ packages missing from "
                f"[tool.setuptools.packages.find].include in pyproject.toml: "
                f"{sorted(missing)}. A wheel/sdist build silently omits these "
                f"packages even though local ./bin wrappers still work."
            ),
        )

    def test_github_assistant_is_included(self):
        """Regression pin for the specific package this finding named."""
        include = _packaging_include_list()
        self.assertIn("github_assistant*", include)


if __name__ == "__main__":
    unittest.main()
