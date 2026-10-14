"""Unit tests for `hrms.modules.employee.document_validation`.

Narrower than `tests/unit/modules/onboarding/test_document_validation.py` — the sniffing/
sanitizing helpers are deliberately duplicated (not imported) from the onboarding module (see
this module's own docstring for why), so their behavior is already covered there; this file only
exercises the one genuinely new function, `safe_employee_document_object_key`, plus a smoke check
that the duplicated helpers still behave identically."""

from uuid import UUID

from hrms.modules.employee.document_validation import (
    content_disposition_attachment,
    safe_employee_document_object_key,
    sanitize_display_filename,
    sniff_document_content_type,
)

_COMPANY_ID = UUID("11111111-1111-1111-1111-111111111111")
_EMPLOYEE_ID = UUID("44444444-4444-4444-4444-444444444444")
_DOCUMENT_ID = UUID("33333333-3333-3333-3333-333333333333")

_REAL_PDF = b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\nrest-of-file"
_REAL_JPEG = b"\xff\xd8\xff\xe0\x00\x10JFIF-ish-bytes"
_REAL_PNG = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR-ish-bytes"


class TestSafeEmployeeDocumentObjectKey:
    def test_key_shape_uses_employee_prefix_not_case(self) -> None:
        key = safe_employee_document_object_key(
            company_id=_COMPANY_ID,
            employee_id=_EMPLOYEE_ID,
            document_id=_DOCUMENT_ID,
            extension=".pdf",
        )
        assert key == (
            f"employee/{_COMPANY_ID}/{_EMPLOYEE_ID}/{_DOCUMENT_ID}/document.pdf"
        )

    def test_extension_is_whatever_was_passed_not_reinterpreted(self) -> None:
        key = safe_employee_document_object_key(
            company_id=_COMPANY_ID,
            employee_id=_EMPLOYEE_ID,
            document_id=_DOCUMENT_ID,
            extension=".png",
        )
        assert key.endswith("/document.png")


class TestSniffDocumentContentType:
    def test_pdf(self) -> None:
        assert sniff_document_content_type(_REAL_PDF) == ("application/pdf", ".pdf")

    def test_jpeg(self) -> None:
        assert sniff_document_content_type(_REAL_JPEG) == ("image/jpeg", ".jpg")

    def test_png(self) -> None:
        assert sniff_document_content_type(_REAL_PNG) == ("image/png", ".png")

    def test_html_pretending_to_be_pdf_is_rejected(self) -> None:
        html = b"<!DOCTYPE html><html><body>not a pdf</body></html>"
        assert sniff_document_content_type(html) is None

    def test_empty_bytes_rejected(self) -> None:
        assert sniff_document_content_type(b"") is None


class TestSanitizeDisplayFilename:
    def test_strips_directory_component(self) -> None:
        assert sanitize_display_filename("../../etc/passwd") == "passwd"

    def test_falls_back_when_nothing_safe_survives(self) -> None:
        assert sanitize_display_filename("***") == "document"


class TestContentDispositionAttachment:
    def test_wraps_filename_as_attachment(self) -> None:
        assert content_disposition_attachment("photo.jpg") == 'attachment; filename="photo.jpg"'
