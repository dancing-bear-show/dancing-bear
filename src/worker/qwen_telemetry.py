"""OTLP telemetry emission for qwen_patch jobs.

Kept separate from ``worker.qwen`` so best-effort telemetry export can never
tangle with job control flow: a collector that is down, unreachable, or slow
must not fail, delay, or retry the job. ``export_job_span`` and
``export_job_metrics`` therefore each wrap their own network call in a broad
exception guard, and are independent of each other — one failing must never
skip the other.

Attributes and metrics follow contract.json's telemetry section: one OTLP
span per job under ``qwen.job``, attributes ``qwen.*``, tokens/duration as
metrics, and deliberately NO cost attribute or metric.
"""

from __future__ import annotations

import json
import logging
import os
import time
import uuid

_log = logging.getLogger(__name__)

SPAN_NAME = "qwen.job"
SERVICE_NAME = "qwen-worker"
DEFAULT_OTLP_ENDPOINT = "http://localhost:4318"
TRACES_PATH = "/v1/traces"
METRICS_PATH = "/v1/metrics"

# Generic (signal-agnostic) OTel exporter env vars.
OTLP_ENDPOINT_ENV = "OTEL_EXPORTER_OTLP_ENDPOINT"
OTLP_PROTOCOL_ENV = "OTEL_EXPORTER_OTLP_PROTOCOL"

# Per-signal env vars take precedence over the generic ones and, per the
# OTel spec, are used AS-IS (a full URL, no path appended).
TRACES_ENDPOINT_ENV = "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT"
TRACES_PROTOCOL_ENV = "OTEL_EXPORTER_OTLP_TRACES_PROTOCOL"
METRICS_ENDPOINT_ENV = "OTEL_EXPORTER_OTLP_METRICS_ENDPOINT"
METRICS_PROTOCOL_ENV = "OTEL_EXPORTER_OTLP_METRICS_PROTOCOL"

_HTTP_PROTOCOLS = frozenset({"http/json", "http/protobuf"})

# Metric names. Token counts are cumulative sums (each job contributes one
# more count to a running total, matching OTLP's monotonic-sum convention
# for per-request counters like Claude Code's own token metrics); duration
# is a gauge because it is a point-in-time measurement of one job, not
# something that accumulates.
METRIC_PROMPT_TOKENS = "qwen.prompt_tokens"
METRIC_COMPLETION_TOKENS = "qwen.completion_tokens"
METRIC_GENERATION_DURATION_MS = "qwen.generation_duration_ms"


def _protocol_is_http(value: str) -> bool:
    return value.strip().lower() in _HTTP_PROTOCOLS


def _strip_trailing_slash(url: str) -> str:
    return url[:-1] if url.endswith("/") else url


def _resolve_signal_endpoint(
    *, signal_env: str, signal_protocol_env: str, path: str
) -> str:
    """Resolve the OTLP HTTP endpoint for one signal (traces or metrics).

    Resolution order, per standard OTel semantics:

    1. The per-signal endpoint var (e.g. ``OTEL_EXPORTER_OTLP_TRACES_ENDPOINT``),
       used AS-IS — a full URL, no path appended. That is the spec for
       per-signal endpoint vars: the caller is expected to supply the exact
       signal URL.
    2. The generic ``OTEL_EXPORTER_OTLP_ENDPOINT`` + path, but ONLY when the
       resolved protocol (per-signal protocol var, else the generic
       ``OTEL_EXPORTER_OTLP_PROTOCOL``) is ``http/json`` or ``http/protobuf``.
       This handler speaks OTLP/HTTP JSON; src/telemetry/otel/health.py's
       documented setup tells users to point the generic endpoint var at the
       collector's gRPC port with protocol=grpc, and appending an HTTP path
       to a gRPC endpoint would silently drop every export. A protocol of
       "grpc" (or unset with no explicit http protocol) is therefore treated
       as "this var was not meant for us" and falls through to the default.
    3. The default ``http://localhost:4318`` + path.

    A trailing slash is stripped before appending path in cases 2 and 3.
    """
    signal_endpoint = os.environ.get(signal_env, "").strip()
    if signal_endpoint:
        return signal_endpoint

    protocol = os.environ.get(signal_protocol_env, "").strip()
    if not protocol:
        protocol = os.environ.get(OTLP_PROTOCOL_ENV, "").strip()

    generic_endpoint = os.environ.get(OTLP_ENDPOINT_ENV, "").strip()
    if generic_endpoint and _protocol_is_http(protocol):
        return _strip_trailing_slash(generic_endpoint) + path

    return DEFAULT_OTLP_ENDPOINT + path


