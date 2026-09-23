"""OTLP telemetry emission for qwen_patch jobs.

Kept separate from ``worker.qwen`` so best-effort telemetry export can never
tangle with job control flow: a collector that is down, unreachable, or slow
must not fail, delay, or retry the job. ``export_job_span`` therefore wraps
its network call in its own broad exception guard.

Attributes and metrics follow contract.json's telemetry section: one OTLP
span per job under ``qwen.job``, attributes ``qwen.*``, tokens/duration as
metrics, and deliberately NO cost attribute.
"""

from __future__ import annotations

import json
import logging
import os
import uuid

_log = logging.getLogger(__name__)

SPAN_NAME = "qwen.job"
DEFAULT_OTLP_ENDPOINT = "http://localhost:4318"
OTLP_ENDPOINT_ENV = "OTEL_EXPORTER_OTLP_ENDPOINT"


def _resolve_endpoint() -> str:
    """Resolve the OTLP HTTP endpoint from the repo's documented env var.

    OTEL_EXPORTER_OTLP_ENDPOINT is the convention already referenced in
    src/telemetry/otel/health.py (there paired with the grpc port); no
    HTTP-specific env var was found elsewhere in src/telemetry during
    design, so this falls back to collector-config.yaml's http listener
    default, localhost:4318.
    """
    return os.environ.get(OTLP_ENDPOINT_ENV, "").strip() or DEFAULT_OTLP_ENDPOINT


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
                "resource": {"attributes": _otlp_attributes({"service.name": "qwen-worker"})},
                "scopeSpans": [{"spans": [span]}],
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
    not a job-control signal.
    """
    try:
        endpoint = _resolve_endpoint()
        span_doc = build_job_span(attrs, start_ns, end_ns)
        _post(f"{endpoint}/v1/traces", span_doc, timeout=5)
    except Exception:  # nosec B110 - best-effort telemetry: a down/slow/unreachable collector must never affect job outcome
        _log.debug("qwen: telemetry export failed (non-fatal)", exc_info=True)
