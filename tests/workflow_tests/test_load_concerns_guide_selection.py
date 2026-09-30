"""Verify load-concerns.yaml always selects collateral-damage.md.

Checks:
- The description's "always include" line lists collateral-damage.md.
- The select-guides stage rules list collateral-damage.md in the always-include rule.
- The no-params default also lists collateral-damage.md.
"""

from __future__ import annotations

import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).parent.parent.parent
_WORKFLOW = _REPO_ROOT / "workflows" / "code" / "load-concerns.yaml"


def _load() -> str:
    return _WORKFLOW.read_text(encoding="utf-8")


class TestLoadConcernsAlwaysIncludes(unittest.TestCase):
    """collateral-damage.md must appear in every always-include position."""

    def setUp(self) -> None:
        self.text = _load()

    def test_description_always_include_has_collateral_damage(self) -> None:
        """The workflow description's 'always include' line must list collateral-damage.md."""
        for line in self.text.splitlines():
            if "always include" in line and "→" in line:
                self.assertIn(
                    "collateral-damage.md",
                    line,
                    msg="description 'always include' line is missing collateral-damage.md",
                )
                return
        self.fail("No 'always include' line with → found in load-concerns.yaml description")

    def test_select_guides_stage_always_include_has_collateral_damage(self) -> None:
        """The select-guides stage Rules section's 'always include' line must list collateral-damage.md."""
        found = False
        for line in self.text.splitlines():
            if "always include" in line and "→" in line:
                found = True
                self.assertIn(
                    "collateral-damage.md",
                    line,
                    msg=f"'always include' line missing collateral-damage.md: {line!r}",
                )
        self.assertTrue(found, msg="No 'always include → ...' line found in load-concerns.yaml")

    def test_no_params_default_has_collateral_damage(self) -> None:
        """The 'If no file_paths and no task_type, default to:' line must include collateral-damage.md."""
        for line in self.text.splitlines():
            if "no file_paths" in line and "no task_type" in line:
                self.assertIn(
                    "collateral-damage.md",
                    line,
                    msg="no-params default line is missing collateral-damage.md",
                )
                return
        self.fail("No 'no file_paths and no task_type' default line found in load-concerns.yaml")

    def test_collateral_damage_count(self) -> None:
        """collateral-damage.md should appear at least twice (description + stage rules + default)."""
        count = self.text.count("collateral-damage.md")
        self.assertGreaterEqual(
            count,
            3,
            msg=f"Expected collateral-damage.md at least 3 times in load-concerns.yaml, got {count}",
        )


if __name__ == "__main__":
    unittest.main()
