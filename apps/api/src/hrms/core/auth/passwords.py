from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

_hasher = PasswordHasher()

PASSWORD_MIN_LENGTH = 8


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except VerifyMismatchError:
        return False


def is_password_strong_enough(password: str) -> bool:
    """Minimum length + letter/digit complexity — no codified policy exists yet elsewhere.

    This is the first code path that creates a password (`docs/sprints/
    SPRINT_3_COMPANY_FOUNDATION.md`'s registration task note); intentionally simple until a
    dedicated password policy is defined.
    """
    if len(password) < PASSWORD_MIN_LENGTH:
        return False
    has_letter = any(c.isalpha() for c in password)
    has_digit = any(c.isdigit() for c in password)
    return has_letter and has_digit
