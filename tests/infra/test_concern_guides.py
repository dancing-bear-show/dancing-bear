"""Verify concerns/*.md contains no repo-path:line citations that will drift."""
import re
import unittest
from pathlib import Path

# Repo root is two levels above this file (tests/infra/test_concern_guides.py).
_REPO_ROOT = Path(__file__).parent.parent.parent
_CONCERNS_DIR = _REPO_ROOT / "concerns"

# Top-level directories whose paths must not appear with a trailing :N line ref.
_REPO_DIRS = frozenset(
    ["src", "workflows", "tests", "bin", ".claude", "concerns", "configs"]
)

# Also catch bare <name>.<ext>:N without a leading directory.
_BARE_PATTERN = re.compile(
    r"`?(?:[A-Za-z0-9_.\-/]+/)?"  # optional directory prefix
    r"([A-Za-z0-9_.\-]+\.(?:py|yaml|yml|sh|md))"  # filename with extension
    r":(\d+)"  # :line-number
    r"`?"
)

# Pattern that requires a known repo-dir prefix or a bare filename match.
_DIR_PREFIX = re.compile(
    r"`?(?:"
    + "|".join(re.escape(d) for d in sorted(_REPO_DIRS))
    + r")/[^:]+\.(?:py|yaml|yml|sh|md):\d+"
    r"`?"
)

_BARE_FILE_PATTERN = re.compile(
    r"`?[A-Za-z0-9_.\-]+\.(?:py|yaml|yml|sh|md):\d+`?"
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


if __name__ == "__main__":
    unittest.main()
