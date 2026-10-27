"""Dependency-free trace correlation (W3C Trace Context compatible).

This is *log/metric correlation*, not a tracing backend: there is no exporter, no sampling, no
span storage and therefore no memory or network cost. It gives every log line of a request, and of
the Celery task it dispatched, one `trace_id`, so a single `grep trace_id` follows an operation
across the API and the worker. It is deliberately wire-compatible with OpenTelemetry: a gateway
that sends a valid `traceparent` header is honoured, and the `traceparent` we put on task messages
is the one an OTel SDK would read, so enabling real tracing later (design in
docs/architecture/OBSERVABILITY_ARCHITECTURE.md §7) does not change any identifier on the wire.

Nothing here is sensitive or unbounded: trace and span ids are random hex, validated on input.
"""

from __future__ import annotations

import re
import secrets
from dataclasses import dataclass

import structlog

#: `00-<32 hex trace id>-<16 hex parent span id>-<2 hex flags>` (W3C Trace Context level 1).
_TRACEPARENT = re.compile(r"00-([0-9a-f]{32})-([0-9a-f]{16})-([0-9a-f]{2})")
_ZERO_TRACE = "0" * 32
_ZERO_SPAN = "0" * 16
TRACEPARENT_HEADER = "traceparent"


@dataclass(frozen=True)
class TraceContext:
    trace_id: str
    span_id: str
    #: the caller's span, when the context was continued from an inbound `traceparent`
    parent_span_id: str | None = None

    def traceparent(self) -> str:
        return f"00-{self.trace_id}-{self.span_id}-01"


def new_span_id() -> str:
    return secrets.token_hex(8)


def new_trace_id() -> str:
    return secrets.token_hex(16)


def parse_traceparent(raw: str | None) -> tuple[str, str] | None:
    """`(trace_id, parent_span_id)` for a well-formed, non-zero header; otherwise `None`. A
    malformed value is ignored (a fresh trace starts), never rejected."""
    if not raw:
        return None
    match = _TRACEPARENT.fullmatch(raw.strip().lower())
    if match is None:
        return None
    trace_id, span_id = match.group(1), match.group(2)
    if trace_id == _ZERO_TRACE or span_id == _ZERO_SPAN:
        return None
    return trace_id, span_id


def start_context(inbound_traceparent: str | None) -> TraceContext:
    """The context for one unit of work: continues the caller's trace when it sent a valid
    header, else starts a new one. The span id is always freshly generated for this unit."""
    parsed = parse_traceparent(inbound_traceparent)
    if parsed is None:
        return TraceContext(new_trace_id(), new_span_id())
    return TraceContext(parsed[0], new_span_id(), parent_span_id=parsed[1])


def current_traceparent() -> str | None:
    """The `traceparent` for work dispatched from the current context (None outside any)."""
    bound = structlog.contextvars.get_contextvars()
    trace_id, span_id = bound.get("trace_id"), bound.get("span_id")
    if isinstance(trace_id, str) and isinstance(span_id, str):
        return f"00-{trace_id}-{span_id}-01"
    return None
