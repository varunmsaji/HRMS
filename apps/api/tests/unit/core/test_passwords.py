"""SEC-10 (RELEASE_HARDENING_PHASE_3A_SECURITY_REMEDIATION.md) — `is_password_strong_enough`'s
common-password blocklist addition."""

from hrms.core.auth.passwords import is_password_strong_enough


def test_too_short_rejected() -> None:
    assert not is_password_strong_enough("Ab1")


def test_missing_digit_rejected() -> None:
    assert not is_password_strong_enough("NoDigitsHere")


def test_missing_letter_rejected() -> None:
    assert not is_password_strong_enough("12345678")


def test_common_password_rejected_even_when_otherwise_compliant() -> None:
    # 8+ chars, has a letter and a digit — would pass the old checks alone.
    assert not is_password_strong_enough("password1")
    assert not is_password_strong_enough("Password123")
    assert not is_password_strong_enough("Welcome1")


def test_common_password_check_is_case_insensitive() -> None:
    assert not is_password_strong_enough("PASSWORD1")


def test_genuinely_strong_password_accepted() -> None:
    assert is_password_strong_enough("CorrectHorse9")
    assert is_password_strong_enough("Zx7!qP9mK2vL5")


def test_distinctive_project_password_not_accidentally_blocklisted() -> None:
    # This project's own seeded demo password must never collide with the common-password
    # blocklist — a regression here would lock every dev/test environment out of the demo login.
    assert is_password_strong_enough("DemoPass123!")


def test_password_length_boundaries() -> None:
    from hrms.core.auth.passwords import PASSWORD_MAX_LENGTH

    assert is_password_strong_enough("Ab3" + "x" * (PASSWORD_MAX_LENGTH - 3))
    assert not is_password_strong_enough("Ab3" + "x" * (PASSWORD_MAX_LENGTH - 2))
    assert is_password_strong_enough("Ab3xyz9q")  # exactly the 8-char minimum
    assert not is_password_strong_enough("Ab3xyz9")
