"""Parsing for the `If-Match` optimistic-concurrency header, shared by every versioned write route.

The row `version` is a 32-bit integer, and clients may send it bare (`3`) or as an RFC 9110 entity
tag (`"3"`, `W/"3"`). Anything else is a client error — it must never reach the database layer or
surface as an unhandled `ValueError` (500)."""

from hrms.core.errors.base import ValidationError

_MAX_VERSION = 2_147_483_647  # Postgres INTEGER


def parse_if_match(value: str) -> int:
    raw = value.strip()
    if raw.startswith(("W/", "w/")):
        raw = raw[2:]
    if len(raw) >= 2 and raw[0] == raw[-1] == '"':
        raw = raw[1:-1]
    if not (raw.isascii() and raw.isdigit()) or int(raw) > _MAX_VERSION:
        raise ValidationError(
            "If-Match must be the resource's current integer version",
            code="INVALID_IF_MATCH",
            details=[
                {
                    "field": "If-Match",
                    "code": "INVALID_IF_MATCH",
                    "message": "If-Match must be the resource's current integer version",
                }
            ],
        )
    return int(raw)
