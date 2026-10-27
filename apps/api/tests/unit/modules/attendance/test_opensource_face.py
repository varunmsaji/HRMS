"""Open-source face engine: pure maths, config gating, provider semantics (fake embedder +
in-memory store - no model, no database, no network), the factory, and - when OpenCV and the
provisioned assets are present - the real detector/embedder on non-face and malformed input."""

import asyncio
import shutil
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from pydantic import ValidationError

from hrms.core.config.settings import Settings
from hrms.core.tenancy.context import TenantContext, clear_tenant, set_tenant
from hrms.modules.attendance import face_verification
from hrms.modules.attendance.face_verification import (
    FaceppFaceVerificationProvider,
    FaceProviderError,
    FaceProviderMultipleFacesError,
    FaceProviderNoFaceError,
    close_face_verification_providers,
    get_face_verification_provider,
    provider_for_stored_name,
)
from hrms.modules.attendance.opensource_face import assets
from hrms.modules.attendance.opensource_face.embedding_service import (
    EmbeddingImageError,
    EmbeddingOutcome,
    EmbeddingTimeoutError,
    EmbeddingUnavailableError,
    SFaceEmbeddingService,
)
from hrms.modules.attendance.opensource_face.engine import (
    PROVIDER_OPENSOURCE,
    OpenSourceFaceVerificationProvider,
    make_person_id,
    parse_person_id,
)
from hrms.modules.attendance.opensource_face.similarity import (
    EMBEDDING_DIM,
    InvalidEmbeddingError,
    best_similarity,
    cosine,
    normalise,
    to_score,
)
from hrms.modules.attendance.opensource_face.store import InMemoryEmbeddingStore

_ASSET_DIR = Path(__file__).resolve().parents[4] / "models/face/opensource-v1"
_ASSETS_PRESENT = all((_ASSET_DIR / n).is_file() for n in assets.ASSETS)


def _settings(**overrides: object) -> Settings:
    # Hermetic: no .env file, and no Face++ credentials leaking in from the developer's shell.
    base: dict[str, object] = {
        "face_verification_provider": "disabled",
        "facepp_api_key": "",
        "facepp_api_secret": "",
        "face_os_enabled": False,
        "face_os_model_dir": "",
    }
    base.update(overrides)
    return Settings(_env_file=None, **base)  # type: ignore[arg-type]


def _os_settings(**overrides: object) -> Settings:
    return _settings(
        face_verification_provider="opensource",
        face_os_enabled=True,
        face_os_model_dir="/nonexistent",
        **overrides,
    )


def _vec(*head: float) -> tuple[float, ...]:
    return normalise([*head, *([0.0] * (EMBEDDING_DIM - len(head)))])


# --- similarity -----------------------------------------------------------------------------


def test_normalise_rejects_bad_vectors() -> None:
    with pytest.raises(InvalidEmbeddingError):
        normalise([1.0] * 5)
    with pytest.raises(InvalidEmbeddingError):
        normalise([float("nan")] + [0.0] * (EMBEDDING_DIM - 1))
    with pytest.raises(InvalidEmbeddingError):
        normalise([0.0] * EMBEDDING_DIM)


def test_cosine_and_best_similarity() -> None:
    a, b, c = _vec(1, 0), _vec(1, 1), _vec(0, 1)
    assert cosine(a, a) == pytest.approx(1.0)
    assert cosine(a, c) == pytest.approx(0.0)
    assert best_similarity(a, [c, b]) == pytest.approx(2**-0.5)
    with pytest.raises(InvalidEmbeddingError):
        best_similarity(a, [])


def test_to_score_clamps_and_rounds() -> None:
    assert to_score(-0.4) == Decimal("0.0000")
    assert to_score(1.2) == Decimal("1.0000")
    assert to_score(0.123456) == Decimal("0.1235")


# --- configuration --------------------------------------------------------------------------


def test_default_provider_is_unchanged_and_engine_disabled() -> None:
    settings = _settings()
    assert settings.face_verification_provider == "disabled"
    assert settings.face_os_enabled is False


