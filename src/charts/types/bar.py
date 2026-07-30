"""BarChartSpec — ChartSpec subtype with bar-specific rendering options."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from charts.types.base import ChartKind, ChartSpec


@dataclass(frozen=True)
class BarChartSpec(ChartSpec):
    kind: ChartKind = ChartKind.bar
    orientation: Literal["vertical", "horizontal"] = "vertical"
    stacked: bool = False
    bar_width: float = 0.8
