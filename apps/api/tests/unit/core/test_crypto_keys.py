"""DATA-01 — unit tests for `DekCache`
(`docs/audits/DATA_01_PII_ENCRYPTION_TEST_MATRIX.md` §1 "Key management"). Non-development-mode
tests use a fake `KmsKeyService`/real `EncryptionKeyRegistry` against the real test database
(`encryption_keys` is a real table — matches this repository's "no mocked database" integration
convention even for these otherwise-unit-shaped tests) so `DekCache`'s own registry-query logic is
exercised for real, not mocked away.

`encryption_keys` has no `company_id`/RLS scoping (it is environment-wide, not tenant data,
`hrms.core.crypto.models.EncryptionKey`'s own docstring) and a `key_version` `UNIQUE` constraint
starting at 1 — unlike most of this repository's tests (which avoid collisions by giving every
row its own random UUID), tests here would collide with each other unless the table is cleared
between tests, hence the local autouse fixture below."""

import base64

import pytest
from sqlalchemy import delete

from hrms.core.config.settings import Settings
from hrms.core.crypto.errors import (
    DecryptionUnavailableError,
    EncryptionUnavailableError,
    NoActiveEncryptionKeyError,
    UnknownKeyVersionError,
)
from hrms.core.crypto.keys import DEV_KEY_VERSION, DekCache, derive_dev_dek
from hrms.core.crypto.models import EncryptionKey
from hrms.core.crypto.registry import EncryptionKeyRegistry
from hrms.core.db.session import get_session_factory, session_scope

pytestmark = pytest.mark.asyncio

_TEST_ARN = "arn:aws:kms:ap-south-1:123456789012:key/test-key"


@pytest.fixture(autouse=True)
async def _clean_encryption_keys() -> None:
    async def _clear() -> None:
        factory = get_session_factory()
        async with factory() as session:
            await session.execute(delete(EncryptionKey))
            await session.commit()

    await _clear()
    yield
    await _clear()


class _FakeKms:
    """Records every call so tests can assert on call counts (plan §14's "at most one KMS call
    per key version per TTL window" property) — never touches real AWS."""

    def __init__(self) -> None:
        self.decrypt_calls = 0
        self.fail_decrypt = False

    async def generate_data_key(self, *, key_arn: str) -> tuple[bytes, str]:  # pragma: no cover
        raise NotImplementedError("not exercised — registry rows are seeded directly in tests")

    async def decrypt_wrapped_dek(self, *, key_arn: str, wrapped_dek_base64: str) -> bytes:
        self.decrypt_calls += 1
        if self.fail_decrypt:
            raise RuntimeError("simulated KMS outage")
        # Deterministic 32-byte "unwrapped" DEK derived from the wrapped value, so encrypting
        # under one call and decrypting under a later one (same wrapped value) stays consistent.
        return (wrapped_dek_base64.encode() * 8)[:32]


def _dev_settings() -> Settings:
    return Settings(environment="development")


def _prod_settings(**overrides: object) -> Settings:
    base: dict[str, object] = {
        "environment": "production",
        "jwt_access_secret": "Zx7!qP9$mK2#vL5^rT8&nB1@wD4%yF6*hJ0",
        "jwt_refresh_secret": "Qm3&zR8!kX1#pL6^bN9$vT2@yH5%wD0*jF4",
        "cors_allowed_origins": ("https://app.example.com",),
        "kms_cmk_arn": _TEST_ARN,
        "encryption_dek_cache_ttl_seconds": 3600,
        # INFRA-01 — required outside development since `_guard_non_development_config` now also
        # validates the self-hosted MinIO endpoint/bucket/credentials; explicit here (rather than
        # relying on a local `.env`) so this test passes in CI, where no `.env` file exists.
        "s3_endpoint_url": "http://minio:9000",
        "s3_bucket_documents": "hrms-test-documents",
        "aws_access_key_id": "test-access-key",
        "aws_secret_access_key": "test-secret-key",
    }
    base.update(overrides)
    return Settings(**base)


async def _seed_active_key(session: object) -> int:
    registry = EncryptionKeyRegistry()
    row = await registry.provision_initial(
        session,  # type: ignore[arg-type]
        key_version=1,
        kms_key_arn=_TEST_ARN,
        wrapped_dek_base64=base64.b64encode(b"seed-wrapped").decode("ascii"),
        created_by="test",
    )
    await session.commit()  # type: ignore[attr-defined]
    return row.key_version


async def test_development_mode_never_touches_kms_or_registry() -> None:
    kms = _FakeKms()
    cache = DekCache(_dev_settings(), kms=kms)  # type: ignore[arg-type]
    async with session_scope(_dev_settings()) as session:
        version, dek = await cache.get_current(session)
    assert version == DEV_KEY_VERSION
    assert dek == derive_dev_dek(_dev_settings().dev_encryption_key)
    assert kms.decrypt_calls == 0