def test_opensource_requires_second_key_and_model_dir() -> None:
    with pytest.raises(ValidationError, match="face_os_enabled"):
        _settings(face_verification_provider="opensource", face_os_model_dir="/x")
    with pytest.raises(ValidationError, match="face_os_model_dir"):
        _settings(face_verification_provider="opensource", face_os_enabled=True)
    assert _os_settings().face_verification_provider == "opensource"


def test_opensource_thresholds_are_range_validated() -> None:
    with pytest.raises(ValidationError):
        _os_settings(face_os_match_threshold=0.05)
    with pytest.raises(ValidationError):
        _os_settings(face_os_match_threshold=1.5)
    with pytest.raises(ValidationError):
        _os_settings(face_os_max_concurrency=0)


def test_facepp_config_still_requires_credentials() -> None:
    with pytest.raises(ValidationError, match="facepp_api_key"):
        _settings(face_verification_provider="facepp")


# --- assets ---------------------------------------------------------------------------------


def test_verify_assets_detects_missing_and_corrupt(tmp_path: Path) -> None:
    with pytest.raises(assets.AssetError, match="missing"):
        assets.verify_assets(tmp_path)
    for name in assets.ASSETS:
        (tmp_path / name).write_bytes(b"not a model")
    with pytest.raises(assets.AssetError, match="failed verification"):
        assets.verify_assets(tmp_path)


def test_pinned_assets_are_sha256_and_have_a_licence() -> None:
    for digest, url, licence in assets.ASSETS.values():
        assert len(digest) == 64 and int(digest, 16) >= 0
        assert url.startswith("https://") and licence in {"MIT", "Apache-2.0"}


# --- provider semantics (fake embedder) -----------------------------------------------------


class FakeEmbedder:
    """Maps image bytes -> outcome; records every call. Stands in for SFaceEmbeddingService."""

    model_version = assets.MODEL_VERSION

    def __init__(self) -> None:
        self.outcomes: dict[bytes, EmbeddingOutcome | Exception] = {}
        self.calls: list[bytes] = []

    def add(self, image: bytes, outcome: EmbeddingOutcome | Exception) -> bytes:
        self.outcomes[image] = outcome
        return image

    async def embed(self, image: bytes) -> EmbeddingOutcome:
        self.calls.append(image)
        outcome = self.outcomes[image]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


@pytest.fixture
def tenant() -> object:
    company = uuid4()
    set_tenant(TenantContext(company_id=company))
    yield company
    clear_tenant()


@pytest.fixture
def engine() -> tuple[OpenSourceFaceVerificationProvider, FakeEmbedder, InMemoryEmbeddingStore]:
    embedder, store = FakeEmbedder(), InMemoryEmbeddingStore()
    provider = OpenSourceFaceVerificationProvider(
        _os_settings(face_os_match_threshold=0.5, face_os_max_samples_per_person=3),
        embedder=embedder,  # type: ignore[arg-type]
        store=store,
    )
    return provider, embedder, store


def _ok(*head: float) -> EmbeddingOutcome:
    return EmbeddingOutcome("OK", _vec(*head))


async def test_enroll_then_verify_matches_and_rejects(engine, tenant) -> None:  # type: ignore[no-untyped-def]
    provider, emb, store = engine
    person = await provider.enroll(
        label=str(uuid4()), image=emb.add(b"front", _ok(1, 0)), content_type="image/jpeg"
    )
    assert person.startswith("osf1.") and len(person) <= 100
    assert (
        await provider.verify(
            person_id=person, image=emb.add(b"same", _ok(1, 0.1)), content_type="image/jpeg"
        )
    ).decision == "MATCHED"
    other = await provider.verify(
        person_id=person, image=emb.add(b"other", _ok(0, 1)), content_type="image/jpeg"
    )
    assert other.decision == "NO_MATCH" and other.similarity == Decimal("0.0000")


async def test_threshold_boundary_is_inclusive(engine, tenant) -> None:  # type: ignore[no-untyped-def]
    provider, emb, _ = engine
    person = await provider.enroll(
        label=str(uuid4()), image=emb.add(b"f", _ok(1, 0)), content_type="x"
    )
    # cosine((1,0),(0.5, sqrt(.75))) = 0.5 exactly at the 0.5 threshold; just below is NO_MATCH.
    at = emb.add(b"at", EmbeddingOutcome("OK", normalise([0.5, 0.75**0.5] + [0.0] * 126)))
    below = emb.add(b"below", EmbeddingOutcome("OK", normalise([0.49, 0.8717798] + [0.0] * 126)))
    assert (
        await provider.verify(person_id=person, image=at, content_type="x")
    ).decision == "MATCHED"
    assert (
        await provider.verify(person_id=person, image=below, content_type="x")
    ).decision == "NO_MATCH"


