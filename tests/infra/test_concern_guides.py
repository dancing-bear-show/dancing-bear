"""Verify concerns/*.md contains no repo-path:line citations that will drift."""
import re
import unittest
from pathlib import Path

# Repo root is two levels above this file (tests/infra/test_concern_guides.py).
_REPO_ROOT = Path(__file__).parent.parent.parent
_CONCERNS_DIR = _REPO_ROOT / "concerns"

# Top-level directories whose paths must not appear with a trailing :N line ref.
_REPO_DIRS = frozenset(
    ["src", "workflows", "tests", "bin", ".claude", "concerns", "config", "configs"]
)

# <repo-dir>/<path>.<ext>:N under one of the known top-level directories. The
# extension is any dotted suffix, not a hardcoded list, so a citation to a
# non-.py/.yaml/.yml/.sh/.md path (e.g. src/data.json:12) is still caught.
_DIR_PREFIX = re.compile(
    r"`?(?:"
    + "|".join(re.escape(d) for d in sorted(_REPO_DIRS))
    + r")/[^:]+\.[A-Za-z0-9]+:\d+"
    r"`?"
)

# Any <name>.<ext>:N, including a bare filename with no leading directory.
_BARE_FILE_PATTERN = re.compile(
    r"`?[A-Za-z0-9_.\-]+\.[A-Za-z0-9]+:\d+`?"
)


class TestConcernGuideCitations(unittest.TestCase):
    """No concerns/*.md file may cite a repo path with a line number."""

    def test_no_path_line_citations(self) -> None:
        offenders: list[str] = []
        for guide in sorted(_CONCERNS_DIR.glob("*.md")):
            for lineno, text in enumerate(guide.read_text(encoding="utf-8").splitlines(), 1):
                if _DIR_PREFIX.search(text) or _BARE_FILE_PATTERN.search(text):
                    offenders.append(f"{guide.name}:{lineno}: {text.strip()[:120]}")
        self.assertEqual(
            offenders,
            [],
            msg="Repo-path:line citations found in concern guides (these drift):\n"
            + "\n".join(offenders),
        )


class TestCitationPatternCoverage(unittest.TestCase):
    """Regression coverage for the two gaps found in review: a hardcoded
    extension list that let non-.py/.yaml/.yml/.sh/.md citations through, and
    a `config/` vs `configs/` allowlist misspelling."""

    def test_matches_non_hardcoded_extension(self) -> None:
        """A citation to a path with an extension outside the old five-item
        list (json, toml, ...) must still be caught."""
        self.assertIsNotNone(_DIR_PREFIX.search("see `src/data.json:12` for detail"))
        self.assertIsNotNone(_BARE_FILE_PATTERN.search("see `schema.toml:4` for detail"))

    def test_matches_config_directory(self) -> None:
        """`config/` (not just `configs/`) must be in the allowlist, since
        both are real top-level directories (config/filters_unified.example.yaml,
        configs/launchd)."""
        self.assertIsNotNone(
            _DIR_PREFIX.search("see `config/filters_unified.example.yaml:12` for detail")
        )
        self.assertIsNone(_DIR_PREFIX.search("see config/filters_unified.example.yaml for detail"))

    def test_does_not_match_prose_without_line_ref(self) -> None:
        """Prose that merely mentions a file extension, with no trailing
        :N line reference, must not be flagged."""
        self.assertIsNone(_DIR_PREFIX.search("edit config/filters_unified.example.yaml directly"))
        self.assertIsNone(_BARE_FILE_PATTERN.search("a schema.toml file lives here"))


if __name__ == "__main__":
    unittest.main()
