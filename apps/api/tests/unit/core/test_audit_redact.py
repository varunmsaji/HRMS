"""DATA-01 — unit tests for mandatory audit-log redaction
(`docs/audits/DATA_01_PII_ENCRYPTION_TEST_MATRIX.md` §5, `hrms.core.audit.redact`)."""

from hrms.core.audit.redact import (
    SENSITIVE_FIELD_MASKS,
    mask_aadhaar,
    mask_account_number,
    mask_pan,
    mask_sensitive,
)


def test_mask_account_number_shows_only_last_four_digits() -> None:
    assert mask_account_number("1234567890") == "******7890"


def test_mask_account_number_short_value_is_fully_masked() -> None:
    assert mask_account_number("123") == "***"


def test_mask_pan_shows_first_five_and_last_one() -> None:
    assert mask_pan("ABCDE1234F") == "ABCDE****F"


def test_mask_pan_falls_back_for_non_standard_length() -> None:
    # Never raises — masking must not be the thing that breaks a write. Falls back to the same
    # last-four convention as mask_account_number for a non-10-character value.
    assert mask_pan("SHORT") == mask_account_number("SHORT") == "*HORT"


def test_mask_aadhaar_shows_last_four_only() -> None:
    assert mask_aadhaar("123456789012") == "XXXX XXXX 9012"


def test_mask_sensitive_only_touches_registered_fields() -> None:
    payload = {
        "account_number_enc": "1234567890",
        "bank_name": "State Bank",
        "ifsc": "SBIN0001234",
        "is_primary": True,
    }
    result = mask_sensitive(payload, sensitive_fields=SENSITIVE_FIELD_MASKS)
    assert result["account_number_enc"] == "******7890"
    assert result["bank_name"] == "State Bank"
    assert result["ifsc"] == "SBIN0001234"
    assert result["is_primary"] is True


def test_mask_sensitive_does_not_mutate_the_input_dict() -> None:
    payload = {"account_number_enc": "1234567890"}
    mask_sensitive(payload, sensitive_fields=SENSITIVE_FIELD_MASKS)
    assert payload["account_number_enc"] == "1234567890"


def test_mask_sensitive_handles_a_null_sensitive_value() -> None:
    payload = {"account_number_enc": None, "bank_name": "State Bank"}
    result = mask_sensitive(payload, sensitive_fields=SENSITIVE_FIELD_MASKS)
    assert result["account_number_enc"] is None


def test_mask_sensitive_ignores_fields_not_present_in_payload() -> None:
    payload = {"bank_name": "State Bank"}
    result = mask_sensitive(payload, sensitive_fields=SENSITIVE_FIELD_MASKS)
    assert result == payload


def test_pan_and_aadhaar_are_pre_registered_in_the_mask_registry() -> None:
    # Plan §7.3 — registered even though no write path exists yet for either field, so a future
    # `employee_to_audit_dict()` inherits correct redaction with nothing left to add.
    assert "pan_number_enc" in SENSITIVE_FIELD_MASKS
    assert "aadhaar_number_enc" in SENSITIVE_FIELD_MASKS
    assert SENSITIVE_FIELD_MASKS["pan_number_enc"]("ABCDE1234F") == "ABCDE****F"
    assert SENSITIVE_FIELD_MASKS["aadhaar_number_enc"]("123456789012") == "XXXX XXXX 9012"
