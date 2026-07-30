"""Load and validate YAML grid config files for multi-panel chart layouts."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from charts.theme import get_theme

_REQUIRED_TOP_LEVEL = ("title", "output", "rows", "cols", "charts")


@dataclass(frozen=True)
class PanelConfig:
    input: str
    row: int
    col: int


@dataclass(frozen=True)
class GridConfig:
    title: str
    output: str
    rows: int
    cols: int
    panels: list[PanelConfig]
    width_px: int = 1600
    height_px: int = 900
    theme: str = "dark"
    dpi: int = 150


def load_grid_config(path: str) -> GridConfig:
    """Load and validate a YAML grid config.

    Raises ValueError on missing required keys or out-of-bounds row/col.
    """
    try:
        import yaml  # noqa: PLC0415
        raw = yaml.safe_load(Path(path).read_text())
    except ImportError:
        import json
        raw = json.loads(Path(path).read_text())

    if not isinstance(raw, dict):
        raise ValueError(f"Grid config must be a YAML mapping, got {type(raw).__name__}")

    for key in _REQUIRED_TOP_LEVEL:
        if key not in raw:
            raise ValueError(f"Grid config missing required field {key!r}")

    raw_charts = raw["charts"]
    if not isinstance(raw_charts, list):
        raise ValueError("'charts' must be a list")

    panels: list[PanelConfig] = []
    for idx, panel_raw in enumerate(raw_charts):
        if not isinstance(panel_raw, dict):
            raise ValueError(f"charts[{idx}]: must be a mapping")
        for req in ("input", "row", "col"):
            if req not in panel_raw:
                raise ValueError(f"charts[{idx}]: missing required field {req!r}")
        panels.append(
            PanelConfig(
                input=str(panel_raw["input"]),
                row=int(panel_raw["row"]),
                col=int(panel_raw["col"]),
            )
        )

    raw_theme = raw.get("theme", "dark")
    theme_name = "dark" if raw_theme is None else str(raw_theme)
    get_theme(theme_name)  # validate eagerly

    cfg = GridConfig(
        title=str(raw["title"]),
        output=str(raw["output"]),
        rows=int(raw["rows"]),
        cols=int(raw["cols"]),
        panels=panels,
        width_px=int(raw.get("width_px", 1600)),
        height_px=int(raw.get("height_px", 900)),
        theme=theme_name,
        dpi=int(raw.get("dpi", 150)),
    )
    _validate_grid(cfg)
    return cfg


def _validate_panel_placement(idx: int, panel: PanelConfig, rows: int, cols: int) -> None:
    if panel.row < 0 or panel.col < 0:
        raise ValueError(
            f"charts[{idx}]: row/col must be non-negative, got row={panel.row} col={panel.col}"
        )
    if panel.row >= rows:
        raise ValueError(
            f"charts[{idx}]: row {panel.row} is out of bounds for grid with {rows} row(s)"
        )
    if panel.col >= cols:
        raise ValueError(
            f"charts[{idx}]: col {panel.col} is out of bounds for grid with {cols} col(s)"
        )


def _validate_grid(cfg: GridConfig) -> None:
    if cfg.rows <= 0 or cfg.cols <= 0:
        raise ValueError(
            f"GridConfig rows/cols must be positive, got rows={cfg.rows} cols={cfg.cols}"
        )
    if cfg.dpi <= 0:
        raise ValueError(f"dpi must be positive, got {cfg.dpi}")
    if cfg.width_px <= 0:
        raise ValueError(f"width_px must be positive, got {cfg.width_px}")
    if cfg.height_px <= 0:
        raise ValueError(f"height_px must be positive, got {cfg.height_px}")
    for idx, panel in enumerate(cfg.panels):
        _validate_panel_placement(idx, panel, cfg.rows, cfg.cols)