def _resolve_traces_endpoint() -> str:
    """Resolve the OTLP/HTTP traces endpoint. See _resolve_signal_endpoint."""
    return _resolve_signal_endpoint(
        signal_env=TRACES_ENDPOINT_ENV,
        signal_protocol_env=TRACES_PROTOCOL_ENV,
        path=TRACES_PATH,
    )


def _resolve_metrics_endpoint() -> str:
    """Resolve the OTLP/HTTP metrics endpoint. See _resolve_signal_endpoint."""
    return _resolve_signal_endpoint(
        signal_env=METRICS_ENDPOINT_ENV,
        signal_protocol_env=METRICS_PROTOCOL_ENV,
        path=METRICS_PATH,
    )


def _otlp_value(value: object) -> dict[str, object]:
    """Wrap a Python value as an OTLPValue-shaped dict (stringValue/intValue/...)."""
    if isinstance(value, bool):
        return {"boolValue": value}
    if isinstance(value, int):
        return {"intValue": value}
    if isinstance(value, float):
        return {"doubleValue": value}
    if value is None:
        return {"stringValue": ""}
    return {"stringValue": str(value)}


def _otlp_attributes(attrs: dict[str, object]) -> list[dict[str, object]]:
    return [{"key": key, "value": _otlp_value(value)} for key, value in attrs.items()]


def _resource(service_name: str = SERVICE_NAME) -> dict[str, object]:
    return {"attributes": _otlp_attributes({"service.name": service_name})}


def build_job_span(attrs: dict[str, object], start_ns: int, end_ns: int) -> dict[str, object]:
    """Build a {"resourceSpans": [...]} OTLP JSON document for one qwen.job span.

    Matches the shape telemetry.otel.models.OTLPSpansRecord.from_dict parses:
    resourceSpans[0].resource / .scopeSpans[0].spans[]. Attributes are all
    under the qwen.* namespace; no cost attribute is ever included.
    """
    span = {
        "traceId": uuid.uuid4().hex,
        "spanId": uuid.uuid4().hex[:16],
        "name": SPAN_NAME,
        "startTimeUnixNano": start_ns,
        "endTimeUnixNano": end_ns,
        "attributes": _otlp_attributes(attrs),
    }
    return {
        "resourceSpans": [
            {
                "resource": _resource(),
                "scopeSpans": [{"spans": [span]}],
            }
        ]
    }


def _sum_metric(name: str, value: float, attrs: dict[str, object], now_ns: int) -> dict[str, object]:
    """A monotonic cumulative-sum metric with one data point.

    Matches telemetry.otel.models.OTLPMetric.from_dict, which prefers the
    "sum" shape when present. Values are emitted under "asDouble" because
    MetricDataPoint.from_dict only reads that key (no "asInt" support) —
    an int under "asInt" would silently parse back as 0.0.
    """
    return {
        "name": name,
        "unit": "1",
        "sum": {
            "aggregationTemporality": 2,  # CUMULATIVE
            "isMonotonic": True,
            "dataPoints": [
                {
                    "startTimeUnixNano": now_ns,
                    "timeUnixNano": now_ns,
                    "asDouble": float(value),
                    "attributes": _otlp_attributes(attrs),
                }
            ],
        },
    }


