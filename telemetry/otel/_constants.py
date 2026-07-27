"""Lightweight OTel metric-name constants with no analytics dependencies.

Import from here (not ``analytics.cost``) when only the metric name string is
needed — e.g. from menubar_provider.py, which runs frequently and should not
pay the import cost of the pricing table and analytics stack just to compare
a metric name.
"""

from __future__ import annotations

# Name of the OTel metric emitted directly by the Claude Code CLI with
# Anthropic's real, authoritative cost computation for each API call (as
# opposed to ``claude_code.token.usage``, which carries only token counts that
# analytics.cost recomputes cost from using MODEL_PRICING — a fragile
# approximation that has been observed to diverge meaningfully from actual
# billed spend).
METRIC_COST_USAGE = "claude_code.cost.usage"
