"""Normalize raw JSON input into ChartSpec instances.

This is the only module that understands the JSON data contract.
The renderer and chart types are JSON-unaware.
"""

from __future__ import annotations

from charts.types.area import AreaChartSpec
from charts.types.bar import BarChartSpec
from charts.types.base import ChartKind, ChartSpec, SeriesSpec
from charts.types.dual import DualAxisChartSpec
from charts.types.line import LineChartSpec

_KIND_TO_SPEC: dict[ChartKind, type[ChartSpec]] = {
    ChartKind.line: LineChartSpec,
    ChartKind.bar: BarChartSpec,
    ChartKind.area: AreaChartSpec,
    ChartKind.dual: DualAxisChartSpec,
}


def json_to_spec(raw: object) -> ChartSpec:
    """Parse the data-contract dict into a ChartSpec.

    Raises ValueError with a precise field path on any schema violation.

    Takes ``object`` rather than ``dict``: callers pass the result of
    ``json.loads`` on user-supplied files (see ``charts.cli``), which is any
    JSON value, so a list or string genuinely reaches this function and is
    rejected by the isinstance guard below. Annotating the narrower ``dict``
    described the happy path rather than the contract, and made the guard --
    plus the test covering it -- look like dead code to type-aware linters.

    The guard narrows ``object`` to ``dict[Any, Any]`` rather than to
    ``dict[str, object]``. ``dict[Any, Any]`` is the problem: it returns ``Any``
    from every ``.get()``, and that ``Any`` spreads into the helpers below.
    ``spec`` re-binds the value as ``dict[str, object]`` so the body stays
    checked.

    That re-bind is an assertion, not a proof: because the narrowed type
    carries ``Any`` parameters, mypy checks only that the value is a ``dict``
    and accepts any key/value types (a deliberately wrong ``dict[int, float]``
    passes silently; ``list[str]`` is still rejected). The runtime guarantee
    comes from the per-field validation below, not from this line.
    """
    if not isinstance(raw, dict):
        raise ValueError(f"chart spec must be a JSON object, got {type(raw).__name__}")
    spec: dict[str, object] = raw
    title = spec.get("title")
    if not title:
        raise ValueError("missing required field 'title'")

    x_field = spec.get("x_field")
    if not x_field:
        raise ValueError("missing required field 'x_field'")

    raw_series = spec.get("series")
    if not raw_series:
        raise ValueError("missing required field 'series' (must be a non-empty list)")
    if not isinstance(raw_series, list):
        raise ValueError("'series' must be a list")

    kind = _detect_kind(spec)
    series = _coerce_series(raw_series, str(x_field))

    spec_cls = _KIND_TO_SPEC.get(kind, LineChartSpec)

    kwargs: dict[str, object] = {
        "title": str(title),
        "x_field": str(x_field),
        "series": series,
        "kind": kind,
    }

    _apply_optional_fields(spec, kwargs)
    _apply_bar_fields(spec, kwargs, kind)
    _apply_area_fields(spec, kwargs, kind)

    return spec_cls(**kwargs)  # type: ignore[arg-type]


_SERIES_NAME_FIELDS = ("left_series_names", "right_series_names")


def _validate_string_list_field(
    raw: dict[str, object], key: str, kwargs: dict[str, object]
) -> None:
    if key not in raw:
        return
    v = raw[key]
    if not isinstance(v, list) or not all(isinstance(item, str) for item in v):
        raise ValueError(f"'{key}' must be a list of strings, got {v!r}")
    kwargs[key] = v


def _apply_optional_fields(raw: dict[str, object], kwargs: dict[str, object]) -> None:
    for optional in (
        "width_px",
        "height_px",
        "dpi",
        "x_label",
        "y_label",
        "y_right_label",
        "show_legend",
        "date_format",
    ):
        if optional in raw:
            kwargs[optional] = raw[optional]
    for series_field in _SERIES_NAME_FIELDS:
        _validate_string_list_field(raw, series_field, kwargs)


