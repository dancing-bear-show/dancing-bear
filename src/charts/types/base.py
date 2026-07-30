"""Core frozen dataclasses shared by all chart types."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ChartKind(str, Enum):
    line = "line"
    bar = "bar"
    area = "area"
    dual = "dual"


@dataclass(frozen=True)
class SeriesSpec:
    name: str
    # Raw rows from JSON; each row must have the parent ChartSpec's x_field + "value".
    data: list[dict[str, object]]
    color: str | None = None
    label: str | None = None
    # Which y-axis to bind to; only meaningful for DualAxisChartSpec.
    y_axis: str = "left"


@dataclass(frozen=True)
class ChartSpec:
    title: str
    x_field: str
    series: list[SeriesSpec]
    kind: ChartKind = ChartKind.line
    width_px: int = 1200
    height_px: int = 400
    dpi: int = 150
    x_label: str | None = None
    y_label: str | None = None
    y_right_label: str | None = None
    show_legend: bool = True
    date_format: str | None = None
    shade_weekends: bool = False

    def __post_init__(self) -> None:
        if not self.title:
            raise ValueError("ChartSpec.title must not be empty")
        if not self.x_field:
            raise ValueError("ChartSpec.x_field must not be empty")
        if not self.series:
            raise ValueError("ChartSpec requires at least one series")
