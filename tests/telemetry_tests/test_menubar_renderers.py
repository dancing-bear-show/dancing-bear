"""Tests for telemetry/_menubar_renderers.py — icon rendering helpers."""
from __future__ import annotations

import unittest

from telemetry._menubar_renderers import (
    _icon_substitutions,
    _icon_token_stream,
    _render_icon_plain,
)


def _make_icon_ctx(
    h1_cost: float = 0.5,
    d1_cost: float = 2.0,
    h1_input: int = 1000,
    h1_output: int = 500,
) -> dict[str, dict]:
    return {
        "1h": {"cost": h1_cost, "input_tokens": h1_input, "output_tokens": h1_output},
        "1d": {"cost": d1_cost, "input_tokens": 0, "output_tokens": 0},
    }


class TestIconSubstitutions(unittest.TestCase):
    def test_score_included(self) -> None:
        ctx = _make_icon_ctx()
        subs = _icon_substitutions(ctx, mtd_cost=10.0, score=5)
        self.assertEqual(subs["score"], "5")

    def test_1h_spend_formatted(self) -> None:
        ctx = _make_icon_ctx(h1_cost=1.23)
        subs = _icon_substitutions(ctx, mtd_cost=0.0, score=1)
        self.assertEqual(subs["1h_spend"], "$1.23")

    def test_1d_spend_formatted(self) -> None:
        ctx = _make_icon_ctx(d1_cost=4.56)
        subs = _icon_substitutions(ctx, mtd_cost=0.0, score=1)
        self.assertEqual(subs["1d_spend"], "$4.56")

    def test_mtd_spend_formatted(self) -> None:
        ctx = _make_icon_ctx()
        subs = _icon_substitutions(ctx, mtd_cost=99.0, score=1)
        self.assertEqual(subs["mtd_spend"], "$99.00")

    def test_otel_1d_included(self) -> None:
        ctx = _make_icon_ctx()
        subs = _icon_substitutions(ctx, mtd_cost=0.0, score=1, otel_cost_1d=3.75)
        self.assertEqual(subs["otel_1d"], "$3.75")

    def test_missing_1h_window_uses_zero(self) -> None:
        subs = _icon_substitutions({}, mtd_cost=0.0, score=1)
        self.assertEqual(subs["1h_spend"], "$0.00")

    def test_tokens_1h_computed_from_input_plus_output(self) -> None:
        from telemetry.tui import format_tokens
        ctx = {"1h": {"cost": 0.0, "input_tokens": 2000, "output_tokens": 500}}
        subs = _icon_substitutions(ctx, mtd_cost=0.0, score=1)
        # 2000 + 500 = 2500 tokens — format_tokens condenses to e.g. "2K"
        expected = format_tokens(2500)
        self.assertEqual(subs["tokens_1h"], expected)


class TestRenderIconPlain(unittest.TestCase):
    def test_simple_score_template(self) -> None:
        result = _render_icon_plain("$score", {}, mtd_cost=0.0, score=7)
        self.assertEqual(result, "7")

    def test_1d_spend_template(self) -> None:
        ctx = _make_icon_ctx(d1_cost=5.0)
        result = _render_icon_plain("$1d_spend", ctx, mtd_cost=0.0, score=1)
        self.assertEqual(result, "$5.00")

    def test_combined_template(self) -> None:
        ctx = _make_icon_ctx(h1_cost=1.0)
        result = _render_icon_plain("$score/$1h_spend", ctx, mtd_cost=0.0, score=3)
        self.assertEqual(result, "3/$1.00")

    def test_unknown_var_passes_through(self) -> None:
        result = _render_icon_plain("$unknown_var", {}, mtd_cost=0.0, score=1)
        # safe_substitute leaves unknown vars literally
        self.assertIn("unknown_var", result)

    def test_literal_text_preserved(self) -> None:
        result = _render_icon_plain("Score: $score!", {}, mtd_cost=0.0, score=4)
        self.assertEqual(result, "Score: 4!")


class TestIconTokenStream(unittest.TestCase):
    def test_literal_only(self) -> None:
        tokens = _icon_token_stream("hello")
        self.assertEqual(tokens, [("lit", "hello")])

    def test_single_named_var(self) -> None:
        tokens = _icon_token_stream("$score")
        self.assertIn(("var", "score"), tokens)

    def test_braced_var(self) -> None:
        tokens = _icon_token_stream("${1d_spend}")
        self.assertIn(("braced", "1d_spend"), tokens)

    def test_mixed_literal_and_var(self) -> None:
        tokens = _icon_token_stream("Cost: $1d_spend!")
        kinds = [k for k, _ in tokens]
        self.assertIn("lit", kinds)
        self.assertIn("var", kinds)

    def test_escaped_dollar(self) -> None:
        tokens = _icon_token_stream("$$")
        self.assertIn(("lit", "$"), tokens)

    def test_empty_template(self) -> None:
        tokens = _icon_token_stream("")
        self.assertEqual(tokens, [])

    def test_multiple_vars(self) -> None:
        tokens = _icon_token_stream("$score $mtd_spend")
        var_names = [t for k, t in tokens if k in ("var", "braced")]
        self.assertIn("score", var_names)
        self.assertIn("mtd_spend", var_names)

    def test_trailing_literal_after_var(self) -> None:
        # Template: "$score!" — var followed by literal "!"
        tokens = _icon_token_stream("$score!")
        # Should include a trailing literal
        lit_parts = [t for k, t in tokens if k == "lit"]
        self.assertIn("!", lit_parts)

    def test_var_in_middle_with_trailing_text(self) -> None:
        tokens = _icon_token_stream("$1d_spend USD")
        # The " USD" part after the var should be a trailing literal
        lit_parts = [t for k, t in tokens if k == "lit"]
        self.assertTrue(any("USD" in lt for lt in lit_parts))

    def test_invalid_dollar_token_emits_literal(self) -> None:
        # An invalid substitution like "$@" triggers the "invalid" group
        # and is emitted as-is (as a literal). This covers line 44.
        tokens = _icon_token_stream("$@")
        # Should produce at least one literal token
        lit_parts = [t for k, t in tokens if k == "lit"]
        self.assertGreater(len(lit_parts), 0)
        # The literal should contain the dollar sign (the matched group)
        combined = "".join(lit_parts)
        self.assertIn("$", combined)


if __name__ == "__main__":
    unittest.main()
