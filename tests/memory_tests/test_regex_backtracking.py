"""Linear-time regression tests for regexes in this domain.

Each rewrite is compared against its pre-rewrite pattern on seeded random input
and run on a pathological input under a generous wall bound.
"""

from __future__ import annotations

import random
import re
import time
import unittest

from memory.redaction import REDACTION_RULES

# ---------------------------------------------------------------------------
# Inline test helpers (equivalent to tests.helpers.regex_backtracking)
# ---------------------------------------------------------------------------

BIG = 100_000
_WALL_SECS = 2.0


def _build_strings(tokens: list[str], n: int = 5000, seed: int | None = None) -> list[str]:
    rng = random.Random(seed)  # nosec B311 - test-data generator, not security
    return ["".join(rng.choices(tokens, k=rng.randint(1, 20))) for _ in range(n)]


def assert_fast(fn, wall_secs: float = _WALL_SECS) -> None:
    start = time.monotonic()
    fn()
    elapsed = time.monotonic() - start
    if elapsed >= wall_secs:
        raise AssertionError(
            f"Expected completion in {wall_secs}s, took {elapsed:.3f}s — possible backtracking"
        )


def assert_same_matches(
    old_pat: str | re.Pattern,
    new_pat: str | re.Pattern,
    tokens: list[str],
    seed: int | None = None,
) -> None:
    old = re.compile(old_pat) if isinstance(old_pat, str) else old_pat
    new = re.compile(new_pat) if isinstance(new_pat, str) else new_pat
    for s in _build_strings(tokens, seed=seed):
        old_hit = old.search(s) is not None
        new_hit = new.search(s) is not None
        if old_hit != new_hit:
            raise AssertionError(f"Match divergence on {s!r}: old={old_hit}, new={new_hit}")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _private_key_rule() -> re.Pattern[str]:
    (rule,) = [r for r in REDACTION_RULES if r.rule_id == "private-key-block"]
    return rule.pattern


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestPrivateKeyRegex(unittest.TestCase):
    def test_private_key_pattern_equivalent(self) -> None:
        old = r"-----BEGIN\s+(?:RSA\s+)?PRIVATE\s+KEY(?:\s+.*)?-----"
        # No "\n" token: the hardened pattern deliberately limits header
        # whitespace to space/tab; a newline inside a PEM header is not valid.
        tokens = ["-----BEGIN", " ", "RSA", "PRIVATE", "KEY", "-----", "x", "\t"]
        assert_same_matches(old, _private_key_rule(), tokens, seed=4)

    def test_private_key_pattern_pathological_is_linear(self) -> None:
        text = "-----BEGIN " + "PRIVATE KEY" + " " * BIG
        assert_fast(lambda: _private_key_rule().search(text))
        self.assertIsNotNone(_private_key_rule().search("-----BEGIN RSA " + "PRIVATE KEY-----"))


class TestSlackTokenRegex(unittest.TestCase):
    @staticmethod
    def _pattern() -> re.Pattern[str]:
        (rule,) = [r for r in REDACTION_RULES if r.rule_id == "slack-token"]
        return rule.pattern

    def test_slack_token_pathological_is_linear(self) -> None:
        for text in ("xo" + "xb" * BIG, ("xo" + "xb-!") * (BIG // 4), "xo" + "xb-" + "-" * BIG):
            assert_fast(lambda t=text: self._pattern().search(t))

    def test_realistic_length_token_matches(self) -> None:
        token = "xo" + "xb-" + "1" * 12 + "-" + "2" * 13 + "-" + "aB3" * 8
        self.assertIsNotNone(self._pattern().search(token))


_NEW_RULE_IDS = (
    "openai-key",
    "google-api-key",
    "jwt",
    "stripe-key",
    "npm-token",
    "url-credentials",
    "aws-secret-key",
)


def _rule_pattern(rule_id: str) -> re.Pattern[str]:
    (rule,) = [r for r in REDACTION_RULES if r.rule_id == rule_id]
    return rule.pattern


def _pathological_inputs() -> list[str]:
    ejwt = "ey" + "J"
    return [
        "sk-" + "proj-" + "A" * BIG,
        ("sk-" + "proj-") * (BIG // 8),
        "AI" + "za" + "A" * BIG,
        ("AI" + "za") * (BIG // 4),
        ejwt * (BIG // 3),
        (ejwt + "aaaaaaaaaa.") * (BIG // 14),
        ejwt + "a" * BIG + "." + "a" * BIG,
        "sk" + "_live_" + "a" * BIG,
        ("sk" + "_live_") * (BIG // 8),
        "npm" + "_" + "a" * BIG,
        ("npm" + "_") * (BIG // 4),
        "x://" + "u" * BIG,
        "x://u:" + "p" * BIG,
        "x://u:" * (BIG // 6),
        "a://" * (BIG // 4),
        ("x://u:" + "p" * 50) * (BIG // 56),
        "aws_secret_access_key" + " " * BIG,
        "aws_secret_access_key=" + "a" * BIG,
        "aws_secret_access_key=" * (BIG // 22),
    ]


class TestNewCredentialRulesAreLinear(unittest.TestCase):
    def test_pathological_inputs_are_linear(self) -> None:
        for rule_id in _NEW_RULE_IDS:
            pattern = _rule_pattern(rule_id)
            for i, text in enumerate(_pathological_inputs()):
                with self.subTest(rule_id=rule_id, case=i):
                    assert_fast(lambda t=text, p=pattern: p.search(t))

    def test_new_rules_registered_as_block(self) -> None:
        for rule_id in _NEW_RULE_IDS:
            severities = [r.severity for r in REDACTION_RULES if r.rule_id == rule_id]
            self.assertEqual(severities, ["block"], rule_id)
