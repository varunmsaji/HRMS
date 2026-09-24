"""Unit tests for payslip amounts in words (Indian numbering)."""

from hrms.modules.payroll.words import number_in_words, rupees_in_words


def test_indian_numbering() -> None:
    assert number_in_words(0) == "Zero"
    assert number_in_words(15) == "Fifteen"
    assert number_in_words(105) == "One Hundred Five"
    assert number_in_words(56_200) == "Fifty Six Thousand Two Hundred"
    assert number_in_words(1_00_000) == "One Lakh"
    assert number_in_words(1_23_45_678) == (
        "One Crore Twenty Three Lakh Forty Five Thousand Six Hundred Seventy Eight"
    )


def test_rupees_and_paise() -> None:
    assert rupees_in_words(5_620_000) == "Rupees Fifty Six Thousand Two Hundred Only"
    assert rupees_in_words(966_667) == (
        "Rupees Nine Thousand Six Hundred Sixty Six and Sixty Seven Paise Only"
    )
    assert rupees_in_words(0) == "Rupees Zero Only"