async def test_best_of_enrolled_samples_decides(engine, tenant) -> None:  # type: ignore[no-untyped-def]
    provider, emb, _ = engine
    person = await provider.enroll(
        label=str(uuid4()), image=emb.add(b"f", _ok(1, 0)), content_type="x"
    )
    await provider.add_reference_photo(
        person_id=person, image=emb.add(b"l", _ok(0, 1)), content_type="x"
    )
    res = await provider.verify(person_id=person, image=emb.add(b"p", _ok(0, 1)), content_type="x")
    assert res.decision == "MATCHED" and res.similarity == Decimal("1.0000")


async def test_unusable_photos_map_to_port_outcomes(engine, tenant) -> None:  # type: ignore[no-untyped-def]
    provider, emb, _ = engine
    with pytest.raises(FaceProviderNoFaceError):
        await provider.enroll(
            label=str(uuid4()), image=emb.add(b"n", EmbeddingOutcome("NO_FACE")), content_type="x"
        )
    with pytest.raises(FaceProviderMultipleFacesError):
        await provider.enroll(
            label=str(uuid4()),
            image=emb.add(b"m", EmbeddingOutcome("MULTIPLE_FACES")),
            content_type="x",
        )
    person = await provider.enroll(
        label=str(uuid4()), image=emb.add(b"f", _ok(1)), content_type="x"
    )
    r = await provider.verify(
        person_id=person, image=emb.add(b"m2", EmbeddingOutcome("MULTIPLE_FACES")), content_type="x"
    )
    assert (r.decision, r.similarity) == ("MULTIPLE_FACES", None)
    r = await provider.verify(
        person_id=person, image=emb.add(b"s", EmbeddingOutcome("FACE_TOO_SMALL")), content_type="x"
    )
    assert (r.decision, r.similarity) == ("NO_FACE", None)


async def test_model_failure_is_an_error_never_a_match(engine, tenant) -> None:  # type: ignore[no-untyped-def]
    provider, emb, _ = engine
    person = await provider.enroll(
        label=str(uuid4()), image=emb.add(b"f", _ok(1)), content_type="x"
    )
    for exc in (
        EmbeddingUnavailableError("boom"),
        EmbeddingTimeoutError("slow"),
        EmbeddingImageError("bad"),
    ):
        with pytest.raises(FaceProviderError):
            await provider.verify(
                person_id=person, image=emb.add(b"x%d" % id(exc), exc), content_type="x"
            )


async def test_sample_cap_and_unknown_person(engine, tenant) -> None:  # type: ignore[no-untyped-def]
    provider, emb, _ = engine
    person = await provider.enroll(
        label=str(uuid4()), image=emb.add(b"f", _ok(1)), content_type="x"
    )
    for i in range(2):
        await provider.add_reference_photo(
            person_id=person, image=emb.add(b"a%d" % i, _ok(1)), content_type="x"
        )
    with pytest.raises(FaceProviderError):
        await provider.add_reference_photo(
            person_id=person, image=emb.add(b"over", _ok(1)), content_type="x"
        )
    ghost = make_person_id(tenant, uuid4())  # type: ignore[arg-type]
    with pytest.raises(FaceProviderError):
        await provider.add_reference_photo(
            person_id=ghost, image=emb.add(b"g", _ok(1)), content_type="x"
        )
    with pytest.raises(FaceProviderError):  # nothing enrolled -> not a biometric NO_MATCH
        await provider.verify(person_id=ghost, image=emb.add(b"g2", _ok(1)), content_type="x")


