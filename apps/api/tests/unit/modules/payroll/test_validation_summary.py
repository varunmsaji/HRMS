"""A failed validation reaches the user as plain `field: reason` text, never as Pydantic's own
rendering (model name, rejected input, documentation URL)."""

from pydantic import BaseModel, ValidationError

from hrms.modules.payroll.service import _validation_summary


class _Params(BaseModel):
    employee_rate_percent: int
    wage_ceiling_minor: int


def _failure() -> ValidationError:
    try:
        _Params.model_validate({"employee_rate_percent": "twelve", "wage_ceiling_minor": None})
    except ValidationError as exc:
        return exc
    raise AssertionError("expected a validation failure")


def test_a_pydantic_error_becomes_field_and_reason_only() -> None:
    text = _validation_summary(_failure())
    assert "employee_rate_percent:" in text and "wage_ceiling_minor:" in text
    for internal in (
        "errors.pydantic.dev",
        "input_value",
        "input_type",
        "[type=",
        "_Params",
        "twelve",
    ):
        assert internal not in text


def test_a_plain_value_error_keeps_its_written_sentence() -> None:
    assert _validation_summary(ValueError("A salary structure needs at least one line")) == (
        "A salary structure needs at least one line"
    )
