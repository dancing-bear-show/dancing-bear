"""Tests for memory.redaction — block aborts, scrub round-trips, masked previews, severity classifications."""

from __future__ import annotations

import unittest

from memory.redaction import REDACTION_RULES, has_blocking, scan, scrub
from tests.memory_tests.fixtures import dirty_memory_text

# Samples for rules the shared dirty fixture does not cover; credentials are
# assembled by concatenation so secret scanners do not flag this source.
_EXTRA_RULE_SAMPLES = "\n".join(
    [
        "key: sk-" + "ant-api03-" + "x" * 40,  # anthropic-key
        "slug: -home-alice-code-myproject",  # abs-home-path-slug-form-linux
        "k: sk-" + "proj-" + "A1b2C3d4" * 6,  # openai-key
        "k: AI" + "za" + "SyA1b2C3d4E5f6G7h8I9j0KlMnOpQrStUv",  # google-api-key
        "t: ey" + "J" + "hbGciOiJIUzI1NiJ9.ey" + "J" + "zdWIiOiIx.c2ln_nat-ure1",  # jwt
        "k: sk" + "_live_" + "51H" + "a" * 30,  # stripe-key
        "t: npm" + "_" + "A1b2C3d4E5" * 3 + "abcdef",  # npm-token
        "u: https://admin:" + "hunter2pass" + "@db.example.com/x",  # url-credentials
        "aws_secret_access_key = " + "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",  # aws-secret-key
        "t: ya" + "29." + "a0AfH6SMB" * 4,  # google-oauth-token
        "t: gl" + "sa_" + "A1b2C3d4" * 4 + "_" + "0a1b2c3d",  # grafana-token
        "t: M." + "C5" + "x" * 30,  # msal-token
        "t: api" + "-" + "ABCDEF1234567890",  # api-dash-token
        "t: root" + "ly_" + "ABCDEFGHIJKLMNOP",  # rootly-token
    ]
)


class TestEveryRuleFires(unittest.TestCase):
    """Each rule in REDACTION_RULES fires on the dirty fixture."""

    def test_every_rule_fires(self) -> None:
        text = dirty_memory_text() + "\n" + _EXTRA_RULE_SAMPLES
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
        self.assertGreaterEqual(
            len(cred_hits), 1, "credential-assignment should fire on password= assignment"
        )
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


def _ids(text: str) -> set[str]:
    return {r.rule_id for r in scan(text)}


class TestHardenedBlockRules(unittest.TestCase):
    """Credential shapes previously missed must block; near-misses must not."""

    def test_positive_shapes_block(self) -> None:
        aws = "AKI" + "A" + "ABCDEFGHIJKLMNOP"
        asia = "ASI" + "A" + "ABCDEFGHIJKLMNOP"
        pat = "github" + "_pat_" + "A" * 82
        ant = "sk-" + "ant-api03-" + "x" * 40
        admin = "sk-" + "ant-admin01-" + "Ab_-" * 10
        begin = "-----BEGIN "
        end = " PRIVATE KEY-----"
        cases = [
            ("aws-access-key", "AWS_ACCESS_KEY_ID=" + aws),
            ("aws-access-key", '"' + aws + '"'),
            ("aws-access-key", "x: " + asia + ","),
            ("aws-access-key", aws),
            ("private-key-block", begin + "OPENSSH" + end),
            ("private-key-block", begin + "EC" + end),
            ("private-key-block", begin + "DSA" + end),
            ("private-key-block", begin + "ENCRYPTED" + end),
            ("private-key-block", begin + "RSA" + end),
            ("private-key-block", begin + "PRIVATE KEY-----"),
            ("github-token", "token=" + pat),
            ("github-token", "github" + "_pat_" + "a" * 22),
            ("anthropic-key", "ANTHROPIC_API_KEY=" + ant),
            ("anthropic-key", '"' + admin + '"'),
            ("slack-token", "xo" + "xb-" + "1" * 12 + "-" + "2" * 13 + "-" + "aB3" * 8),
            ("slack-token", "xo" + "xp-" + "1" * 12 + "-" + "2" * 12 + "-" + "c" * 24),
            ("slack-token", "xo" + "xs-" + "x" * 30),
        ]
        for rule_id, text in cases:
            with self.subTest(rule_id=rule_id, text=text[:30]):
                reds = scan(text)
                self.assertIn(rule_id, {r.rule_id for r in reds})
                self.assertTrue(has_blocking(reds))

    def test_negative_shapes_do_not_match(self) -> None:
        cases = [
            ("aws-access-key", "AKI" + "A" + "ABCDEFGHIJKLMNO"),  # 15 chars
            ("aws-access-key", "X" + "AKI" + "A" + "ABCDEFGHIJKLMNOP"),
            ("aws-access-key", "AKI" + "A" + "ABCDEFGHIJKLMNOP" + "Q"),
            ("private-key-block", "-----BEGIN " + "PUBLIC KEY-----"),
            ("private-key-block", "-----BEGIN " + "CERTIFICATE-----"),
            ("github-token", "github" + "_pat_" + "A" * 10),
            ("github-token", "github" + "_pat"),
            ("anthropic-key", "sk-" + "ant"),
            ("anthropic-key", "sk-" + "ant-api03-short"),
            ("anthropic-key", "ask-" + "ant-api03-" + "x" * 40),
            ("slack-token", "xo" + "xb-"),
            ("slack-token", "xo" + "xb-short"),
            ("slack-token", "xo" + "xz-" + "a" * 40),
        ]
        for rule_id, text in cases:
            with self.subTest(rule_id=rule_id, text=text[:30]):
                self.assertNotIn(rule_id, _ids(text))