def _gauge_metric(name: str, unit: str, value: float, attrs: dict[str, object], now_ns: int) -> dict[str, object]:
    """A gauge metric with one data point: a single point-in-time measurement,

    not something that accumulates across jobs. Matches OTLPMetric.from_dict's
    gauge.dataPoints fallback shape.
    """
    return {
        "name": name,
        "unit": unit,
        "gauge": {
            "dataPoints": [
                {
                    "startTimeUnixNano": now_ns,
                    "timeUnixNano": now_ns,
                    "asDouble": float(value),
                    "attributes": _otlp_attributes(attrs),
                }
            ]
        },
    }


def build_job_metrics(
    attrs: dict[str, object],
    duration_ms: float,
    prompt_tokens: int | None,
    completion_tokens: int | None,
    now_ns: int | None = None,
) -> dict[str, object]:
    """Build a {"resourceMetrics": [...]} OTLP JSON document for one job.

    Matches the shape telemetry.otel.models.OTLPMetricsRecord.from_dict
    parses: resourceMetrics[0].resource / .scopeMetrics[0].metrics[].
    Emits qwen.prompt_tokens/qwen.completion_tokens ONLY when Ollama
    returned them (absent, not zero-filled), plus
    qwen.generation_duration_ms unconditionally. No cost metric is ever
    included. attrs carries the same qwen.* identity attributes as the
    span, already masked by the caller.
    """
    timestamp_ns = now_ns if now_ns is not None else time.time_ns()
    metrics: list[dict[str, object]] = []
    if prompt_tokens is not None:
        metrics.append(_sum_metric(METRIC_PROMPT_TOKENS, prompt_tokens, attrs, timestamp_ns))
    if completion_tokens is not None:
        metrics.append(_sum_metric(METRIC_COMPLETION_TOKENS, completion_tokens, attrs, timestamp_ns))
    metrics.append(_gauge_metric(METRIC_GENERATION_DURATION_MS, "ms", duration_ms, attrs, timestamp_ns))

    return {
        "resourceMetrics": [
            {
                "resource": _resource(),
                "scopeMetrics": [{"metrics": metrics}],
            }
        ]
    }


def _post(url: str, body: dict[str, object], timeout: float) -> None:
    """POST body as JSON to url. The only network call site; tests patch this."""
    import urllib.request

    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(  # noqa: S310 - url is the resolved local/configured OTLP endpoint, not user input
        url, data=data, headers={"Content-Type": "application/json"}, method="POST"
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # nosec B310 - fixed configured OTLP endpoint, not user-controlled
        resp.read()


def export_job_span(attrs: dict[str, object], start_ns: int, end_ns: int) -> None:
    """Best-effort export of one qwen.job span. Never raises.

    Wrapped in a broad except so a collector that is down, unreachable, or
    slow cannot fail, delay, or retry the job — telemetry is observability,
    not a job-control signal. Independent of export_job_metrics: this export
    failing must never skip that one or vice versa.
    """
    try:
        endpoint = _resolve_traces_endpoint()
        span_doc = build_job_span(attrs, start_ns, end_ns)
        _post(endpoint, span_doc, timeout=5)
    except Exception:  # nosec B110 - best-effort telemetry: a down/slow/unreachable collector must never affect job outcome
        _log.debug("qwen: span export failed (non-fatal)", exc_info=True)


def export_job_metrics(
    attrs: dict[str, object],
    duration_ms: float,
    prompt_tokens: int | None,
    completion_tokens: int | None,
) -> None:
    """Best-effort export of one job's metrics. Never raises, never retried.

    Independent of export_job_span: this export failing must never skip
    that one or vice versa, and neither ever changes the job's outcome.
    """
    try:
        endpoint = _resolve_metrics_endpoint()
        metrics_doc = build_job_metrics(attrs, duration_ms, prompt_tokens, completion_tokens)
        _post(endpoint, metrics_doc, timeout=5)
    except Exception:  # nosec B110 - best-effort telemetry: a down/slow/unreachable collector must never affect job outcome
        _log.debug("qwen: metrics export failed (non-fatal)", exc_info=True)
