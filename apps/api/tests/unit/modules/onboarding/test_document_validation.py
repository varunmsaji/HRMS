"""Unit tests for SEC-04's content-sniffing/filename-safety helpers
(docs/audits/UPLOAD_BATCH_B_FILE_VALIDATION.md, `hrms.modules.onboarding.document_validation`).

Covers the MIME/magic-byte test matrix (§8) and filename/object-key test matrix (§10) from the
Batch B task brief."""

from uuid import UUID

from hrms.modules.onboarding.document_validation import (
    content_disposition_attachment,
    safe_document_object_key,
    sanitize_display_filename,
    sniff_document_content_type,
)

_COMPANY_ID = UUID("11111111-1111-1111-1111-111111111111")
_CASE_ID = UUID("22222222-2222-2222-2222-222222222222")
_DOCUMENT_ID = UUID("33333333-3333-3333-3333-333333333333")

_REAL_PDF = b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\nrest-of-file"
_REAL_JPEG = b"\xff\xd8\xff\xe0\x00\x10JFIF-ish-bytes"
_REAL_PNG = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR-ish-bytes"


class TestSniffDocumentContentType:
    def test_correct_extension_correct_mime_correct_bytes_pdf(self) -> None:
        assert sniff_document_content_type(_REAL_PDF) == ("application/pdf", ".pdf")

    def test_correct_extension_correct_mime_correct_bytes_jpeg(self) -> None:
        assert sniff_document_content_type(_REAL_JPEG) == ("image/jpeg", ".jpg")

    def test_correct_extension_correct_mime_correct_bytes_png(self) -> None:
        assert sniff_document_content_type(_REAL_PNG) == ("image/png", ".png")

    def test_html_pretending_to_be_pdf_is_rejected(self) -> None:
        html = b"<!DOCTYPE html><html><body>not a pdf</body></html>"
        assert sniff_document_content_type(html) is None

    def test_javascript_pretending_to_be_pdf_is_rejected(self) -> None:
        js = b"<script>alert('xss')</script>"
        assert sniff_document_content_type(js) is None

    def test_random_binary_data_is_rejected(self) -> None:
        assert sniff_document_content_type(bytes(range(256))) is None

    def test_empty_file_is_rejected(self) -> None:
        assert sniff_document_content_type(b"") is None

    def test_polyglot_pdf_html_prefix_is_rejected_when_bytes_dont_start_with_pdf_signature(
        self,
    ) -> None:
        # A classic PDF/HTML polyglot that leads with an HTML comment hiding a PDF body later in
        # the file — sniffing only trusts the prefix, so this is correctly rejected rather than
        # accepted on the strength of a PDF signature appearing later in the byte stream.
        polyglot = b"<!--\n%PDF-1.4\n...-->\n<html></html>"
        assert sniff_document_content_type(polyglot) is None

    def test_claimed_mime_is_irrelevant_bytes_are_authoritative(self) -> None:
        # This module never looks at a claimed Content-Type at all — the caller (service layer)
        # is what ignores it. Documented here: sniffing a real PDF succeeds regardless of what
        # any caller claimed the type was.
        assert sniff_document_content_type(_REAL_PDF) is not None

    def test_truncated_signature_is_rejected(self) -> None:
        assert sniff_document_content_type(b"\xff\xd8") is None


class TestSanitizeDisplayFilename:
    def test_normal_filename_is_preserved(self) -> None:
        assert sanitize_display_filename("normal.pdf") == "normal.pdf"

    def test_unix_path_traversal_is_reduced_to_basename(self) -> None:
        assert sanitize_display_filename("../../evil.pdf") == "evil.pdf"

    def test_windows_path_traversal_is_reduced_to_basename(self) -> None:
        assert sanitize_display_filename("..\\..\\evil.pdf") == "evil.pdf"

    def test_absolute_unix_path_is_reduced_to_basename(self) -> None:
        assert sanitize_display_filename("../../../etc/passwd") == "passwd"

    def test_script_tag_is_neutralized(self) -> None:
        result = sanitize_display_filename("<script>.html")
        assert "<" not in result
        assert ">" not in result

    def test_sql_injection_looking_filename_is_neutralized(self) -> None:
        result = sanitize_display_filename("invoice;DROP TABLE.pdf")
        assert ";" not in result
        assert result.endswith(".pdf")

    def test_filename_with_spaces_is_preserved(self) -> None:
        assert sanitize_display_filename("name with spaces.pdf") == "name with spaces.pdf"

    def test_unicode_filename_does_not_crash_and_stays_functional(self) -> None:
        result = sanitize_display_filename("résumé_中文.pdf")
        assert result  # non-empty
        assert result.endswith(".pdf")

    def test_very_long_filename_is_capped(self) -> None:
        result = sanitize_display_filename("a" * 5000 + ".pdf")
        assert len(result) <= 200

    def test_control_characters_are_stripped(self) -> None:
        result = sanitize_display_filename("evil\r\nX-Injected-Header: 1.pdf")
        assert "\r" not in result
        assert "\n" not in result

    def test_empty_after_sanitization_falls_back(self) -> None:
        assert sanitize_display_filename("////") == "document"

    def test_empty_input_falls_back(self) -> None:
        assert sanitize_display_filename("") == "document"


class TestSafeDocumentObjectKey:
    def test_key_never_contains_the_client_filename(self) -> None:
        key = safe_document_object_key(
            company_id=_COMPANY_ID, case_id=_CASE_ID, document_id=_DOCUMENT_ID, extension=".pdf"
        )
        assert key == (
            "onboarding/11111111-1111-1111-1111-111111111111/"
            "22222222-2222-2222-2222-222222222222/"
            "33333333-3333-3333-3333-333333333333/document.pdf"
        )

    def test_key_extension_matches_the_sniffed_type_not_any_client_claim(self) -> None:
        key = safe_document_object_key(
            company_id=_COMPANY_ID, case_id=_CASE_ID, document_id=_DOCUMENT_ID, extension=".jpg"
        )
        assert key.endswith("document.jpg")


class TestContentDispositionAttachment:
    def test_forces_attachment(self) -> None:
        value = content_disposition_attachment("photo.jpg")
        assert value == 'attachment; filename="photo.jpg"'
        assert value.startswith("attachment")
