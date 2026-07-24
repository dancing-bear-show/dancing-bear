"""LineChartSpec — ChartSpec subtype with line-specific rendering options."""

from dataclasses import dataclass

from charts.types.base import ChartKind, ChartSpec


@dataclass(frozen=True)
class LineChartSpec(ChartSpec):
    kind: ChartKind = ChartKind.line
    line_width: float = 2.0
    # matplotlib marker string (e.g. "o"); None disables point markers.
    marker: str | None = None
    # Smooth via numpy linear interpolation on a dense x-grid (no scipy needed).
    smooth: bool = False
