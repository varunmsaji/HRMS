"""Application start-up (the real `lifespan`) under each face-provider configuration, with every
outbound socket connection and URL fetch made fatal: models are verified locally at boot and are
never downloaded at start-up. Real-asset cases skip when the assets are not provisioned."""

import shutil
import socket
import urllib.request
from pathlib import Path

import pytest
from fastapi import FastAPI
from pydantic import ValidationError

from hrms.app import lifespan
from hrms.core.config.settings import get_settings
from hrms.modules.attendance import face_verification
from hrms.modules.attendance.opensource_face import assets
from hrms.modules.attendance.opensource_face.embedding_service import EmbeddingUnavailableError

_ASSET_DIR = Path(__file__).resolve().parents[4] / "models/face/opensource-v1"
_HAVE_ASSETS = all((_ASSET_DIR / n).is_file() for n in assets.ASSETS)
_BASE = {
    "ENVIRONMENT": "development",
    "FACE_VERIFICATION_PROVIDER": "disabled",
    "FACEPP_API_KEY": "",
    "FACEPP_API_SECRET": "",
    "FACE_OS_ENABLED": "false",
    "FACE_OS_MODEL_DIR": "",
    "FACE_LIVENESS_ENGINE": "disabled",
}


@pytest.fixture(autouse=True)
def _isolated(monkeypatch: pytest.MonkeyPatch) -> None:
    def no_net(*a: object, **k: object) -> None:
        raise AssertionError("network used during start-up")

    monkeypatch.setattr(socket.socket, "connect", no_net)
    monkeypatch.setattr(urllib.request, "urlopen", no_net)
    for key, value in _BASE.items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()
    face_verification._shared_opensource.clear()
    face_verification._shared_providers.clear()
    yield
    get_settings.cache_clear()
    face_verification._shared_opensource.clear()
    face_verification._shared_providers.clear()


async def _boot() -> str | None:
    async with lifespan(FastAPI()):
        provider = face_verification.get_face_verification_provider(get_settings())
        return getattr(provider, "provider_name", None)


def _env(monkeypatch: pytest.MonkeyPatch, **values: str) -> None:
    for key, value in values.items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()


async def test_default_and_facepp_boot_without_open_source_assets(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    assert await _boot() is None  # default: face verification disabled
    _env(
        monkeypatch,
        FACE_VERIFICATION_PROVIDER="facepp",
        FACEPP_API_KEY="k",
        FACEPP_API_SECRET="s",
    )
    assert await _boot() == "FACEPP"


async def test_open_source_needs_the_second_key_and_a_model_dir(monkeypatch, tmp_path) -> None:  # type: ignore[no-untyped-def]
    _env(monkeypatch, FACE_VERIFICATION_PROVIDER="opensource", FACE_OS_MODEL_DIR=str(tmp_path))
    with pytest.raises(ValidationError, match="face_os_enabled"):
        await _boot()
    _env(monkeypatch, FACE_OS_ENABLED="true", FACE_OS_MODEL_DIR="")
    with pytest.raises(ValidationError, match="face_os_model_dir"):
        await _boot()
    _env(monkeypatch, FACE_OS_MODEL_DIR=str(tmp_path), FACE_OS_MATCH_THRESHOLD="1.5")
    with pytest.raises(ValidationError):
        await _boot()


async def test_unknown_provider_value_is_rejected(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _env(monkeypatch, FACE_VERIFICATION_PROVIDER="insightface")
    with pytest.raises(ValidationError):
        await _boot()


@pytest.mark.parametrize("path", ["empty", "nonexistent"])
async def test_missing_assets_refuse_to_boot(monkeypatch, tmp_path, path) -> None:  # type: ignore[no-untyped-def]
    pytest.importorskip("cv2")
    directory = tmp_path if path == "empty" else tmp_path / "nope"
    _env(
        monkeypatch,
        FACE_VERIFICATION_PROVIDER="opensource",
        FACE_OS_ENABLED="true",
        FACE_OS_MODEL_DIR=str(directory),
    )
    with pytest.raises(EmbeddingUnavailableError, match="missing"):
        await _boot()


@pytest.mark.skipif(not _HAVE_ASSETS, reason="assets not provisioned")
async def test_valid_then_tampered_assets(monkeypatch, tmp_path) -> None:  # type: ignore[no-untyped-def]
    pytest.importorskip("cv2")
    for name in assets.ASSETS:
        shutil.copy(_ASSET_DIR / name, tmp_path / name)
    _env(
        monkeypatch,
        FACE_VERIFICATION_PROVIDER="opensource",
        FACE_OS_ENABLED="true",
        FACE_OS_MODEL_DIR=str(tmp_path),
    )
    assert await _boot() == "OPENSOURCE"

    face_verification._shared_opensource.clear()
    target = tmp_path / assets.RECOGNIZER_FILE
    data = bytearray(target.read_bytes())
    data[1000] ^= 0xFF
    target.write_bytes(bytes(data))
    with pytest.raises(EmbeddingUnavailableError, match="failed verification"):
        await _boot()

    # Face++ selected: the (tampered) open-source assets are never read and there is no fallback.
    _env(
        monkeypatch,
        FACE_VERIFICATION_PROVIDER="facepp",
        FACEPP_API_KEY="k",
        FACEPP_API_SECRET="s",
    )
    assert await _boot() == "FACEPP"