def _validate_bool_field(
    raw: dict[str, object], key: str, kwargs: dict[str, object]
) -> None:
    if key not in raw:
        return
    v = raw[key]
    if not isinstance(v, bool):
        raise ValueError(f"'{key}' must be a bool, got {v!r}")
    kwargs[key] = v


def _apply_bar_fields(
    raw: dict[str, object], kwargs: dict[str, object], kind: ChartKind
) -> None:
    if kind != ChartKind.bar:
        return
    _validate_bool_field(raw, "stacked", kwargs)
    if "orientation" in raw:
        v = raw["orientation"]
        if v not in ("vertical", "horizontal"):
            raise ValueError(
                f"'orientation' must be 'vertical' or 'horizontal', got {v!r}"
            )
        kwargs["orientation"] = v
    if "bar_width" in raw:
        v = raw["bar_width"]
        if isinstance(v, bool) or not isinstance(v, (int, float)) or v <= 0:
            raise ValueError(f"'bar_width' must be a positive number, got {v!r}")
        kwargs["bar_width"] = v


def _apply_area_fields(
    raw: dict[str, object], kwargs: dict[str, object], kind: ChartKind
) -> None:
    if kind != ChartKind.area:
        return
    _validate_bool_field(raw, "stacked", kwargs)
    if "alpha" in raw:
        v = raw["alpha"]
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not (0 <= v <= 1):
            raise ValueError(f"'alpha' must be between 0 and 1, got {v!r}")
        kwargs["alpha"] = v


def json_to_spec_list(raw: list[dict[str, object]]) -> list[ChartSpec]:
    """Parse a list of data-contract dicts; used by the grid config loader."""
    return [json_to_spec(item) for item in raw]


def _validate_series_rows(data: list[object], series_idx: int, x_field: str) -> None:
    for row_idx, row in enumerate(data):
        if not isinstance(row, dict):
            raise ValueError(
                f"series[{series_idx}].data[{row_idx}]: row must be a dict"
            )
        if x_field not in row:
            raise ValueError(
                f"series[{series_idx}].data[{row_idx}]: missing {x_field!r} key"
            )
        if "value" not in row:
            raise ValueError(
                f"series[{series_idx}].data[{row_idx}]: missing 'value' key"
            )
        val = row["value"]
        if not isinstance(val, (int, float)):
            raise ValueError(
                f"series[{series_idx}].data[{row_idx}]: 'value' must be numeric, "
                f"got {type(val).__name__}"
            )


def _coerce_series(
    raw_series: list[dict[str, object]], x_field: str
) -> list[SeriesSpec]:
    result: list[SeriesSpec] = []
    for series_idx, raw_s in enumerate(raw_series):
        if not isinstance(raw_s, dict):
            raise ValueError(
                f"series[{series_idx}]: must be a mapping, got {type(raw_s).__name__}"
            )
        name = raw_s.get("name")
        if not name:
            raise ValueError(f"series[{series_idx}]: missing required 'name' field")

        data = raw_s.get("data")
        if not isinstance(data, list):
            raise ValueError(f"series[{series_idx}]: 'data' must be a list")

        _validate_series_rows(data, series_idx, x_field)

        raw_color = raw_s.get("color")
        raw_label = raw_s.get("label")
        result.append(
            SeriesSpec(
                name=str(name),
                data=list(data),
                color=str(raw_color) if raw_color is not None else None,
                label=str(raw_label) if raw_label is not None else None,
                y_axis=str(raw_s.get("y_axis", "left")),
            )
        )
    return result


_KIND_MAP: dict[str, ChartKind] = {k.value: k for k in ChartKind}


def _detect_kind(raw: dict[str, object]) -> ChartKind:
    """Infer chart kind from 'kind' or 'type' key; defaults to line when absent."""
    if "kind" in raw:
        raw_type = raw["kind"]
    elif "type" in raw:
        raw_type = raw["type"]
    else:
        return ChartKind.line
    if raw_type is None:
        return ChartKind.line
    kind = _KIND_MAP.get(str(raw_type))
    if kind is None:
        raise ValueError(
            f"Unknown chart kind {raw_type!r}. Valid kinds: {list(_KIND_MAP.keys())}"
        )
    return kind
