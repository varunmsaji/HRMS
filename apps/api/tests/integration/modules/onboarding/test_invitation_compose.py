# ruff: noqa: E501 - long literals in test data
"""HR-editable onboarding invitation: compose, preview (no side effects), send, history, tenancy.

Dispatch is `none` so the queued message stays in the outbox with its body and the test drives
delivery explicitly with a synthetic sender. Nothing contacts a mail server.
"""

import asyncio
from typing import Any
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import text

from hrms.core.config.settings import get_settings
from hrms.core.db.session import get_session_factory
from hrms.modules.onboarding import email_outbox as ob
from hrms.modules.onboarding.email_sender import EmailDeliveryError

from .test_onboarding_case import (
    _cleanup_scoped_users,
    _create_permission_scoped_user,
    _register_tenant,
)
from .test_onboarding_invite import (
    _create_case,
    _teardown_with_tokens,
    _token_from_invite_url,
)

pytestmark = [pytest.mark.asyncio, pytest.mark.usefixtures("seeded_plan_catalogue")]

GOOD_BODY = "Hello {{candidate_first_name}},\n\nJoin {{company_name}} on {{joining_date}}.\n\n{{onboarding_url}}"


@pytest.fixture(autouse=True)
async def _no_dispatch(monkeypatch: pytest.MonkeyPatch) -> Any:
    monkeypatch.setenv("EMAIL_OUTBOX_DISPATCH", "none")
    get_settings.cache_clear()
    yield


class Recorder:
    def __init__(self, exc: BaseException | None = None) -> None:
        self.exc = exc
        self.sent: list[str] = []

    async def send(self, *, to: str, subject: str, html_body: str, text_body: str) -> None:
        if self.exc:
            raise self.exc
        self.sent.append(to)


async def _q(company_id: UUID, sql: str, **p: Any) -> list[Any]:
    from hrms.core.db.session import set_rls_company_id

    async with get_session_factory()() as s:
        await set_rls_company_id(s, str(company_id))
        return list((await s.execute(text(sql), {"cid": str(company_id), **p})).all())


async def _counts(company_id: UUID, case_id: str) -> dict[str, int]:
    out = {}
    for name, sql in {
        "outbox": "SELECT count(*) FROM email_outbox WHERE company_id=:cid",
        "message": "SELECT count(*) FROM onboarding_message WHERE onboarding_case_id=:k",
        "token": "SELECT count(*) FROM onboarding_token WHERE onboarding_case_id=:k",
    }.items():
        async with get_session_factory()() as s:
            from hrms.core.db.session import set_rls_company_id

            await set_rls_company_id(s, str(company_id))
            out[name] = (
                await s.execute(text(sql), {"cid": str(company_id), "k": case_id})
            ).scalar_one()
    return out


async def _outbox_for(company_id: UUID) -> list[Any]:
    return await _q(
        company_id,
        "SELECT id, message_id, subject, text_body, html_body, status FROM email_outbox "
        "WHERE company_id=:cid ORDER BY created_at",
    )


def _url(case_id: str, tail: str) -> str:
    return f"/v1/onboarding-cases/{case_id}/{tail}"


async def _send(client: AsyncClient, headers: dict[str, str], case_id: str, **body: Any) -> Any:
    return await client.post(_url(case_id, "send-invite"), headers=headers, json=body or None)


# ------------------------------------------------------------------------- compose / preview


async def test_compose_returns_defaults_recipient_and_placeholders(client: AsyncClient) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        case = await _create_case(client, headers)
        r = await client.get(_url(case["id"], "invitation/compose"), headers=headers)
        assert r.status_code == 200, r.text
        d = r.json()["data"]
        assert d["recipient_email"] == case["personal_email"]
        assert d["invitable"] is True and d["has_active_link"] is False
        assert "{{company_name}}" in d["default_subject"]
        keys = {p["key"] for p in d["placeholders"]}
        assert {"candidate_name", "company_name", "joining_date", "onboarding_url"} <= keys
        assert d["designation"] is None  # optional fields are not assumed
    finally:
        await _teardown_with_tokens(company_id=company_id, user_id=user_id)


