"""`body` / `body_doc` request contract and service wiring (no database)."""

from typing import Any
from uuid import uuid4

import pytest
from pydantic import ValidationError as PydanticValidationError

from hrms.core.errors.base import ValidationError
from hrms.modules.onboarding.invitation_compose import InvitationValues
from hrms.modules.onboarding.invitation_schemas import (
    InvitationPreviewRequest,
    OnboardingInviteSendRequest,
)
from hrms.modules.onboarding.invitation_service import OnboardingInvitationService

DOC: dict[str, Any] = {
    "type": "doc",
    "content": [
        {"type": "paragraph", "content": [{"type": "text", "text": "Hi {{candidate_name}}"}]},
        {"type": "paragraph", "content": [{"type": "text", "text": "{{onboarding_url}}"}]},
    ],
}
VALUES = InvitationValues({"candidate_name": "Asha", "company_name": "Acme"})
URL = "https://app.example.com/onboarding/T"


def test_preview_requires_exactly_one_representation() -> None:
    assert InvitationPreviewRequest(subject="s", body="b").body_doc is None
    assert InvitationPreviewRequest(subject="s", body_doc=DOC).body is None
    for kwargs in ({}, {"body": "b", "body_doc": DOC}):
        with pytest.raises(PydanticValidationError):
            InvitationPreviewRequest(subject="s", **kwargs)


def test_send_request_is_backward_compatible_and_rejects_ambiguity() -> None:
    assert OnboardingInviteSendRequest().body is None  # absent => built-in default
    assert OnboardingInviteSendRequest(subject="s", body="b").body_doc is None
    assert OnboardingInviteSendRequest(subject="s", body_doc=DOC, send_request_id=uuid4())
    with pytest.raises(PydanticValidationError):
        OnboardingInviteSendRequest(subject="s", body="b", body_doc=DOC)


@pytest.mark.parametrize(
    "field", ["onboarding_url", "invite_url", "token", "html_body", "mobile_url"]
)
def test_client_cannot_supply_link_token_or_html(field: str) -> None:
    for model in (InvitationPreviewRequest, OnboardingInviteSendRequest):
        with pytest.raises(PydanticValidationError):
            model(subject="s", body_doc=DOC, **{field: "x"})  # type: ignore[arg-type]


def _service() -> OnboardingInvitationService:
    return OnboardingInvitationService.__new__(OnboardingInvitationService)


def test_service_render_routes_to_the_matching_renderer() -> None:
    svc = _service()
    rich = svc.render(
        subject="S", body=None, body_doc=DOC, values=VALUES, onboarding_url=URL, mobile_url=None
    )
    plain = svc.render(
        subject="S",
        body="Hi {{candidate_name}}\n\n{{onboarding_url}}",
        values=VALUES,
        onboarding_url=URL,
        mobile_url=None,
    )
    assert rich.html_body == plain.html_body and rich.text_body == plain.text_body


def test_service_render_rejects_both_and_validates_documents() -> None:
    svc = _service()
    with pytest.raises(ValueError):
        svc.render(
            subject="S", body="x", body_doc=DOC, values=VALUES, onboarding_url=URL, mobile_url=None
        )
    with pytest.raises(ValidationError):
        svc.render(
            subject="S",
            body=None,
            body_doc={"type": "doc"},
            values=VALUES,
            onboarding_url=URL,
            mobile_url=None,
        )


def test_redacted_history_copy_never_contains_the_link() -> None:
    text = _service().redacted_text(subject="S", body=None, body_doc=DOC, values=VALUES)
    assert (
        "not retained" in text and "redacted.invalid" not in text and "app.example.com" not in text
    )
