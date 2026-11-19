"""Tests for core.token_shapes: every shape matches its format, rejects a near miss, runs linear.

Token literals are assembled by concatenation so push protection does not flag
this source.
"""

from __future__ import annotations

import time
import unittest

from core.token_shapes import TOKEN_SHAPES, contains_token_shape

# name -> (matching sample, nearby non-matching sample)
_SAMPLES: dict[str, tuple[str, str]] = {
    "aws-access-key": ("AKI" + "A" + "ABCDEFGHIJKLMNOP", "AKI" + "A" + "ABCDEFGHIJKLMNO"),
    "private-key-block": (
        "-----BEGIN RSA " + "PRIVATE KEY-----",
        "-----BEGIN " + "PUBLIC KEY-----",
    ),
    "github-token": ("gh" + "p_" + "a" * 36, "gh" + "p_" + "a" * 35),
    "anthropic-key": ("sk-" + "ant-api03-" + "x" * 40, "sk-" + "ant-api03-short"),
    "slack-token": (
        "xa" + "pp-1-A0123456789-1234567890123-abcdef",
        "xa" + "pp-config-" + "a" * 30,
    ),
    "openai-key": ("sk-" + "A1b2C3d4" * 6, "sk-" + "A1b2C3d4" * 6 + "x"),
    "google-api-key": ("AI" + "za" + "SyA1b2C3d4E5f6G7h8I9j0KlMnOpQrStUv", "AI" + "za" + "A" * 20),
    "google-oauth-token": ("ya" + "29." + "a0AfH6SMB" * 4, "ya29.short"),
    "jwt": ("ey" + "J" + "hbGciOiJ9.eyJzdWIiOiIx.c2lnbmF0dXJl", "ey" + "J.ey" + "J.abc"),
    "stripe-key": ("sk" + "_live_" + "a" * 30, "sk" + "_live_" + "short"),
    "npm-token": ("npm" + "_" + "A1b2C3d4E5" * 3 + "abcdef", "npm" + "_" + "A" * 35),
    "grafana-token": (
        "gl" + "sa_" + "A1b2C3d4" * 4 + "_" + "0a1b2c3d",
        "gl" + "sa_" + "A1b2C3d4" * 4 + "_" + "zzzzzzzz",
    ),
    "stripe-test-key": ("sk" + "_test_" + "a" * 30, "sk" + "_test_" + "short"),
    "msal-token": ("M." + "C5" + "x" * 30, "M.Sc."),
    "api-dash-token": ("api" + "-" + "ABCDEF1234567890", "api" + "-" + "ABC123"),
    "rootly-token": ("root" + "ly_" + "ABCDEFGHIJKLMNOP", "root" + "ly_" + "short"),
}

_HEURISTIC = {"stripe-test-key", "msal-token", "api-dash-token", "rootly-token"}

_BIG = 100_000
_WALL_SECS = 2.0


class TestCatalog(unittest.TestCase):
    def test_every_shape_has_samples(self) -> None:
        self.assertEqual({s.name for s in TOKEN_SHAPES}, set(_SAMPLES))

    def test_names_unique(self) -> None:
        names = [s.name for s in TOKEN_SHAPES]
        self.assertEqual(len(names), len(set(names)))

    def test_exact_flag(self) -> None:
        for shape in TOKEN_SHAPES:
            with self.subTest(name=shape.name):
                self.assertEqual(shape.exact, shape.name not in _HEURISTIC)

    def test_shape_matches_and_rejects(self) -> None:
        for shape in TOKEN_SHAPES:
            hit, miss = _SAMPLES[shape.name]
            with self.subTest(name=shape.name):
                self.assertIsNotNone(shape.pattern.search(hit))
                self.assertIsNone(shape.pattern.search(miss))


class TestContainsTokenShape(unittest.TestCase):
    def test_true_for_any_shape(self) -> None:
        for name, (hit, _) in _SAMPLES.items():
            with self.subTest(name=name):
                self.assertTrue(contains_token_shape("value: " + hit))

    def test_false_for_plain_text(self) -> None:
        for text in ("", "hello", "the M.Sc. thesis", "sk-proj prefix", "api-docs"):
            with self.subTest(text=text):
                self.assertFalse(contains_token_shape(text))


class TestLinearTime(unittest.TestCase):
    """A long run that ends in a non-match is scanned once, not once per offset."""

    def test_pathological_inputs(self) -> None:
        inputs = [
            "A" * _BIG + ".",
            "a1" * (_BIG // 2) + "!",
            "M." * (_BIG // 2) + "!",
            "M." + "!" * _BIG,
            "ya29." * (_BIG // 5),
            "sk-" + "a" * _BIG + "-",
            "api-" * (_BIG // 4),
            "gl" + "sa_" + "a" * _BIG,
            "x" + "ox" * _BIG,
        ]
        for shape in TOKEN_SHAPES:
            for i, text in enumerate(inputs):
                with self.subTest(name=shape.name, case=i):
                    start = time.monotonic()
                    list(shape.pattern.finditer(text))
                    self.assertLess(time.monotonic() - start, _WALL_SECS)


if __name__ == "__main__":
    unittest.main()
