"""DATA-01 — the DEK cache (`docs/audits/DATA_01_PII_ENCRYPTION_IMPLEMENTATION_PLAN.md` §2.1).
Lazily resolves and TTL-caches plaintext DEKs, in process memory only — this is what keeps the
registry lookup + master-key unwrap bounded to "at most once per key version per process per TTL
window," not once per field operation (plan §14; the wrap/unwrap mechanism itself moved from AWS
KMS to a local application key in RELEASE_HARDENING_PHASE_3A — see `master_key.py`). A single
`DekCache` instance must be shared across requests within a process (`get_dek_cache()` below is a
process-wide singleton, mirroring `get_settings()`'s own `lru_cache` convention) — a per-request
instance would defeat that property entirely."""

import asyncio
import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import lru_cache

from sqlalchemy.ext.asyncio import AsyncSession

from hrms.core.config.settings import Settings, get_settings
from hrms.core.crypto.errors import (
    DecryptionUnavailableError,
    EncryptionUnavailableError,
    NoActiveEncryptionKeyError,
    UnknownKeyVersionError,
)
from hrms.core.crypto.master_key import MasterKeyService
from hrms.core.crypto.registry import EncryptionKeyRegistry

#: Plan §5.4 — the fixed key version every development-mode ciphertext carries. Never a real KMS
#: key version; staging/production never reach this path (`Settings.is_development` gates it).
DEV_KEY_VERSION = 0


def derive_dev_dek(dev_encryption_key: str) -> bytes:
    """Plan §5.4 — SHA-256 of the configured string so any length input still yields a valid
    32-byte AES-256 key deterministically. Exposed as a top-level function (not only
    `DekCache`-internal) so tests that seed a pre-encrypted fixture value can derive the same key
    without duplicating the derivation, matching `Settings.dev_encryption_key`'s own default."""
    return hashlib.sha256(dev_encryption_key.encode("utf-8")).digest()


@dataclass
class _CachedDek:
    dek: bytes
    resolved_at: datetime


class DekCache:
    def __init__(
        self,
        settings: Settings,
        *,
        master: MasterKeyService | None = None,
        registry: EncryptionKeyRegistry | None = None,
    ) -> None:
        self._settings = settings
        self._master = master or MasterKeyService(settings)
        self._registry = registry or EncryptionKeyRegistry()
        self._dek_cache: dict[int, _CachedDek] = {}
        self._current_version_cache: tuple[int, datetime] | None = None
        self._lock = asyncio.Lock()

    def _ttl_expired(self, resolved_at: datetime) -> bool:
        age = datetime.now(UTC) - resolved_at
        return age > timedelta(seconds=self._settings.encryption_dek_cache_ttl_seconds)

    def _dev_dek(self) -> bytes:
        # Never used outside `environment=development`.
        return derive_dev_dek(self._settings.dev_encryption_key)

    async def get_current(self, session: AsyncSession) -> tuple[int, bytes]:
        """Resolves `(key_version, plaintext_dek)` for the current `ACTIVE` key — what every new
        write must use (plan §2.2). Fails closed: a write must never silently proceed without
        encryption (plan §5.5)."""
        if self._settings.is_development:
            return DEV_KEY_VERSION, self._dev_dek()

        async with self._lock:
            if self._current_version_cache is not None and not self._ttl_expired(
                self._current_version_cache[1]
            ):
                version = self._current_version_cache[0]
                cached = self._dek_cache.get(version)
                if cached is not None and not self._ttl_expired(cached.resolved_at):
                    return version, cached.dek

            try:
                row = await self._registry.get_active(session)
            except NoActiveEncryptionKeyError:
                raise
            except Exception as exc:  # noqa: BLE001 — deliberately broad: fail closed
                raise EncryptionUnavailableError(
                    "Unable to look up the current encryption key registry row."
                ) from exc

            cached = self._dek_cache.get(row.key_version)
            if cached is not None and not self._ttl_expired(cached.resolved_at):
                dek = cached.dek
            else:
                try:
                    dek = await self._master.decrypt_wrapped_dek(wrapped_dek_base64=row.wrapped_dek)
                except Exception as exc:  # noqa: BLE001 — deliberately broad: fail closed
                    raise EncryptionUnavailableError(
                        "Unable to unwrap the current DEK under the master key — refusing to "
                        "write unencrypted."
                    ) from exc
                self._dek_cache[row.key_version] = _CachedDek(
                    dek=dek, resolved_at=datetime.now(UTC)
                )
            self._current_version_cache = (row.key_version, datetime.now(UTC))
            return row.key_version, dek

    async def get_for_version(self, session: AsyncSession, *, key_version: int) -> bytes:
        """Resolves the plaintext DEK for a specific, possibly-`RETIRED`, key version — the read
        path (plan §2.2 "how old records remain decryptable"). Fails closed with a distinct error
        so a KMS outage degrades one field, not the whole response (plan §5.5)."""
        if self._settings.is_development:
            if key_version != DEV_KEY_VERSION:
                raise DecryptionUnavailableError(
                    f"No development key registered for key_version={key_version}."
                )
            return self._dev_dek()

        async with self._lock:
            cached = self._dek_cache.get(key_version)
            if cached is not None and not self._ttl_expired(cached.resolved_at):
                return cached.dek

            try:
                row = await self._registry.get_by_version(session, key_version=key_version)
            except UnknownKeyVersionError:
                raise
            except Exception as exc:  # noqa: BLE001 — deliberately broad: fail closed
                raise DecryptionUnavailableError(
                    f"Unable to look up encryption key_version={key_version} in the registry."
                ) from exc

            try:
                dek = await self._master.decrypt_wrapped_dek(wrapped_dek_base64=row.wrapped_dek)
            except Exception as exc:  # noqa: BLE001 — deliberately broad: fail closed
                raise DecryptionUnavailableError(
                    f"Unable to unwrap key_version={key_version} under the master key."
                ) from exc
            self._dek_cache[key_version] = _CachedDek(dek=dek, resolved_at=datetime.now(UTC))
            return dek

    def invalidate_current(self) -> None:
        """Plan §10.2 step 5 — called immediately after a rotation this process performed
        commits, so it picks up the new current version on its next operation rather than
        waiting out its own TTL. Other processes still pick it up lazily within their own TTL
        window (plan §2.1) — a bounded propagation delay, not a correctness gap (old-version
        writes during that window are still valid ciphertext, plan §10.2 step 6)."""
        self._current_version_cache = None


@lru_cache
def get_dek_cache() -> DekCache:
    """Process-wide singleton, mirroring `get_settings()`'s own `lru_cache` convention — see the
    class docstring for why a shared instance is load-bearing, not a convenience."""
    return DekCache(get_settings())
