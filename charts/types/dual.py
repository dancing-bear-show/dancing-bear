"""DualAxisChartSpec — ChartSpec subtype with two independent y-axes."""

from dataclasses import dataclass, field

from charts.types.base import ChartKind, ChartSpec


@dataclass(frozen=True)
class DualAxisChartSpec(ChartSpec):
    kind: ChartKind = ChartKind.dual
    # Explicit name lists take precedence over series.y_axis when non-empty.
    left_series_names: list[str] = field(default_factory=list)
    right_series_names: list[str] = field(default_factory=list)
