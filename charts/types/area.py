"""AreaChartSpec — ChartSpec subtype for filled area charts."""

from dataclasses import dataclass

from charts.types.base import ChartKind, ChartSpec


@dataclass(frozen=True)
class AreaChartSpec(ChartSpec):
    kind: ChartKind = ChartKind.area
    # Fill transparency; 0 = opaque, 1 = invisible.
    alpha: float = 0.4
    stacked: bool = False