def _credential_shape_samples() -> list[tuple[str, str]]:
    """(rule_id, text) pairs, assembled by concatenation for push protection."""
    return [
        ("openai-key", "key sk-" + "proj-" + "A1b2C3d4" * 6),
        ("openai-key", "OPENAI_API_KEY=sk-" + "proj-" + "A1b2_C3-d4" * 6),
        ("google-api-key", "AI" + "za" + "SyA1b2C3d4E5f6G7h8I9j0KlMnOpQrStUv"),
        ("google-api-key", "key=AI" + "za" + "SyA1b2C3d4E5f6G7h8I9j0KlMnOpQrStUv&x=1"),
        (
            "jwt",
            "ey"
            + "J"
            + "hbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U",
        ),
        (
            "jwt",
            "Authorization: ey" + "J" + "hbGciOiJIUzI1NiJ9.ey" + "J" + "zdWIiOiIx.c2ln_nat-ure1",
        ),
        ("stripe-key", "sk" + "_live_" + "51H" + "a" * 30),
        ("stripe-key", "rk" + "_live_" + "51H" + "b" * 30),
        ("npm-token", "npm" + "_" + "A1b2C3d4E5" * 3 + "abcdef"),
        ("url-credentials", "https://admin:" + "hunter2pass" + "@db.example.com/x"),
        ("url-credentials", "postgres://u:p" + "@host:5432/db"),
        ("aws-secret-key", "aws_secret_access_key = " + "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"),
        (
            "aws-secret-key",
            'AWS_SECRET_ACCESS_KEY="' + "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY" + '"',
        ),
    ]


class TestCredentialShapeRules(unittest.TestCase):
    """Credential shapes the first rule set missed must block; near-misses must not."""

    def test_positive_shapes_block(self) -> None:
        for rule_id, text in _credential_shape_samples():
            with self.subTest(rule_id=rule_id, text=text[:30]):
                reds = scan(text)
                self.assertIn(rule_id, {r.rule_id for r in reds})
                self.assertTrue(has_blocking(reds))

    def test_negative_shapes_do_not_match(self) -> None:
        cases = [
            ("openai-key", "the sk-" + "proj prefix"),
            ("openai-key", "sk-" + "proj-short"),
            ("openai-key", "task-" + "proj-" + "A1b2C3d4" * 6),
            ("google-api-key", "AI" + "za" + "Sy123"),
            ("google-api-key", "AI" + "za"),
            ("google-api-key", "AI" + "za" + "A" * 20),
            ("jwt", "a.b.c"),
            ("jwt", "v1.2.3"),
            ("jwt", "ey" + "J" + "hbGciOi.short"),
            ("jwt", "file.tar.gz"),
            ("stripe-key", "sk" + "_live_" + "short"),
            ("stripe-key", "sk" + "_test_" + "a" * 30),
            ("npm-token", "npm" + "_" + "A" * 35),
            ("npm-token", "npm" + "_" + "A" * 37),
            ("npm-token", "install npm_config"),
            ("url-credentials", "http://host/path"),
            ("url-credentials", "http://host:8080/path"),
            ("url-credentials", "https://github.com/a/b@c"),
            ("url-credentials", "mailto:a@b.example"),
            ("aws-secret-key", "aws_secret_access_key = short"),
            ("aws-secret-key", "aws_secret_access_key"),
        ]
        for rule_id, text in cases:
            with self.subTest(rule_id=rule_id, text=text[:30]):
                self.assertNotIn(rule_id, _ids(text))


