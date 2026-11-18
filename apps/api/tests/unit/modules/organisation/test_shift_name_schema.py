"""SC-02 - shift and break names are trimmed before their length is checked.

Before SC-02 only the web form trimmed; the API stored `"  Morning "` as sent and accepted a
whitespace-only name, so mobile or direct callers could create shifts that look blank in pickers.
"""

import pytest
from pydantic import ValidationError

from hrms.modules.organisation.schemas import (
    ShiftBreakCreate,
    ShiftCreate,
    ShiftSetup,
    ShiftUpdate,
    ShiftVersionCreate,
)


def _break(name: str) -> ShiftBreakCreate:
    return ShiftBreakCreate(
        name=name, break_kind="FIXED_WINDOW", start_time="13:00", end_time="14:00"
    )


def _setup(name: str) -> ShiftSetup:
    return ShiftSetup(name=name, rules=ShiftVersionCreate())


@pytest.mark.parametrize(
    "build",
    [
        lambda n: ShiftCreate(name=n).name,
        lambda n: ShiftUpdate(name=n).name,
        lambda n: _setup(n).name,
        lambda n: _break(n).name,
    ],
    ids=["create", "update", "setup", "break"],
)
class TestNameIsTrimmed:
    def test_surrounding_spaces_are_removed(self, build) -> None:  # type: ignore[no-untyped-def]
        assert build("  Morning ") == "Morning"

    def test_tabs_and_newlines_are_removed(self, build) -> None:  # type: ignore[no-untyped-def]
        assert build("\tMorning\n") == "Morning"

    def test_inner_spaces_are_kept(self, build) -> None:  # type: ignore[no-untyped-def]
        assert build(" Early  Shift ") == "Early  Shift"

    def test_unicode_is_kept(self, build) -> None:  # type: ignore[no-untyped-def]
        assert build(" रात की पाली ") == "रात की पाली"

    @pytest.mark.parametrize("blank", ["", " ", "   ", "\t", " \n "])
    def test_blank_is_refused(self, build, blank: str) -> None:  # type: ignore[no-untyped-def]
        with pytest.raises(ValidationError):
            build(blank)

    def test_a_full_length_name_with_padding_is_accepted(self, build) -> None:  # type: ignore[no-untyped-def]
        assert build("  " + "x" * 100 + "  ") == "x" * 100

    def test_one_character_too_long_is_refused(self, build) -> None:  # type: ignore[no-untyped-def]
        with pytest.raises(ValidationError):
            build("x" * 101)


def test_shift_update_without_a_name_still_means_no_rename() -> None:
    patch = ShiftUpdate(is_active=False)
    assert patch.name is None
    assert "name" not in patch.model_fields_set


def test_shift_update_name_null_is_still_accepted() -> None:
    """Unchanged contract: an explicit null is the same as leaving the field out."""
    assert ShiftUpdate(name=None).name is None


def test_unknown_fields_are_still_refused() -> None:
    with pytest.raises(ValidationError):
        ShiftCreate(name="Morning", code="SHF-9")  # type: ignore[call-arg]


def test_publish_reason_is_not_trimmed_by_the_setup_schema() -> None:
    """Only the name is normalised; other text fields keep their existing behaviour."""
    assert (
        ShiftSetup(name="A", rules=ShiftVersionCreate(), publish_reason=" why ").publish_reason
        == " why "
    )