async def test_person_ids_are_tenant_bound_and_engine_specific(engine, tenant) -> None:  # type: ignore[no-untyped-def]
    provider, emb, store = engine
    person = await provider.enroll(
        label=str(uuid4()), image=emb.add(b"f", _ok(1)), content_type="x"
    )
    # A Face++ FaceSet token is never accepted - and never "deleted successfully".
    for bad in ("0123456789abcdef0123456789abcdef", "osf1.not-a-uuid.x", "osf1.a.b.c"):
        with pytest.raises(FaceProviderError):
            await provider.delete_person(person_id=bad)
    # Another tenant's person id fails closed under this request's tenant.
    foreign = make_person_id(uuid4(), uuid4())
    with pytest.raises(FaceProviderError):
        await provider.verify(person_id=foreign, image=emb.add(b"x", _ok(1)), content_type="x")
    assert parse_person_id(person)[0] == tenant


async def test_embeddings_of_another_model_version_are_not_compared(engine, tenant) -> None:  # type: ignore[no-untyped-def]
    provider, emb, store = engine
    person = await provider.enroll(
        label=str(uuid4()), image=emb.add(b"f", _ok(1)), content_type="x"
    )
    store.rows = [(*r[:4], "other-model", r[5]) for r in store.rows]
    with pytest.raises(FaceProviderError, match="re-enrolment"):
        await provider.verify(person_id=person, image=emb.add(b"p", _ok(1)), content_type="x")


async def test_delete_removes_only_that_person(engine, tenant) -> None:  # type: ignore[no-untyped-def]
    provider, emb, store = engine
    a = await provider.enroll(label=str(uuid4()), image=emb.add(b"a", _ok(1)), content_type="x")
    b = await provider.enroll(label=str(uuid4()), image=emb.add(b"b", _ok(0, 1)), content_type="x")
    await provider.delete_person(person_id=a)
    await provider.delete_person(person_id=a)  # idempotent
    assert {str(r[2]) for r in store.rows} == {b.split(".")[2]}


async def test_enroll_needs_tenant_and_employee_label(engine) -> None:  # type: ignore[no-untyped-def]
    provider, emb, _ = engine
    clear_tenant()
    with pytest.raises(FaceProviderError):
        await provider.enroll(label=str(uuid4()), image=emb.add(b"f", _ok(1)), content_type="x")
    set_tenant(TenantContext(company_id=uuid4()))
    try:
        with pytest.raises(FaceProviderError):
            await provider.enroll(label="not-a-uuid", image=emb.add(b"f", _ok(1)), content_type="x")
    finally:
        clear_tenant()


