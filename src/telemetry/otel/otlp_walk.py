"""Tolerant walkers over the nested OTLP JSONL shape.

Collector output is decoded JSON of unknown shape, so every consumer has to
survive ``null`` / numbers / strings / wrong container types at every nesting
level and non-dict elements inside every list. The guard lives in one
primitive, :func:`iter_dicts`, and every walker below is built from it.

Contract for the walkers (:func:`iter_dicts`, :func:`iter_children`,
:func:`iter_log_records`, :func:`iter_metrics`): never raise on malformed input;
yield only ``dict`` items; anything that is not the expected container type
yields nothing.

:func:`require_unix_nano` raises ``ValueError`` for unusable input; it is for
model ``from_dict`` constructors whose callers skip records on that exception.
:func:`parse_unix_nano` is the ``None``-returning variant.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

# OTLP timeUnixNano is a fixed64: [0, 2**64). Restricting to [0, 2**63) keeps
# every accepted value convertible by ``/ 1e9`` and ``datetime.fromtimestamp``
# on every platform instead of raising OverflowError / OSError later.
_MAX_UNIX_NANO = 2**63

# Exceptions one malformed record or element may raise during model parsing.
# OverflowError covers float()/int() of an oversized JSON number.
RECORD_EXCEPTIONS: tuple[type[Exception], ...] = (
    ValueError,
    KeyError,
    TypeError,
    AttributeError,
    IndexError,
    OverflowError,
)


def attr_key(raw: object) -> str | None:
    """Return *raw* as an attribute key, or ``None`` when it is not a string.

    A buggy encoder can emit ``{"key": [], ...}`` or ``{"key": null, ...}``;
    a list used as a dict key raises ``TypeError`` in callers.
    """
    return raw if isinstance(raw, str) else None


def iter_dicts(value: object) -> Iterator[dict[str, Any]]:
    """Yield the dict elements of *value* when it is a list; nothing otherwise."""
    if isinstance(value, list):
        for item in value:
            if isinstance(item, dict):
                yield item


def iter_children(parent: object, key: str) -> Iterator[dict[str, Any]]:
    """Yield the dict elements of ``parent[key]`` when *parent* is a dict."""
    if isinstance(parent, dict):
        yield from iter_dicts(parent.get(key))


def iter_log_records(obj: object) -> Iterator[dict[str, Any]]:
    """Yield every logRecord dict under ``resourceLogs[].scopeLogs[].logRecords[]``."""
    for resource in iter_children(obj, "resourceLogs"):
        for scope in iter_children(resource, "scopeLogs"):
            yield from iter_children(scope, "logRecords")


def iter_metrics(obj: object) -> Iterator[dict[str, Any]]:
    """Yield every metric dict under ``resourceMetrics[].scopeMetrics[].metrics[]``."""
    for resource in iter_children(obj, "resourceMetrics"):
        for scope in iter_children(resource, "scopeMetrics"):
            yield from iter_children(scope, "metrics")


def metric_series(metric: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Return ``(shape, data_points)`` for one metric.

    The one sum/gauge selection rule for every consumer: ``sum`` when it is a
    dict (Claude Code metrics are sums), otherwise ``gauge`` when that is a
    dict, otherwise an empty shape. *shape* is the chosen dict, so callers can
    read ``aggregationTemporality``.
    """
    sum_raw = metric.get("sum")
    chosen = sum_raw if isinstance(sum_raw, dict) else metric.get("gauge")
    shape: dict[str, Any] = chosen if isinstance(chosen, dict) else {}
    return shape, list(iter_dicts(shape.get("dataPoints")))


def select_datapoint_value(dp: dict[str, Any]) -> float:
    """Return a datapoint's value: ``asDouble``, else ``asInt``, else 0.0.

    OTLP integer points carry only ``asInt`` (JSON-encoded as a string), so
    reading ``asDouble`` alone yields 0.0 for them. An explicit ``null`` counts
    as absent.
    """
    v = dp.get("asDouble")
    if v is None:
        v = dp.get("asInt")
    if v is None:
        return 0.0
    return float(v)


def parse_unix_nano(value: object) -> int | None:
    """Return *value* as convertible unix nanoseconds, or ``None``.

    ``None`` means absent or unusable: non-numeric, ``bool``, NaN/inf,
    negative, or >= 2**63. Numeric strings and floats are accepted.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return None
    try:
        nano = int(value)
    except (ValueError, OverflowError):
        return None
    return nano if 0 <= nano < _MAX_UNIX_NANO else None


def require_unix_nano(value: object) -> int:
    """Return *value* as unix nanoseconds; raise ``ValueError`` if unusable.

    Callers pass a ``0`` default for an absent key, so ``None`` here means an
    explicit JSON ``null`` and is rejected, as ``int(None)`` was before.
    """
    nano = parse_unix_nano(value)
    if nano is None:
        raise ValueError(f"invalid unix nanosecond timestamp: {value!r}")
    return nano