async def test_development_mode_decrypts_for_the_dev_version_only() -> None:
    cache = DekCache(_dev_settings())
    async with session_scope(_dev_settings()) as session:
        dek = await cache.get_for_version(session, key_version=DEV_KEY_VERSION)
        assert dek == derive_dev_dek(_dev_settings().dev_encryption_key)
        with pytest.raises(DecryptionUnavailableError):
            await cache.get_for_version(session, key_version=99)


async def test_no_active_encryption_key_row_fails_closed() -> None:
    kms = _FakeKms()
    cache = DekCache(_prod_settings(), kms=kms)  # type: ignore[arg-type]
    async with session_scope(_prod_settings()) as session:
        with pytest.raises(NoActiveEncryptionKeyError):
            await cache.get_current(session)


async def test_unknown_key_version_in_ciphertext_fails_closed() -> None:
    kms = _FakeKms()
    cache = DekCache(_prod_settings(), kms=kms)  # type: ignore[arg-type]
    async with session_scope(_prod_settings()) as session:
        with pytest.raises(UnknownKeyVersionError):
            await cache.get_for_version(session, key_version=999)


async def test_current_key_resolves_and_caches_across_calls() -> None:
    kms = _FakeKms()
    cache = DekCache(_prod_settings(), kms=kms)  # type: ignore[arg-type]
    async with session_scope(_prod_settings()) as session:
        await _seed_active_key(session)

    async with session_scope(_prod_settings()) as session:
        version1, dek1 = await cache.get_current(session)
        version2, dek2 = await cache.get_current(session)
        version3, dek3 = await cache.get_current(session)

    assert version1 == version2 == version3 == 1
    assert dek1 == dek2 == dek3
    # Plan §14 — at most one KMS Decrypt call for three resolutions under the same cached
    # version, not one per call.
    assert kms.decrypt_calls == 1


async def test_kms_unavailable_on_write_fails_closed() -> None:
    kms = _FakeKms()
    kms.fail_decrypt = True
    cache = DekCache(_prod_settings(), kms=kms)  # type: ignore[arg-type]
    async with session_scope(_prod_settings()) as session:
        await _seed_active_key(session)

    async with session_scope(_prod_settings()) as session:
        with pytest.raises(EncryptionUnavailableError):
            await cache.get_current(session)


async def test_kms_unavailable_on_read_degrades_that_field_only() -> None:
    kms = _FakeKms()
    kms.fail_decrypt = True
    cache = DekCache(_prod_settings(), kms=kms)  # type: ignore[arg-type]
    async with session_scope(_prod_settings()) as session:
        await _seed_active_key(session)

    async with session_scope(_prod_settings()) as session:
        with pytest.raises(DecryptionUnavailableError):
            await cache.get_for_version(session, key_version=1)


async def test_key_rotation_old_version_still_decrypts() -> None:
    kms = _FakeKms()
    cache = DekCache(_prod_settings(), kms=kms)  # type: ignore[arg-type]
    registry = EncryptionKeyRegistry()

    async with session_scope(_prod_settings()) as session:
        await _seed_active_key(session)
        _version1, dek_v1 = await cache.get_current(session)

    async with session_scope(_prod_settings()) as session:
        new_row = await registry.rotate(
            session,
            kms_key_arn=_TEST_ARN,
            wrapped_dek_base64=base64.b64encode(b"rotated-wrapped").decode("ascii"),
            created_by="test",
        )
        await session.commit()
    cache.invalidate_current()

    async with session_scope(_prod_settings()) as session:
        version2, dek_v2 = await cache.get_current(session)
        # New writes use the new version (plan §10.2 step 5).
        assert version2 == new_row.key_version == 2
        assert dek_v2 != dek_v1
        # The old version is still resolvable for reads of historical ciphertext (plan §10.2
        # step 7).
        dek_v1_again = await cache.get_for_version(session, key_version=1)
        assert dek_v1_again == dek_v1


async def test_rotation_leaves_exactly_one_active_row() -> None:
    registry = EncryptionKeyRegistry()
    async with session_scope(_prod_settings()) as session:
        await _seed_active_key(session)

    async with session_scope(_prod_settings()) as session:
        await registry.rotate(
            session,
            kms_key_arn=_TEST_ARN,
            wrapped_dek_base64=base64.b64encode(b"rotated-again").decode("ascii"),
            created_by="test",
        )
        await session.commit()

    async with session_scope(_prod_settings()) as session:
        assert await registry.count_active(session) == 1
        active = await registry.get_active(session)
        assert active.key_version == 2
        retired = await registry.get_by_version(session, key_version=1)
        assert retired.status == "RETIRED"
        assert retired.retired_at is not None
