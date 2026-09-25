"""DATA-01 — the narrow, explicit encrypt/decrypt API
(`docs/audits/DATA_01_PII_ENCRYPTION_IMPLEMENTATION_PLAN.md` §2.5/§2.6, and this batch's own
task item 11 "explicit decryption service"). This is the *only* surface `hrms.modules.employee`/
`hrms.modules.onboarding` service code is expected to call for DATA-01 fields — it composes
`DekCache` (key resolution), `field.py` (the crypto primitive), and `aad.py` (AAD construction) so
call sites never touch a raw DEK, a raw nonce, or hand-build an AAD string themselves.

**This class does not check authorization.** It has no idea what permission the caller holds,
and must not be given one — that is deliberate (task item 11: "the crypto helper should not
itself assume that every caller is authorized"; plan §2.5's encryption boundary: "Authorized
service explicitly calls decrypt"). The *caller* — `EmployeeBankService`, `OnboardingCaseService`,
etc. — is responsible for having already run the relevant permission check
(`EMPLOYEE.VIEW_BANKING`, and so on) before it calls `decrypt()` here. Calling this service is
what "explicit decryption" means in the plan; it is not itself the authorization boundary."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from hrms.core.config.settings import Settings, get_settings
from hrms.core.crypto.aad import build_column_aad, build_jsonb_key_aad
from hrms.core.crypto.field import decrypt_value, encrypt_value, parse_ciphertext
from hrms.core.crypto.keys import DekCache, get_dek_cache


class PiiCryptoService:
    def __init__(
        self,
        settings: Settings | None = None,
        *,
        dek_cache: DekCache | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._dek_cache = dek_cache or get_dek_cache()

    async def encrypt_column(
        self,
        session: AsyncSession,
        *,
        plaintext: str | None,
        table: str,
        column: str,
        record_id: UUID,
    ) -> str | None:
        """Plan §4.4's three real columns (`employee.pan_number_enc`,
        `employee.aadhaar_number_enc`, `employee_bank.account_number_enc`). `None` passes through
        unchanged (plan §4 null-handling row — matches every field's existing `nullable=True`
        behavior)."""
        if plaintext is None:
            return None
        key_version, dek = await self._dek_cache.get_current(session)
        aad = build_column_aad(table=table, column=column, record_id=record_id)
        return encrypt_value(plaintext, dek=dek, key_version=key_version, aad=aad)

    async def decrypt_column(
        self,
        session: AsyncSession,
        *,
        ciphertext: str | None,
        table: str,
        column: str,
        record_id: UUID,
    ) -> str | None:
        if ciphertext is None:
            return None
        dek, aad = await self._resolve_for_decrypt(
            session,
            ciphertext=ciphertext,
            aad=build_column_aad(table=table, column=column, record_id=record_id),
        )
        return decrypt_value(ciphertext, dek=dek, aad=aad)

    async def encrypt_jsonb_key(
        self,
        session: AsyncSession,
        *,
        plaintext: str | None,
        table: str,
        column: str,
        jsonb_key: str,
        record_id: UUID,
    ) -> str | None:
        """`onboarding_case.bank_info`'s `account_number_enc` key (plan §2.5/§7)."""
        if plaintext is None:
            return None
        key_version, dek = await self._dek_cache.get_current(session)
        aad = build_jsonb_key_aad(
            table=table, column=column, jsonb_key=jsonb_key, record_id=record_id
        )
        return encrypt_value(plaintext, dek=dek, key_version=key_version, aad=aad)

    async def decrypt_jsonb_key(
        self,
        session: AsyncSession,
        *,
        ciphertext: str | None,
        table: str,
        column: str,
        jsonb_key: str,
        record_id: UUID,
    ) -> str | None:
        if ciphertext is None:
            return None
        dek, aad = await self._resolve_for_decrypt(
            session,
            ciphertext=ciphertext,
            aad=build_jsonb_key_aad(
                table=table, column=column, jsonb_key=jsonb_key, record_id=record_id
            ),
        )
        return decrypt_value(ciphertext, dek=dek, aad=aad)

    async def _resolve_for_decrypt(
        self, session: AsyncSession, *, ciphertext: str, aad: str
    ) -> tuple[bytes, str]:
        key_version, _nonce, _ct = parse_ciphertext(ciphertext)
        dek = await self._dek_cache.get_for_version(session, key_version=key_version)
        return dek, aad
