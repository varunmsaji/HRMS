"""API audit H-6 - face attendance must stay off until deliberately configured."""

import pytest
from pydantic import ValidationError

from hrms.core.config.settings import Settings


def test_face_features_default_to_disabled() -> None:
    s = Settings(_env_file=None)
    assert s.face_verification_provider == "disabled"
    assert s.face_liveness_engine == "disabled"


def test_enabling_the_provider_without_credentials_refuses_to_start() -> None:
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            face_verification_provider="facepp",
            facepp_api_key="",
            facepp_api_secret="",
        )


def test_enabling_liveness_without_model_assets_refuses_to_start() -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, face_liveness_engine="minifasnet", face_liveness_model_dir="")


def test_threshold_pair_that_could_label_one_frame_both_live_and_spoof_is_rejected() -> None:
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None, face_liveness_live_threshold=0.6, face_liveness_spoof_threshold=0.4
        )