def _gap_samples() -> list[tuple[str, str, str]]:
    """(rule_id, missed shape, nearby benign string), assembled for push protection."""
    aws_value_40 = "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"
    return [
        ("openai-key", "OPENAI_API_KEY=sk-" + "A1b2C3d4" * 6, "sk-" + "A1b2C3d4" * 6 + "x"),
        ("url-credentials", "redis://:" + "hunter2secret" + "@host:6379", "redis://host:6379/0"),
        (
            "aws-secret-key",
            '"aws_secret_access_key": "' + aws_value_40 + '"',
            '"aws_secret_access_key": "<your-secret-here>"',
        ),
        (
            "aws-secret-key",
            "aws_secret_access_key: '" + aws_value_40 + "'",
            "aws_secret_access_key: TBD",
        ),
        ("bearer-token", "Authorization: Bearer abcdef123456,", "send a Bearer token, then retry"),
        (
            "slack-token",
            "xa" + "pp-1-A0123456789-1234567890123-" + "ab12" * 10,
            "set xapp-config in the manifest",
        ),
        ("google-oauth-token", "ya" + "29." + "a0AfH6SMB" * 4, "ya29.short"),
        (
            "grafana-token",
            "gl" + "sa_" + "A1b2C3d4" * 4 + "_" + "0a1b2c3d",
            "gl" + "sa_" + "A1b2C3d4",
        ),
    ]


class TestPreviouslyMissedShapesBlock(unittest.TestCase):
    """Shapes the rules used to miss must block; the nearby benign string must not."""

    def test_missed_shape_blocks(self) -> None:
        for rule_id, text, _ in _gap_samples():
            with self.subTest(rule_id=rule_id, text=text[:30]):
                reds = scan(text)
                self.assertIn(rule_id, {r.rule_id for r in reds})
                self.assertTrue(has_blocking(reds))

    def test_nearby_benign_string_does_not_match(self) -> None:
        for rule_id, _, benign in _gap_samples():
            with self.subTest(rule_id=rule_id, text=benign[:30]):
                self.assertNotIn(rule_id, _ids(benign))


class TestCredentialAssignmentWarns(unittest.TestCase):
    """key: value and token= forms warn (never block); colon prose does not match."""

    def test_assignment_forms_warn(self) -> None:
        for text in (
            "password: hunter2secret",
            "token = abc123def",
            'secret: "s3cr3t-value"',
            "db:\n  passwd: p4ssw0rd\n",
        ):
            with self.subTest(text=text):
                reds = [r for r in scan(text) if r.rule_id == "credential-assignment"]
                self.assertTrue(reds)
                self.assertEqual({r.severity for r in reds}, {"warn"})

    def test_colon_prose_does_not_match(self) -> None:
        for text in (
            "password: see vault",
            "password: see the vault for details",
            "secret: classified",
            "token_count: 123456",
            "token: 4096",
        ):
            with self.subTest(text=text):
                self.assertNotIn("credential-assignment", _ids(text))


class TestHeuristicShapesWarn(unittest.TestCase):
    """Heuristic catalog shapes are reported as warn, so they never block export."""

    def test_heuristic_shapes_warn_only(self) -> None:
        for rule_id, text in (
            ("msal-token", "M." + "C5" + "x" * 30),
            ("api-dash-token", "api" + "-" + "ABCDEF1234567890"),
            ("rootly-token", "root" + "ly_" + "ABCDEFGHIJKLMNOP"),
            ("stripe-test-key", "sk" + "_test_" + "a" * 30),
        ):
            with self.subTest(rule_id=rule_id):
                reds = scan(text)
                self.assertIn(rule_id, {r.rule_id for r in reds})
                self.assertFalse(has_blocking(reds))


class TestScanLineNumbers(unittest.TestCase):
    """Line numbers stay right for repeated matches of one rule."""

    def test_each_match_gets_its_own_line(self) -> None:
        text = "INC-1\nnothing\nINC-2\n\nINC-3"
        lines = [r.line_no for r in scan(text) if r.rule_id == "incident-id"]
        self.assertEqual(lines, [1, 3, 5])


class TestHomePathHardening(unittest.TestCase):
    """/home and -home- forms scrub with their own replacements."""

    def test_home_path_scrubbed_to_tilde(self) -> None:
        out, reds = scrub("at /home/alice/code/x")
        self.assertEqual(out, "at ~/code/x")
        self.assertIn("abs-home-path", {r.rule_id for r in reds})

    def test_home_slug_scrubbed_without_users_form(self) -> None:
        out, reds = scrub("slug: -home-alice-code-x")
        self.assertEqual(out, "slug: -home-<home>-x")  # greedy name, as for -Users-
        self.assertNotIn("Users", out)
        self.assertIn("abs-home-path-slug-form-linux", {r.rule_id for r in reds})

    def test_users_forms_unchanged(self) -> None:
        self.assertEqual(scrub("/Users/bob/x")[0], "~/x")
        self.assertEqual(scrub("-Users-bob-x")[0], "-Users-<home>-x")

    def test_negative_home_shapes(self) -> None:
        for text in ("/home", "/home/", "go /home now", "my-home-page-header", "a/home/"):
            with self.subTest(text=text):
                reds = _ids(text)
                self.assertNotIn("abs-home-path", reds)
                self.assertNotIn("abs-home-path-slug-form-linux", reds)
