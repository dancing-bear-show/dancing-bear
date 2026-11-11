"""Tests for memory.redaction — block aborts, scrub round-trips, masked previews, severity classifications."""

from __future__ import annotations

import unittest

from memory.redaction import REDACTION_RULES, has_blocking, scan, scrub
from tests.memory_tests.fixtures import dirty_memory_text


class TestEveryRuleFires(unittest.TestCase):
    """Each rule in REDACTION_RULES fires on the dirty fixture."""

    def test_every_rule_fires(self) -> None:
        text = dirty_memory_text()
        for rule in REDACTION_RULES:
            with self.subTest(rule_id=rule.rule_id):
                if rule.requires_anonymize:
                    redactions = scan(text, anonymize=True)
                else:
                    redactions = scan(text)

                rule_redactions = [r for r in redactions if r.rule_id == rule.rule_id]

                self.assertGreater(
                    len(rule_redactions),
                    0,
                    f"Rule {rule.rule_id!r} did not fire on dirty_memory_text fixture. "
                    "Verify the fixture string contains a match for this rule's pattern.",
                )

                for redaction in rule_redactions:
                    self.assertIsNotNone(redaction.matched)
                    self.assertNotEqual(redaction.matched, "")
                    self.assertEqual(
                        redaction.matched,
                        rule.replacement,
                        f"Rule {rule.rule_id!r}: matched preview must equal replacement, "
                        f"got {redaction.matched!r}",
                    )


class TestSeverityClassifications(unittest.TestCase):
    """Severity classifications for specific rules."""

    def test_jira_pd_key_is_warn_not_block(self) -> None:
        text = "env: password=hunter2secret"
        redactions = scan(text)
        cred_hits = [r for r in redactions if r.rule_id == "credential-assignment"]
        self.assertGreaterEqual(len(cred_hits), 1, "credential-assignment should fire on password= assignment")
        for r in cred_hits:
            self.assertEqual(
                r.severity,
                "warn",
                f"credential-assignment must be 'warn' not {r.severity!r} — it must not permanently block export",
            )

    def test_benign_password_prose_does_not_trigger_jira_pd_key(self) -> None:
        prose = "the password rotation policy requires 12+ characters and monthly updates."
        redactions = scan(prose)
        cred_hits = [r for r in redactions if r.rule_id == "credential-assignment"]
        self.assertEqual(
            len(cred_hits),
            0,
            "credential-assignment must not fire on prose without assignment syntax (=)",
        )

    def test_abs_home_path_is_scrub(self) -> None:
        text = "working at /Users/alice/code/myproject"
        redactions = scan(text)
        home_path = [r for r in redactions if r.rule_id == "abs-home-path"]
        self.assertGreaterEqual(len(home_path), 1)
        self.assertEqual(home_path[0].severity, "scrub")

    def test_abs_home_path_slug_form_is_scrub(self) -> None:
        text = "slug: -Users-alice-code-myproject"
        redactions = scan(text)
        slug_form = [r for r in redactions if r.rule_id == "abs-home-path-slug-form"]
        self.assertGreaterEqual(len(slug_form), 1)
        self.assertEqual(slug_form[0].severity, "scrub")

    def test_has_blocking_empty_tuple_returns_false(self) -> None:
        self.assertFalse(has_blocking(()))

    def test_has_blocking_with_block_severity_returns_true(self) -> None:
        # AWS key with trailing newline so the pattern's (?:\s|$) matches
        text = "AKIA" + "0123456789ABCDEF\n"
        redactions = scan(text)
        block_reds = tuple(r for r in redactions if r.severity == "block")
        self.assertTrue(has_blocking(block_reds))

    def test_has_blocking_with_only_warn_returns_false(self) -> None:
        text = "ticket TEAM-456 was resolved"
        redactions = scan(text)
        warn_reds = tuple(r for r in redactions if r.severity == "warn")
        if warn_reds:
            self.assertFalse(has_blocking(warn_reds))


class TestBlockAborts(unittest.TestCase):
    """Block severity aborts the export path."""

    def test_dirty_text_has_block_severity(self) -> None:
        text = dirty_memory_text()
        redactions = scan(text)
        block_reds = [r for r in redactions if r.severity == "block"]
        self.assertGreater(
            len(block_reds),
            0,
            "dirty_memory_text must contain block-severity secrets",
        )
        self.assertTrue(has_blocking(tuple(block_reds)))

    def test_block_present_in_mixed_list(self) -> None:
        from memory.models import Redaction

        reds = (
            Redaction(
                rule_id="jira-key",
                severity="warn",
                line_no=1,
                matched="[JIRA_KEY]",
                replacement="[JIRA_KEY]",
            ),
            Redaction(
                rule_id="aws-access-key",
                severity="block",
                line_no=2,
                matched="[REDACTED_AWS_KEY]",
                replacement="[REDACTED_AWS_KEY]",
            ),
        )
        self.assertTrue(has_blocking(reds))


class TestScrub(unittest.TestCase):
    """scrub() applies scrub-severity replacements and reports all severities."""

    def test_scrub_replaces_abs_home_path(self) -> None:
        text = "My home: /Users/alice/code/myproject/file.py"
        scrubbed, findings = scrub(text)
        self.assertNotIn("/Users/alice", scrubbed)
        self.assertIn("~/", scrubbed)
        self.assertTrue(any(r.rule_id == "abs-home-path" for r in findings))

    def test_scrub_does_not_replace_block_severity(self) -> None:
        """scrub() reports block findings but does NOT substitute them in the text."""
        # AWS key needs trailing newline for the (?:\s|$) lookahead
        text = "AKIA" + "0123456789ABCDEF\n"
        scrubbed, findings = scrub(text)
        block_findings = [r for r in findings if r.rule_id == "aws-access-key"]
        self.assertGreaterEqual(len(block_findings), 1)
        # Block-severity content is NOT removed from the text by scrub()
        self.assertIn("AKIA", scrubbed)

    def test_scrub_returns_tuple_of_redactions(self) -> None:
        scrubbed_text, findings = scrub("no secrets here")
        self.assertIsInstance(scrubbed_text, str)
        self.assertIsInstance(findings, tuple)

    def test_anonymize_false_skips_local_username_rule(self) -> None:
        """local-username rule (requires_anonymize=True) does NOT fire without anonymize."""
        text = "username: alice"
        redactions = scan(text, anonymize=False)
        username_reds = [r for r in redactions if r.rule_id == "local-username"]
        self.assertEqual(len(username_reds), 0)

    def test_anonymize_true_fires_local_username_rule(self) -> None:
        text = "username: alice"
        redactions = scan(text, anonymize=True)
        username_reds = [r for r in redactions if r.rule_id == "local-username"]
        self.assertGreaterEqual(len(username_reds), 1)

    def test_line_no_is_one_indexed(self) -> None:
        text = "first line\nsecond line with /Users/alice/path"
        _, findings = scrub(text)
        home_path = [r for r in findings if r.rule_id == "abs-home-path"]
        self.assertGreaterEqual(len(home_path), 1)
        self.assertEqual(home_path[0].line_no, 2)  # second line


if __name__ == "__main__":
    unittest.main()
