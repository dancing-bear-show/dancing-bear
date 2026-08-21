"""Guards that real mail filter rules stay out of the repository.

`config/filters_unified.yaml` held a user's actual rules — hundreds of sender
domains plus family forwarding addresses — and was committed to a public repo.
The rules now live in ``~/.config/dancing-bear/``; only the synthetic template
is tracked. These tests fail if that regresses.
"""

import subprocess
import unittest
from pathlib import Path

import yaml

from mail.config_cli.commands import UNIFIED_FILTERS_NAME, resolve_filters_config

# tests/mail_tests/test_filters_config_privacy.py -> mail_tests -> tests -> checkout
REPO_ROOT = Path(__file__).resolve().parents[2]
EXAMPLE = REPO_ROOT / "config" / "filters_unified.example.yaml"


def _tracked_files() -> list[str]:
    """Paths git currently tracks, or [] when git is unavailable."""
    try:
        out = subprocess.run(
            ["git", "ls-files"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):  # pragma: no cover - env-dependent
        return []
    return out.stdout.splitlines() if out.returncode == 0 else []


class TestRealFiltersAreNotTracked(unittest.TestCase):
    def test_real_unified_filters_is_not_committed(self):
        tracked = _tracked_files()
        if not tracked:
            self.skipTest("git not available")
        offenders = [
            p
            for p in tracked
            if Path(p).name == UNIFIED_FILTERS_NAME
        ]
        self.assertEqual(
            [],
            offenders,
            f"{UNIFIED_FILTERS_NAME} must not be tracked; it holds personal mail rules. "
            "Keep it in ~/.config/dancing-bear/ and commit only the .example.yaml.",
        )

    def test_example_template_is_tracked(self):
        tracked = _tracked_files()
        if not tracked:
            self.skipTest("git not available")
        self.assertIn("config/filters_unified.example.yaml", tracked)

    def test_gitignore_covers_the_real_file(self):
        """`git check-ignore` is the authority — pattern order in .gitignore is subtle."""
        real = REPO_ROOT / "config" / UNIFIED_FILTERS_NAME
        result = subprocess.run(
            ["git", "check-ignore", "-q", str(real)],
            cwd=REPO_ROOT,
            capture_output=True,
            timeout=30,
            check=False,
        )
        self.assertEqual(
            0, result.returncode, f"config/{UNIFIED_FILTERS_NAME} is not gitignored"
        )


class TestExampleIsSynthetic(unittest.TestCase):
    """The template ships publicly, so it must contain no real contact data."""

    def setUp(self):
        self.doc = yaml.safe_load(EXAMPLE.read_text())

    def test_parses_and_has_rules(self):
        self.assertTrue(self.doc.get("filters"))

    def test_every_forward_address_is_a_reserved_example_domain(self):
        for rule in self.doc["filters"]:
            fwd = (rule.get("action") or {}).get("forward")
            if fwd:
                self.assertTrue(
                    fwd.endswith(("@example.com", "@example.org", "@example.net")),
                    f"non-example forward address in template: {fwd}",
                )

    def test_every_sender_uses_a_reserved_example_domain(self):
        """RFC 2606 reserves example.com/org/net; anything else may be a real party."""
        for rule in self.doc["filters"]:
            senders = (rule.get("match") or {}).get("from", "")
            for term in senders.split(" OR "):
                term = term.strip()
                if not term:
                    continue
                host = term.split("@")[-1]
                self.assertTrue(
                    host.endswith(("example.com", "example.org", "example.net", "example.edu")),
                    f"non-example sender in template: {term}",
                )

    def test_documents_the_external_config_location(self):
        text = EXAMPLE.read_text()
        self.assertIn("~/.config/dancing-bear/", text)


class TestResolveFiltersConfig(unittest.TestCase):
    def test_explicit_flag_wins(self):
        args = type("A", (), {"in_path": "/tmp/explicit.yaml"})()
        self.assertEqual("/tmp/explicit.yaml", resolve_filters_config(args))

    def test_missing_attribute_falls_back_to_config_home(self):
        resolved = resolve_filters_config(type("A", (), {})())
        self.assertTrue(resolved.endswith(UNIFIED_FILTERS_NAME))
        self.assertFalse(Path(resolved).is_relative_to(REPO_ROOT))

    def test_none_falls_back_to_config_home(self):
        args = type("A", (), {"in_path": None})()
        self.assertFalse(Path(resolve_filters_config(args)).is_relative_to(REPO_ROOT))

    def test_reads_alternate_attribute_name(self):
        """`workflows` subcommands spell the flag --config, not --in."""
        args = type("A", (), {"config": "/tmp/wf.yaml"})()
        self.assertEqual("/tmp/wf.yaml", resolve_filters_config(args, "config"))


if __name__ == "__main__":
    unittest.main()