async def test_preview_has_no_side_effects_and_no_real_credential(client: AsyncClient) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        case = await _create_case(client, headers)
        before = await _counts(company_id, case["id"])
        r = await client.post(
            _url(case["id"], "invitation/preview"),
            headers=headers,
            json={"subject": "Welcome to {{company_name}}", "body": GOOD_BODY},
        )
        assert r.status_code == 200, r.text
        d = r.json()["data"]
        assert "{{" not in d["subject"] + d["text_body"] + d["html_body"]
        assert "Asha" in d["text_body"] and "15 January 2027" in d["text_body"]
        assert "PREVIEW-LINK-NOT-ACTIVE" in d["text_body"] and d["link_is_placeholder"] is True
        assert (
            await _counts(company_id, case["id"])
            == before
            == {"outbox": 0, "message": 0, "token": 0}
        )
        refreshed = await client.get(f"/v1/onboarding-cases/{case['id']}", headers=headers)
        assert refreshed.json()["data"]["status"] == "DRAFT"
    finally:
        await _teardown_with_tokens(company_id=company_id, user_id=user_id)


@pytest.mark.parametrize(
    ("subject", "body"),
    [
        ("Hi {{nope}}", GOOD_BODY),
        ("", GOOD_BODY),
        ("Hi\r\nBcc: x@y.test", GOOD_BODY),
        ("Hi", "no link here"),
        ("Hi", "{{company_name}} {{onboarding_url}} {{broken"),
        ("Hi {{designation}}", GOOD_BODY),  # optional value missing in subject
    ],
)
async def test_preview_rejects_unsendable_content(
    client: AsyncClient, subject: str, body: str
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        case = await _create_case(client, headers)
        r = await client.post(
            _url(case["id"], "invitation/preview"),
            headers=headers,
            json={"subject": subject, "body": body},
        )
        assert r.status_code == 422, r.text
        assert r.json()["error"]["details"][0]["code"] == "INVITATION_TEMPLATE_INVALID"
    finally:
        await _teardown_with_tokens(company_id=company_id, user_id=user_id)


async def test_preview_omits_optional_paragraph_and_escapes_markup(client: AsyncClient) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        case = await _create_case(client, headers, candidate_first_name="<i>Asha</i>")
        r = await client.post(
            _url(case["id"], "invitation/preview"),
            headers=headers,
            json={
                "subject": "S",
                "body": "Hi {{candidate_first_name}} <script>x</script>\n\nRole: {{designation}}\n\n{{onboarding_url}}",
            },
        )
        d = r.json()["data"]
        assert "Role:" not in d["text_body"]
        assert "<script" not in d["html_body"] and "<i>" not in d["html_body"]
        assert "&lt;i&gt;Asha&lt;/i&gt;" in d["html_body"]
    finally:
        await _teardown_with_tokens(company_id=company_id, user_id=user_id)


# --------------------------------------------------------------------------------- sending


async def test_custom_send_queues_exactly_what_was_approved_and_keeps_safe_history(
    client: AsyncClient,
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        case = await _create_case(client, headers)
        subject = "Welcome aboard {{candidate_first_name}}"
        preview = (
            await client.post(
                _url(case["id"], "invitation/preview"),
                headers=headers,
                json={"subject": subject, "body": GOOD_BODY},
            )
        ).json()["data"]
        r = await _send(client, headers, case["id"], subject=subject, body=GOOD_BODY)
        assert r.status_code == 200, r.text
        d = r.json()["data"]
        raw = _token_from_invite_url(d["invite_url"])
        assert d["email_queued"] is True and d["message_status"] == "QUEUED"

        (row,) = await _outbox_for(company_id)
        assert row.subject == preview["subject"] == "Welcome aboard Asha"
        # same rendering as the approved preview, only the link differs
        assert row.text_body == preview["text_body"].replace("PREVIEW-LINK-NOT-ACTIVE", raw)
        assert d["invite_url"] in row.text_body and d["invite_url"] in row.html_body

        msgs = (await client.get(_url(case["id"], "messages"), headers=headers)).json()["data"]
        assert len(msgs) == 1 and msgs[0]["status"] == "QUEUED"
        assert (
            msgs[0]["subject"] == row.subject
            and msgs[0]["recipient_email"] == case["personal_email"]
        )
        assert msgs[0]["created_by_user_id"] == str(user_id)
        assert "not retained" in msgs[0]["body_text"] and raw not in msgs[0]["body_text"]

        # the raw token is nowhere durable: history row, audit payload
        stored = await _q(company_id, "SELECT subject, rendered_text_body FROM onboarding_message")
        audit = await _q(
            company_id,
            "SELECT after_json::text FROM audit_log WHERE action='ONBOARDING_INVITE_SENT'",
        )
        assert not any(raw in str(c) for r_ in stored + audit for c in r_)
        assert audit and str(case["id"]) in audit[0][0] and "message_id" in audit[0][0]
    finally:
        await _teardown_with_tokens(company_id=company_id, user_id=user_id)


async def test_default_send_without_body_still_works(client: AsyncClient) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        case = await _create_case(client, headers)
        r = await client.post(_url(case["id"], "send-invite"), headers=headers)
        assert r.status_code == 200 and r.json()["data"]["case"]["status"] == "INVITED"
        (row,) = await _outbox_for(company_id)
        assert "{{" not in row.subject + row.text_body and row.subject.startswith("Welcome to")
    finally:
        await _teardown_with_tokens(company_id=company_id, user_id=user_id)


async def test_unsendable_content_mints_no_token_and_queues_nothing(client: AsyncClient) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        case = await _create_case(client, headers)
        r = await _send(client, headers, case["id"], subject="Hi {{nope}}", body=GOOD_BODY)
        assert r.status_code == 422
        assert await _counts(company_id, case["id"]) == {"outbox": 0, "message": 0, "token": 0}
        got = await client.get(f"/v1/onboarding-cases/{case['id']}", headers=headers)
        assert got.json()["data"]["status"] == "DRAFT"
    finally:
        await _teardown_with_tokens(company_id=company_id, user_id=user_id)


async def test_failure_after_queueing_rolls_everything_back(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from hrms.core.audit.service import AuditService

    async def boom(*a: Any, **k: Any) -> None:
        raise RuntimeError("audit down")

    headers, company_id, user_id = await _register_tenant(client)
    try:
        case = await _create_case(client, headers)
        monkeypatch.setattr(AuditService, "record", boom)
        try:
            r = await _send(client, headers, case["id"])
            assert r.status_code >= 500
        except RuntimeError:
            pass
        monkeypatch.undo()
        assert await _counts(company_id, case["id"]) == {"outbox": 0, "message": 0, "token": 0}
    finally:
        await _teardown_with_tokens(company_id=company_id, user_id=user_id)


async def test_provider_acceptance_is_reported_as_accepted_not_delivered(
    client: AsyncClient,
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        case = await _create_case(client, headers)
        await _send(client, headers, case["id"])
        (row,) = await _outbox_for(company_id)
        sender = Recorder()
        assert await ob.deliver_message(row.id, sender=sender) == "sent"
        (m,) = (await client.get(_url(case["id"], "messages"), headers=headers)).json()["data"]
        assert m["status"] == "PROVIDER_ACCEPTED" and m["provider_accepted_at"]
        assert "DELIVERED" not in m["status"]
        assert m["subject"] and m["body_text"]  # history survives the outbox blanking its body
        (blank,) = await _outbox_for(company_id)
        assert blank.text_body is None
    finally:
        await _teardown_with_tokens(company_id=company_id, user_id=user_id)


async def test_transient_failure_retries_same_message_and_token_permanent_fails(
    client: AsyncClient,
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        case = await _create_case(client, headers)
        sent = (await _send(client, headers, case["id"])).json()["data"]
        token = _token_from_invite_url(sent["invite_url"])
        (row,) = await _outbox_for(company_id)

        transient = EmailDeliveryError("t", "network", True, "not_sent", None, error_type=OSError())
        assert await ob.deliver_message(row.id, sender=Recorder(transient)) == "retry"
        (m,) = (await client.get(_url(case["id"], "messages"), headers=headers)).json()["data"]
        assert m["status"] == "RETRYING" and m["attempts"] == 1 and m["failure_class"]
        # retrying re-sends the SAME stored message: same outbox row/body, same live token
        (still,) = await _outbox_for(company_id)
        assert still.message_id == row.message_id and still.text_body == row.text_body
        assert (await client.get(f"/v1/public/onboarding/{token}")).status_code == 200

        await _q(company_id, "UPDATE email_outbox SET status='PENDING'") if False else None
        async with get_session_factory()() as s:
            await s.execute(
                text(
                    "UPDATE email_outbox SET next_attempt_at = now() - interval '1 minute' WHERE id=:i"
                ),
                {"i": row.id},
            )
            await s.commit()
        permanent = EmailDeliveryError(
            "t", "rejected", False, "not_sent", 550, error_type=ValueError()
        )
        assert await ob.deliver_message(row.id, sender=Recorder(permanent)) == "failed"
        (m,) = (await client.get(_url(case["id"], "messages"), headers=headers)).json()["data"]
        assert m["status"] == "FAILED" and m["failed_at"]
        assert "550" not in str(m) and "rejected" not in m["subject"]
    finally:
        await _teardown_with_tokens(company_id=company_id, user_id=user_id)


async def test_intentional_resend_rotates_token_and_keeps_both_history_rows(
    client: AsyncClient,
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        case = await _create_case(client, headers)
        a = (await _send(client, headers, case["id"])).json()["data"]
        b = (await _send(client, headers, case["id"])).json()["data"]
        assert (
            await client.get(f"/v1/public/onboarding/{_token_from_invite_url(a['invite_url'])}")
        ).status_code == 404
        assert (
            await client.get(f"/v1/public/onboarding/{_token_from_invite_url(b['invite_url'])}")
        ).status_code == 200
        assert (
            len((await client.get(_url(case["id"], "messages"), headers=headers)).json()["data"])
            == 2
        )
        c = (await client.get(_url(case["id"], "invitation/compose"), headers=headers)).json()[
            "data"
        ]
        assert c["has_active_link"] is True  # the UI warns that sending again revokes this link
    finally:
        await _teardown_with_tokens(company_id=company_id, user_id=user_id)


async def test_duplicate_request_id_returns_first_result_without_new_token(
    client: AsyncClient,
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        case = await _create_case(client, headers)
        rid = str(uuid4())
        first = (await _send(client, headers, case["id"], send_request_id=rid)).json()["data"]
        second = (await _send(client, headers, case["id"], send_request_id=rid)).json()["data"]
        assert second["replayed"] is True and second["invite_url"] is None
        assert second["message_id"] == first["message_id"]
        assert (
            await client.get(f"/v1/public/onboarding/{_token_from_invite_url(first['invite_url'])}")
        ).status_code == 200
        assert await _counts(company_id, case["id"]) == {"outbox": 1, "message": 1, "token": 1}
    finally:
        await _teardown_with_tokens(company_id=company_id, user_id=user_id)


async def test_concurrent_sends_do_not_conflict(client: AsyncClient) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        case = await _create_case(client, headers)
        rid = str(uuid4())
        same = await asyncio.gather(
            *[_send(client, headers, case["id"], send_request_id=rid) for _ in range(4)]
        )
        assert all(r.status_code == 200 for r in same)
        assert await _counts(company_id, case["id"]) == {"outbox": 1, "message": 1, "token": 1}

        many = await asyncio.gather(*[_send(client, headers, case["id"]) for _ in range(3)])
        assert all(r.status_code == 200 for r in many)
        live = await _q(
            company_id,
            "SELECT count(*) FROM onboarding_token WHERE onboarding_case_id=:k AND revoked_at IS NULL",
            k=UUID(case["id"]),
        )
        assert live[0][0] == 1  # exactly one live link survives
    finally:
        await _teardown_with_tokens(company_id=company_id, user_id=user_id)


# ------------------------------------------------------------------- permissions / tenancy


async def test_permissions_are_enforced_on_every_new_route(client: AsyncClient) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        case = await _create_case(client, headers)
        none_h, _ = await _create_permission_scoped_user(company_id=company_id, permission_codes=[])
        view_h, _ = await _create_permission_scoped_user(
            company_id=company_id, permission_codes=["ONBOARDING.VIEW"]
        )
        pv = {"subject": "s", "body": GOOD_BODY}
        for h in (none_h, view_h):
            assert (
                await client.get(_url(case["id"], "invitation/compose"), headers=h)
            ).status_code == 403
            assert (
                await client.post(_url(case["id"], "invitation/preview"), headers=h, json=pv)
            ).status_code == 403
            assert (await _send(client, h, case["id"])).status_code == 403
        assert (await client.get(_url(case["id"], "messages"), headers=none_h)).status_code == 403
        assert (await client.get(_url(case["id"], "messages"), headers=view_h)).status_code == 200
        assert await _counts(company_id, case["id"]) == {"outbox": 0, "message": 0, "token": 0}
    finally:
        await _teardown_with_tokens(company_id=company_id, user_id=user_id)
        await _cleanup_scoped_users()


async def test_other_tenants_cannot_use_or_read_a_case(client: AsyncClient) -> None:
    ha, ca, ua = await _register_tenant(client)
    hb, cb, ub = await _register_tenant(client)
    try:
        case = await _create_case(client, ha)
        await _send(client, ha, case["id"])
        pv = {"subject": "s", "body": GOOD_BODY}
        assert (
            await client.get(_url(case["id"], "invitation/compose"), headers=hb)
        ).status_code == 404
        assert (
            await client.post(_url(case["id"], "invitation/preview"), headers=hb, json=pv)
        ).status_code == 404
        assert (await _send(client, hb, case["id"])).status_code == 404
        assert (await client.get(_url(case["id"], "messages"), headers=hb)).status_code == 404
        # B naming A's company id does not widen access
        forged = {"Authorization": hb["Authorization"], "X-Company-Id": str(ca)}
        assert (await client.get(_url(case["id"], "messages"), headers=forged)).status_code in (
            401,
            403,
            404,
        )
        # A client-supplied company id in the body is rejected outright
        r = await _send(client, ha, case["id"], company_id=str(cb))
        assert r.status_code == 422
        # A's data is untouched: one message, one live token
        assert len((await client.get(_url(case["id"], "messages"), headers=ha)).json()["data"]) == 1
    finally:
        await _teardown_with_tokens(company_id=ca, user_id=ua)
        await _teardown_with_tokens(company_id=cb, user_id=ub)


async def test_tenant_admin_cannot_reach_platform_email_log(client: AsyncClient) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        r = await client.get("/v1/platform/emails", headers=headers)
        assert r.status_code in (401, 403)
    finally:
        await _teardown_with_tokens(company_id=company_id, user_id=user_id)


async def test_rls_hides_messages_from_other_company_context(client: AsyncClient) -> None:
    """Checked as the real runtime role (`hrms_app`); the suite's default `hrms` role bypasses RLS."""
    import os
    from urllib.parse import urlsplit

    from sqlalchemy.ext.asyncio import create_async_engine

    ha, ca, ua = await _register_tenant(client)
    hb, cb, ub = await _register_tenant(client)
    engine = None
    try:
        case = await _create_case(client, ha)
        await _send(client, ha, case["id"])
        parts = urlsplit(os.environ["DATABASE_URL"])
        url = f"postgresql+asyncpg://hrms_app:hrms_app_dev_password@{parts.netloc.rsplit('@', 1)[-1]}{parts.path}"
        engine = create_async_engine(url)

        async def visible(company: UUID) -> int:
            async with engine.connect() as conn:
                await conn.execute(
                    text("SELECT set_config('app.company_id', :c, false)"), {"c": str(company)}
                )
                return int(
                    (
                        await conn.execute(text("SELECT count(*) FROM onboarding_message"))
                    ).scalar_one()
                )

        assert await visible(ca) == 1
        assert await visible(cb) == 0
    finally:
        if engine is not None:
            await engine.dispose()
        await _teardown_with_tokens(company_id=ca, user_id=ua)
        await _teardown_with_tokens(company_id=cb, user_id=ub)
