"""SEC-10 (RELEASE_HARDENING_PHASE_3A_SECURITY_REMEDIATION.md) — a small, bundled list of the
most common passwords (from public breach-corpus frequency lists, e.g. the well-known
"10-million-password" / RockYou-derived top lists), checked entirely offline. This deliberately
does not call a live breach-check API (e.g. Have I Been Pwned's k-anonymity endpoint): this
deployment's architecture avoids new external network dependencies for a security control that
must not be a single point of failure for account creation, and a live API call would also leak
partial password-hash information off this server on every signup. A bundled list is the smallest
safe improvement over no breach-list check at all — it will never be as complete as a live
service, but it reliably blocks the passwords attackers try first."""

_COMMON_PASSWORDS: frozenset[str] = frozenset(
    p.lower()
    for p in (
        "123456",
        "123456789",
        "12345678",
        "12345",
        "1234567",
        "1234567890",
        "qwerty",
        "qwerty123",
        "password",
        "password1",
        "password123",
        "111111",
        "123123",
        "abc123",
        "1q2w3e4r",
        "1qaz2wsx",
        "iloveyou",
        "000000",
        "letmein",
        "welcome",
        "welcome1",
        "monkey",
        "dragon",
        "football",
        "baseball",
        "master",
        "superman",
        "trustno1",
        "sunshine",
        "shadow",
        "michael",
        "jennifer",
        "computer",
        "princess",
        "admin123",
        "administrator",
        "changeme",
        "letmein123",
        "qazwsx",
        "asdfghjkl",
        "zxcvbnm",
        "passw0rd",
        "p@ssw0rd",
        "p@ssword",
        "abcd1234",
        "123qwe",
        "qwerty1",
        "1qaz@wsx",
        "google",
        "whatever",
        "freedom",
        "starwars",
    )
)


def is_common_password(password: str) -> bool:
    return password.lower() in _COMMON_PASSWORDS
