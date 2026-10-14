"""Content-based validation for employee document uploads.

Deliberately duplicates (rather than imports) the sniffing/sanitizing helpers from
`hrms.modules.onboarding.document_validation` — the only existing cross-module dependency
between the employee and onboarding modules runs the other way (onboarding composes the
employee module's services at case activation, never the reverse; `OnboardingActivationService`
docstring). Keeping that direction one-way (never employee -> onboarding) matches why
`DocumentStorageService` itself lives in `hrms.core` rather than in either domain module
(`hrms.core.storage` module docstring). The duplicated logic here is a small, stable magic-byte
table — see the onboarding module's own copy for the original SEC-04 rationale.

Client-supplied `UploadFile.content_type` is never trusted — every accepted upload is classified
from its own magic bytes, and that sniffed type is what gets persisted and stored, never the
caller's claim."""

import re
import unicodedata
from uuid import UUID

_SIGNATURES: tuple[tuple[bytes, str, str], ...] = (
    (b"%PDF-", "application/pdf", ".pdf"),
    (b"\xff\xd8\xff", "image/jpeg", ".jpg"),
    (b"\x89PNG\r\n\x1a\n", "image/png", ".png"),
)

_UNSAFE_FILENAME_CHARS = re.compile(r"[^A-Za-z0-9._ -]")
_FALLBACK_DISPLAY_NAME = "document"


def sniff_document_content_type(data: bytes) -> tuple[str, str] | None:
    """Returns `(content_type, extension)` for the first matching magic-byte signature, or
    `None` if `data` doesn't start with any of them."""
    for signature, content_type, extension in _SIGNATURES:
        if data.startswith(signature):
            return content_type, extension
    return None


def sanitize_display_filename(filename: str) -> str:
    """Produces a filename safe to store as display metadata and to echo back in a
    `Content-Disposition` header — never used to construct a storage path (see
    `safe_employee_document_object_key`)."""
    normalized = unicodedata.normalize("NFKC", filename)
    basename = normalized.replace("\\", "/").rsplit("/", 1)[-1]
    printable = "".join(ch for ch in basename if ch.isprintable())
    safe = _UNSAFE_FILENAME_CHARS.sub("_", printable).strip(" ._")
    if not safe:
        return _FALLBACK_DISPLAY_NAME
    return safe[:200]


def safe_employee_document_object_key(
    *, company_id: UUID, employee_id: UUID, document_id: UUID, extension: str
) -> str:
    """The storage key's filename component is always this fixed, server-chosen literal — never
    derived from client input. `document_id` already makes the key unique; `extension` comes
    from `sniff_document_content_type`'s verified result, never from the client's claimed
    filename."""
    return f"employee/{company_id}/{employee_id}/{document_id}/document{extension}"


def content_disposition_attachment(filename: str) -> str:
    """`Content-Disposition` value forcing a download rather than in-browser rendering —
    `filename` must already be `sanitize_display_filename`'s output before it reaches here."""
    return f'attachment; filename="{filename}"'