async def test_no_network_is_used(engine, tenant, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    def forbidden(*a: object, **k: object) -> None:
        raise AssertionError("the open-source engine must not use the network")

    monkeypatch.setattr(httpx, "AsyncClient", forbidden)
    monkeypatch.setattr(httpx, "Client", forbidden)
    provider, emb, _ = engine
    person = await provider.enroll(
        label=str(uuid4()), image=emb.add(b"f", _ok(1)), content_type="x"
    )
    await provider.verify(person_id=person, image=emb.add(b"p", _ok(1)), content_type="x")


# --- factory / engine selection -------------------------------------------------------------


async def test_factory_selects_exactly_the_configured_engine() -> None:
    await close_face_verification_providers()
    assert get_face_verification_provider(_settings()) is None
    facepp = get_face_verification_provider(
        _settings(face_verification_provider="facepp", facepp_api_key="k", facepp_api_secret="s")
    )
    assert isinstance(facepp, FaceppFaceVerificationProvider)
    os_provider = get_face_verification_provider(_os_settings())
    assert isinstance(os_provider, OpenSourceFaceVerificationProvider)
    assert os_provider.provider_name == PROVIDER_OPENSOURCE != facepp.provider_name
    assert os_provider is get_face_verification_provider(_os_settings())
    await close_face_verification_providers()
    assert not face_verification._shared_opensource and not face_verification._shared_providers


def test_deletion_provider_follows_the_stored_engine_not_the_selected_one() -> None:
    selected_os = _os_settings(facepp_api_key="k", facepp_api_secret="s")
    assert isinstance(
        provider_for_stored_name("FACEPP", selected_os), FaceppFaceVerificationProvider
    )
    assert isinstance(
        provider_for_stored_name("OPENSOURCE", _settings()), OpenSourceFaceVerificationProvider
    )
    assert provider_for_stored_name("FACEPP", _settings()) is None  # no credentials -> deferred
    # Face attendance disabled: Face++ deletions stay deferred even when credentials exist.
    assert (
        provider_for_stored_name("FACEPP", _settings(facepp_api_key="k", facepp_api_secret="s"))
        is None
    )
    assert provider_for_stored_name(None, _settings()) is None


def test_failure_in_one_engine_never_selects_the_other() -> None:
    """There is no fallback code path: the factory returns one provider or None."""
    assert get_face_verification_provider(_os_settings()).provider_name == "OPENSOURCE"  # type: ignore[union-attr]


# --- real detector / embedder (skipped without OpenCV or provisioned assets) ----------------

real = pytest.mark.skipif(not _ASSETS_PRESENT, reason="models/face/opensource-v1 not provisioned")


def _service(model_dir: Path = _ASSET_DIR, **kw: object) -> SFaceEmbeddingService:
    params: dict[str, object] = dict(
        detector_score_threshold=0.9, min_face_px=80, max_concurrency=2, timeout_seconds=10.0
    )
    params.update(kw)
    return SFaceEmbeddingService(model_dir, **params)  # type: ignore[arg-type]


@real
async def test_real_models_load_and_noise_has_no_face() -> None:
    np = pytest.importorskip("numpy")
    cv2 = pytest.importorskip("cv2")
    service = _service()
    service.warm_up()
    noise = np.random.default_rng(0).integers(0, 255, (320, 320, 3), dtype=np.uint8)
    ok, jpeg = cv2.imencode(".jpg", noise)
    assert ok
    assert (await service.embed(jpeg.tobytes())).status == "NO_FACE"


@real
async def test_real_malformed_and_out_of_bounds_inputs_fail_safely() -> None:
    pytest.importorskip("cv2")
    service = _service()
    for bad in (
        b"",
        b"GIF89a....",
        b"\xff\xd8\xff" + b"\x00" * 20,
        b"\x89PNG\r\n\x1a\n" + b"\x00" * 30,
    ):
        with pytest.raises(EmbeddingImageError):
            await service.embed(bad)


@real
def test_real_corrupted_asset_is_refused(tmp_path: Path) -> None:
    pytest.importorskip("cv2")
    for name in assets.ASSETS:
        shutil.copy(_ASSET_DIR / name, tmp_path / name)
    (tmp_path / assets.RECOGNIZER_FILE).write_bytes(b"corrupted")
    with pytest.raises(EmbeddingUnavailableError, match="failed verification"):
        _service(tmp_path).warm_up()


def test_missing_assets_fail_clearly(tmp_path: Path) -> None:
    pytest.importorskip("cv2")
    with pytest.raises(EmbeddingUnavailableError, match="missing"):
        _service(tmp_path).warm_up()


async def test_saturated_engine_times_out_instead_of_queueing() -> None:
    service = _service(max_concurrency=1, timeout_seconds=0.2)
    service._built = 1  # one instance exists and is checked out
    with pytest.raises(EmbeddingTimeoutError):
        await asyncio.to_thread(service._acquire, __import__("time").monotonic() + 0.1)


# --- ciphertext binding (synthetic embeddings; development DEK, no database) -------------------


async def test_embedding_ciphertext_is_bound_to_every_ownership_column() -> None:
    """A stored template cannot be re-pointed at another employee / person / tenant / row, nor
    reinterpreted under another model version: decryption fails closed (GCM authentication)."""
    from uuid import uuid4 as _uuid4

    from hrms.core.crypto.errors import DecryptionFailedError
    from hrms.core.crypto.service import PiiCryptoService
    from hrms.modules.attendance.opensource_face.store import _aad_record_id

    crypto = PiiCryptoService(_settings(environment="development"))
    base = dict(
        row_id=_uuid4(),
        company_id=_uuid4(),
        employee_id=_uuid4(),
        person_ref=_uuid4(),
        sample_index=0,
        model_version="sface-2021dec",
    )
    token = await crypto.encrypt_column(
        None,  # type: ignore[arg-type]  # development DEK needs no session
        plaintext="[0.1, 0.2]",
        table="face_embedding",
        column="embedding_enc",
        record_id=_aad_record_id(**base),
    )
    assert token is not None and token.startswith("v1:") and "0.1" not in token

    async def read(**changes: object) -> str | None:
        return await crypto.decrypt_column(
            None,  # type: ignore[arg-type]
            ciphertext=token,
            table="face_embedding",
            column="embedding_enc",
            record_id=_aad_record_id(**{**base, **changes}),  # type: ignore[arg-type]
        )

    assert await read() == "[0.1, 0.2]"
    for field, other in (
        ("row_id", _uuid4()),
        ("company_id", _uuid4()),
        ("employee_id", _uuid4()),
        ("person_ref", _uuid4()),
        ("sample_index", 1),
        ("model_version", "other-model"),
    ):
        with pytest.raises(DecryptionFailedError):
            await read(**{field: other})
    # A different column / table with the right id also fails.
    with pytest.raises(DecryptionFailedError):
        await crypto.decrypt_column(
            None,  # type: ignore[arg-type]
            ciphertext=token,
            table="face_embedding",
            column="other_column",
            record_id=_aad_record_id(**base),  # type: ignore[arg-type]
        )
    # Nonces are fresh per encryption (same plaintext, same binding -> different ciphertext).
    again = await crypto.encrypt_column(
        None,  # type: ignore[arg-type]
        plaintext="[0.1, 0.2]",
        table="face_embedding",
        column="embedding_enc",
        record_id=_aad_record_id(**base),
    )
    assert again != token


# --- bounded concurrency / admission ---------------------------------------------------------


def _fake_service(**kw: object) -> SFaceEmbeddingService:
    """A service whose inference is replaced by a slow stub that records parallelism."""
    import threading
    import time

    service = _service(Path("/unused"), **kw)
    state = {"running": 0, "peak": 0, "calls": 0}
    lock = threading.Lock()

    def slow(image: bytes, deadline: float) -> EmbeddingOutcome:
        with lock:
            state["running"] += 1
            state["calls"] += 1
            state["peak"] = max(state["peak"], state["running"])
        try:
            time.sleep(0.15)
            if image == b"boom":
                raise EmbeddingUnavailableError("model exploded")
            return EmbeddingOutcome("NO_FACE")
        finally:
            with lock:
                state["running"] -= 1

    service._embed_sync = slow  # type: ignore[method-assign]
    service.state = state  # type: ignore[attr-defined]
    return service


_PNG = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR" + (400).to_bytes(4, "big") * 2 + b"\x00" * 10


async def test_inference_is_bounded_and_overflow_fails_fast() -> None:
    service = _fake_service(max_concurrency=1, timeout_seconds=0.5)
    results = await asyncio.gather(
        *[service.embed(_PNG) for _ in range(12)], return_exceptions=True
    )
    ok = [r for r in results if isinstance(r, EmbeddingOutcome)]
    busy = [r for r in results if isinstance(r, EmbeddingTimeoutError)]
    assert service.state["peak"] == 1  # type: ignore[attr-defined]
    assert ok and busy and len(ok) + len(busy) == 12
    # The waiting room is bounded (1 running + 4 waiting admitted at once, the rest rejected
    # immediately), so a flood cannot pile up threads or memory.
    assert service.state["calls"] <= 5  # type: ignore[attr-defined]


async def test_slot_is_released_after_error_and_after_cancellation() -> None:
    service = _fake_service(max_concurrency=1, timeout_seconds=2.0)
    service._embed_sync = lambda image, deadline: (_ for _ in ()).throw(  # type: ignore[method-assign]
        EmbeddingUnavailableError("model exploded")
    )
    for _ in range(3):  # would deadlock on the 2nd call if the slot leaked
        with pytest.raises(EmbeddingUnavailableError):
            await asyncio.wait_for(service.embed(_PNG), 1.0)

    service = _fake_service(max_concurrency=1, timeout_seconds=2.0)
    task = asyncio.create_task(service.embed(_PNG))
    await asyncio.sleep(0.03)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert (await asyncio.wait_for(service.embed(_PNG), 2.0)).status == "NO_FACE"


async def test_deletion_needs_no_model_and_never_builds_the_embedder(tenant) -> None:  # type: ignore[no-untyped-def]
    provider = OpenSourceFaceVerificationProvider(_os_settings(), store=InMemoryEmbeddingStore())
    await provider.delete_person(person_id=make_person_id(tenant, uuid4()))  # type: ignore[arg-type]
    assert provider._embedder is None
