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


def _build_strings(
    tokens: list[str], n: int = 5000, seed: int | None = None
) -> list[str]:
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
        tokens = ["-----BEGIN", " ", "RSA", "PRIVATE", "KEY", "-----", "\n", "x", "\t"]
        assert_same_matches(old, _private_key_rule(), tokens, seed=4)

    def test_private_key_pattern_pathological_is_linear(self) -> None:
        text = "-----BEGIN " + "PRIVATE KEY" + " " * BIG
        assert_fast(lambda: _private_key_rule().search(text))
        self.assertIsNotNone(
            _private_key_rule().search("-----BEGIN RSA " + "PRIVATE KEY-----")
        )
