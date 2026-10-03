from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

from hrms.core.auth.common_passwords import is_common_password

_hasher = PasswordHasher()

PASSWORD_MIN_LENGTH = 8
#: Upper bound on any password accepted by an endpoint. NIST 800-63B asks verifiers to permit at
#: least 64 characters; 128 is generous, while stopping an unauthenticated caller from making the
#: server run argon2 over an arbitrarily large body.
PASSWORD_MAX_LENGTH = 128


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except VerifyMismatchError:
        return False


def is_password_strong_enough(password: str) -> bool:
    """Minimum length + letter/digit complexity, plus a common-password blocklist check
    (SEC-10, RELEASE_HARDENING_PHASE_3A — the original gap this audit finding named). Forced
    rotation and mandatory special-character rules are deliberately still absent: NIST 800-63B
    recommends against both, so their absence is an intentional non-fix, not a remaining gap.

    This is the first code path that creates a password (`docs/sprints/
    SPRINT_3_COMPANY_FOUNDATION.md`'s registration task note); intentionally simple until a
    dedicated password policy is defined.
    """
    if not PASSWORD_MIN_LENGTH <= len(password) <= PASSWORD_MAX_LENGTH:
        return False
    has_letter = any(c.isalpha() for c in password)
    has_digit = any(c.isdigit() for c in password)
    if not (has_letter and has_digit):
        return False
    return not is_common_password(password)
