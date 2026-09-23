"""DATA-01 — the AAD construction convention
(`docs/audits/DATA_01_PII_ENCRYPTION_IMPLEMENTATION_PLAN.md` §2.4): ``table:column:record_id``,
or ``table:column.jsonb_key:record_id`` for a key inside a JSONB blob. A single, named builder so
every call site constructs AAD identically — a typo'd AAD string at encrypt time versus decrypt
time is indistinguishable from ciphertext tampering (both fail the same GCM authentication check),
so this function existing once, not re-typed at each call site, is itself a correctness control."""

from uuid import UUID


def build_column_aad(*, table: str, column: str, record_id: UUID) -> str:
    """`employee:pan_number_enc:{employee_id}`, `employee_bank:account_number_enc:{bank_id}`."""
    return f"{table}:{column}:{record_id}"


def build_jsonb_key_aad(*, table: str, column: str, jsonb_key: str, record_id: UUID) -> str:
    """`onboarding_case:bank_info.account_number_enc:{case_id}`."""
    return f"{table}:{column}.{jsonb_key}:{record_id}"
