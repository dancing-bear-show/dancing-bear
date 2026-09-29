"""Pin one pricing table across the transcript and OTel analytics cost paths.

The transcript provider (``pricing.compute_cost``) and OTel analytics
(``analytics.cost``) once kept separate tables that drifted apart, so the same
model was priced differently depending on which command reported it.

Parity is asserted for the cost helpers only (``compute_cost`` vs the
``compute_raw_cost`` path behind ``_build_model_costs``); the legacy formulas in
``get_model_performance`` and prompt metrics are not covered.
"""

import unittest
from unittest.mock import MagicMock, patch

from telemetry.otel.analytics.cost import _build_model_costs
from telemetry.providers.transcript import TranscriptProvider

_TOKENS = {
    "input_tokens": 1_000_000,
    "output_tokens": 500_000,
    "cache_creation_tokens": 200_000,
    "cache_read_tokens": 3_000_000,
}

# Models that only one of the two former tables listed, with list prices.
_PREVIOUSLY_ONE_SIDED: dict[str, tuple[float, float]] = {
    "claude-opus-4-8": (5.0, 25.0),
    "claude-opus-4-1": (15.0, 75.0),
    "claude-opus-4-1-20250805": (15.0, 75.0),
    "claude-sonnet-4-8": (3.0, 15.0),
    "claude-sonnet-4-8-1m": (3.0, 15.0),
    "claude-haiku-4-5-20251001": (1.0, 5.0),
}


def _otel_cost(model: str) -> float:
    data = {model: {"api_calls": 1, **_TOKENS}}
    return _build_model_costs(data)[0].cost


@patch("telemetry.pricing._cost_multiplier", return_value=1.0)
def _transcript_cost(model: str, _mult: MagicMock) -> float:
    return TranscriptProvider._compute_token_cost(
        model,
        _TOKENS["input_tokens"],
        _TOKENS["output_tokens"],
        _TOKENS["cache_read_tokens"],
        _TOKENS["cache_creation_tokens"],
    )


def _expected_cost(in_rate: float, out_rate: float) -> float:
    return (
        _TOKENS["input_tokens"] * in_rate
        + _TOKENS["output_tokens"] * out_rate
        + _TOKENS["cache_creation_tokens"] * in_rate * 1.25
        + _TOKENS["cache_read_tokens"] * in_rate * 0.1
    ) / 1_000_000


class TestPricingParity(unittest.TestCase):
    def test_every_model_key_costs_the_same_on_both_paths(self):
        from telemetry.pricing import MODEL_PRICING

        for model in MODEL_PRICING:
            with self.subTest(model=model):
                self.assertAlmostEqual(_otel_cost(model), _transcript_cost(model), places=9)

    def test_previously_one_sided_models_price_at_list_on_both_paths(self):
        for model, (in_rate, out_rate) in _PREVIOUSLY_ONE_SIDED.items():
            expected = _expected_cost(in_rate, out_rate)
            with self.subTest(model=model, path="otel"):
                self.assertAlmostEqual(_otel_cost(model), expected, places=9)
            with self.subTest(model=model, path="transcript"):
                self.assertAlmostEqual(_transcript_cost(model), expected, places=9)

    def test_previously_one_sided_models_resolve_to_own_key(self):
        from telemetry.pricing import resolve_pricing_key

        for model in _PREVIOUSLY_ONE_SIDED:
            with self.subTest(model=model):
                self.assertEqual(resolve_pricing_key(model), model)

    def test_sonnet_1m_fallback_uses_newest_1m_key(self):
        from telemetry.pricing import resolve_pricing_key

        self.assertEqual(resolve_pricing_key("claude-sonnet-4-9[1m]"), "claude-sonnet-4-8-1m")


if __name__ == "__main__":
    unittest.main()
