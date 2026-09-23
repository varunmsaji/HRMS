"""Content-based validation for onboarding document uploads (SEC-04,
docs/audits/UPLOAD_BATCH_B_FILE_VALIDATION.md).

No source document (plan, schema, or product spec) names an allowed file-type list for
onboarding documents (PAN/Aadhaar/photo/certificate/bank-proof scans) — this module's allowlist
is this task's own engineering decision, the same posture `ONBOARDING_DOCUMENT_MAX_SIZE_BYTES`
already took for the 10MB cap: PDF plus the two image formats every existing test fixture and the
web wizard's file picker already assume (JPEG, PNG) — the minimal set that covers a phone-camera
ID photo or a scanned/exported certificate. Documented here as an open ambiguity, not a silent
product decision: widening this list (e.g. HEIC, WebP, TIFF) is a product call, not an
engineering one.

Client-supplied `UploadFile.content_type` is never trusted (SEC-04) — every accepted upload is
classified from its own magic bytes, and that sniffed type is what gets persisted and stored,
never the caller's claim."""

import re
import unicodedata
from uuid import UUID

# (signature, content_type, extension) — checked in order, first match wins. Each signature is
# the canonical magic-byte prefix for the format; sniffing (not the client's `Content-Type`
# header or the claimed filename) is the sole source of truth for what a file actually is.
_SIGNATURES: tuple[tuple[bytes, str, str], ...] = (
    (b"%PDF-", "application/pdf", ".pdf"),
    (b"\xff\xd8\xff", "image/jpeg", ".jpg"),
    (b"\x89PNG\r\n\x1a\n", "image/png", ".png"),
)

_UNSAFE_FILENAME_CHARS = re.compile(r"[^A-Za-z0-9._ -]")
_FALLBACK_DISPLAY_NAME = "document"


def sniff_document_content_type(data: bytes) -> tuple[str, str] | None:
    """Returns `(content_type, extension)` for the first matching magic-byte signature, or
    `None` if `data` doesn't start with any of them — covers the empty file (`data == b""`
    matches no prefix), random binary, and any HTML/JS/other content masquerading as a document
    under a spoofed `Content-Type` or a misleading filename extension."""
    for signature, content_type, extension in _SIGNATURES:
        if data.startswith(signature):
            return content_type, extension
    return None


def sanitize_display_filename(filename: str) -> str:
    """Produces a filename safe to store as display metadata and to echo back in a
    `Content-Disposition` header — never used to construct a storage path (see
    `safe_document_object_key`), so this only needs to guard against header-injection (CR/LF and
    other control characters) and unprintable/unsafe characters, not path traversal.

    Strips any directory component first (a raw `../../x` or `..\\..\\x` must never even reach
    the character filter as a multi-segment path), drops non-printable characters (control
    characters, including the CR/LF that would otherwise let a filename inject extra HTTP
    headers into a `Content-Disposition` response), then replaces anything outside a small safe
    ASCII allowlist — including non-ASCII/unicode characters, which this deliberately does not
    attempt to transliterate — with `_`. Falls back to a fixed name if nothing safe survives, and
    caps length so an absurdly long filename can't bloat a stored/returned field."""
    normalized = unicodedata.normalize("NFKC", filename)
    basename = normalized.replace("\\", "/").rsplit("/", 1)[-1]
    printable = "".join(ch for ch in basename if ch.isprintable())
    safe = _UNSAFE_FILENAME_CHARS.sub("_", printable).strip(" ._")
    if not safe:
        return _FALLBACK_DISPLAY_NAME
    return safe[:200]


def safe_document_object_key(
    *, company_id: UUID, case_id: UUID, document_id: UUID, extension: str
) -> str:
    """The storage key's filename component is always this fixed, server-chosen literal — never
    derived from client input (SEC-04: "user filename ≠ storage path authority"). `document_id`
    already makes the key unique; `extension` comes from `sniff_document_content_type`'s verified
    result, never from the client's claimed filename, so the object's key extension always
    matches its actual bytes."""
    return f"onboarding/{company_id}/{case_id}/{document_id}/document{extension}"


def content_disposition_attachment(filename: str) -> str:
    """`Content-Disposition` value forcing a download rather than in-browser rendering (SEC-04) —
    `filename` must already be `sanitize_display_filename`'s output (no quotes/control characters
    to escape) before it reaches here."""
    return f'attachment; filename="{filename}"'
