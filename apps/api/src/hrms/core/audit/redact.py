"""DATA-01 — mandatory audit-log redaction
(`docs/audits/DATA_01_PII_ENCRYPTION_IMPLEMENTATION_PLAN.md` §7). `AuditService.record()` persists
`before_json`/`after_json` into an architecturally-immutable table
(`HRMS_SYSTEM_DESIGN_BASELINE.md` §20 invariant #8) — a value that reaches it in plaintext stays
there forever. This module is the one place every `*_to_audit_dict()` function
(`bank_to_audit_dict` today; a future `employee_to_audit_dict()` once PAN/Aadhaar get a write
path) applies masking, so the requirement cannot be silently missed at a new call site.

`SENSITIVE_FIELD_MASKS` deliberately registers `pan_number_enc`/`aadhaar_number_enc` even though
neither field has a write path yet (inventory §2) — plan §7.3's own point: a future write path's
own audit-dict function only has to call `mask_sensitive(..., sensitive_fields=
SENSITIVE_FIELD_MASKS)` to inherit correct redaction from day one, with nothing left to add here
when that slice ships."""

from collections.abc import Callable
from typing import Any

MaskFn = Callable[[str], str]


def mask_account_number(value: str) -> str:
    """Last-four-digit convention (inventory §8, `"Bank account: ******7890"`)."""
    if len(value) <= 4:
        return "*" * len(value)
    return "*" * (len(value) - 4) + value[-4:]


def mask_pan(value: str) -> str:
    """`"ABCDE****F"` — first five + last one, matching the documented PAN format exactly
    (inventory §8). A PAN is always exactly 10 characters; a differently-shaped value (test data,
    a future format change) falls back to the same last-four convention rather than raising, since
    masking must never be the thing that breaks a write."""
    if len(value) == 10:
        return f"{value[:5]}****{value[-1]}"
    return mask_account_number(value)


def mask_aadhaar(value: str) -> str:
    """`"XXXX XXXX 1234"` — last four only, matching the documented Aadhaar format exactly
    (inventory §8). An Aadhaar number is always exactly 12 digits; a differently-shaped value
    falls back to the same last-four convention."""
    if len(value) == 12:
        return f"XXXX XXXX {value[-4:]}"
    return mask_account_number(value)


#: Registered by field name (matches this codebase's existing `_enc` column-name convention), not
#: by table — one registry covers `employee`, `employee_bank`, and any future onboarding audit
#: call, without duplicating the mapping per table (plan §7.1).
SENSITIVE_FIELD_MASKS: dict[str, MaskFn] = {
    "account_number_enc": mask_account_number,
    "pan_number_enc": mask_pan,
    "aadhaar_number_enc": mask_aadhaar,
}


def mask_sensitive(
    payload: dict[str, Any], *, sensitive_fields: dict[str, MaskFn]
) -> dict[str, Any]:
    """Returns a new dict — never mutates `payload` in place — with every key present in both
    `payload` and `sensitive_fields` replaced by its masked form. A registered field whose value
    is `None` or not a `str` passes through unchanged (masking a value that was never written is a
    no-op, not an error). Every other key is untouched."""
    result = dict(payload)
    for field_name, mask_fn in sensitive_fields.items():
        value = result.get(field_name)
        if isinstance(value, str):
            result[field_name] = mask_fn(value)
    return result
