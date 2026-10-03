import pytest

from hrms.core.errors.base import ValidationError
from hrms.shared.if_match import parse_if_match


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("3", 3), ('"3"', 3), ('W/"3"', 3), (" 7 ", 7), ("0", 0), ("2147483647", 2147483647)],
)
def test_accepts_bare_and_entity_tag_forms(raw: str, expected: int) -> None:
    assert parse_if_match(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "",
        " ",
        "abc",
        "-1",
        "1.5",
        "1e3",
        '"3',
        '3"',
        "٣",
        "2147483648",
        "9" * 30,
        "3 4",
        '""',
        "+3",
    ],
)
def test_rejects_everything_else_with_a_clean_422(raw: str) -> None:
    with pytest.raises(ValidationError) as err:
        parse_if_match(raw)
    assert err.value.status_code == 422
    assert err.value.code == "INVALID_IF_MATCH"
