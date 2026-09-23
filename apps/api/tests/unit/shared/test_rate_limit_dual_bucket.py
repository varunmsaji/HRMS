"""SEC-02 (PLATFORM_READINESS_SECURITY_AUDIT_2026-09-17) — `rate_limit_by_ip_and_email`, the
dual-bucket dependency `/auth/login` uses. Behavioural tests against the real Redis instance
(same convention as `tests/integration/modules/organisation/test_registration_rate_limit.py`'s
`test_rate_limit_dependency_blocks_after_threshold`), not a mock — the sliding-window counters
are the thing under test.
"""

import asyncio
import json

import pytest
import redis.asyncio as redis
from fastapi import Request

from hrms.core.config.settings import get_settings
from hrms.shared.rate_limit import RateLimitExceededError, rate_limit, rate_limit_by_ip_and_email


def _login_request(client_ip: str, email: str | None) -> Request:
    body = json.dumps({"email": email} if email else {}).encode()

    async def receive() -> dict:
        return {"type": "http.request", "body": body, "more_body": False}

    scope = {"type": "http", "client": (client_ip, 555), "headers": []}
    return Request(scope, receive=receive)


async def _clear(client: redis.Redis, *keys: str) -> None:
    for key in keys:
        await client.delete(key)


@pytest.mark.asyncio
async def test_ip_bucket_blocks_one_ip_spraying_many_accounts() -> None:
    """A single attacking IP trying many different (nonexistent) emails must still trip the
    IP-keyed bucket even though no individual email bucket ever gets close to its own limit."""
    dep = rate_limit_by_ip_and_email("test-dual-ip-spray", limit=3, window_seconds=60)
    client = redis.from_url(get_settings().redis_url, decode_responses=True)
    emails = [f"victim-{i}@example.com" for i in range(4)]
    try:
        for email in emails[:3]:
            await dep(_login_request("9.9.9.1", email))
        with pytest.raises(RateLimitExceededError):
            await dep(_login_request("9.9.9.1", emails[3]))
    finally:
        await _clear(
            client,
            "ratelimit:test-dual-ip-spray:ip:9.9.9.1",
            *(f"ratelimit:test-dual-ip-spray:email:{e}" for e in emails),
        )
        await client.aclose()


@pytest.mark.asyncio
async def test_email_bucket_blocks_one_account_attacked_from_many_ips() -> None:
    """A distributed attack against one known account — different source IPs each stay well
    under the IP limit, but the shared email bucket must still trip (the anti-DoS case the
    audit calls out explicitly: an IP-only limiter would let this through)."""
    dep = rate_limit_by_ip_and_email("test-dual-email-spray", limit=3, window_seconds=60)
    client = redis.from_url(get_settings().redis_url, decode_responses=True)
    victim_email = "widely-targeted@example.com"
    attacker_ips = [f"9.9.9.{10 + i}" for i in range(4)]
    try:
        for ip in attacker_ips[:3]:
            await dep(_login_request(ip, victim_email))
        with pytest.raises(RateLimitExceededError):
            await dep(_login_request(attacker_ips[3], victim_email))
    finally:
        await _clear(
            client,
            f"ratelimit:test-dual-email-spray:email:{victim_email}",
            *(f"ratelimit:test-dual-email-spray:ip:{ip}" for ip in attacker_ips),
        )
        await client.aclose()


@pytest.mark.asyncio
async def test_different_emails_get_independent_counters_behind_one_shared_ip() -> None:
    """Case E — same client IP, two different accounts. Each email is tracked under its own
    Redis key with its own count (not merged into one "this IP tried N logins" number) — the
    shared IP bucket legitimately keeps accumulating across both accounts too (that's its job,
    not a bug); the blocking behaviour for each dimension individually is already covered by
    the two tests above, so this uses a generous limit and asserts on the underlying counts
    directly rather than on when either bucket trips."""
    dep = rate_limit_by_ip_and_email("test-dual-independent", limit=100, window_seconds=60)
    client = redis.from_url(get_settings().redis_url, decode_responses=True)
    try:
        await dep(_login_request("9.9.9.77", "alice@example.com"))
        await dep(_login_request("9.9.9.77", "alice@example.com"))
        await dep(_login_request("9.9.9.77", "bob@example.com"))

        alice_count = await client.get("ratelimit:test-dual-independent:email:alice@example.com")
        bob_count = await client.get("ratelimit:test-dual-independent:email:bob@example.com")
        ip_count = await client.get("ratelimit:test-dual-independent:ip:9.9.9.77")

        assert alice_count == "2"
        assert bob_count == "1"
        assert ip_count == "3"
    finally:
        await _clear(
            client,
            "ratelimit:test-dual-independent:ip:9.9.9.77",
            "ratelimit:test-dual-independent:email:alice@example.com",
            "ratelimit:test-dual-independent:email:bob@example.com",
        )
        await client.aclose()


@pytest.mark.asyncio
async def test_login_bucket_recovers_after_the_window_expires() -> None:
    dep = rate_limit_by_ip_and_email("test-dual-window", limit=1, window_seconds=1)
    client = redis.from_url(get_settings().redis_url, decode_responses=True)
    try:
        await dep(_login_request("9.9.9.200", "a@example.com"))
        with pytest.raises(RateLimitExceededError):
            await dep(_login_request("9.9.9.200", "b@example.com"))
        await asyncio.sleep(1.2)
        await dep(_login_request("9.9.9.200", "c@example.com"))  # window reset — succeeds
    finally:
        await _clear(
            client,
            "ratelimit:test-dual-window:ip:9.9.9.200",
            "ratelimit:test-dual-window:email:a@example.com",
            "ratelimit:test-dual-window:email:b@example.com",
            "ratelimit:test-dual-window:email:c@example.com",
        )
        await client.aclose()


@pytest.mark.asyncio
async def test_missing_or_unparsable_body_falls_back_to_ip_only_protection() -> None:
    """The refresh endpoint's own limiter (`rate_limit`, not this dual-bucket one) has no email
    to key on at all — but even this dual-bucket dependency must not error out if it somehow
    received a body without an `email` field; it degrades to a shared 'unknown' identity bucket
    rather than raising."""
    dep = rate_limit_by_ip_and_email("test-dual-no-email", limit=5, window_seconds=60)
    client = redis.from_url(get_settings().redis_url, decode_responses=True)

    async def receive() -> dict:
        return {"type": "http.request", "body": b"not-json", "more_body": False}

    scope = {"type": "http", "client": ("9.9.9.201", 1), "headers": []}
    request = Request(scope, receive=receive)
    try:
        await dep(request)  # must not raise despite the unparsable body
    finally:
        await _clear(
            client,
            "ratelimit:test-dual-no-email:ip:9.9.9.201",
            "ratelimit:test-dual-no-email:email:unknown",
        )
        await client.aclose()


@pytest.mark.asyncio
async def test_plain_rate_limit_still_recovers_after_window_expires() -> None:
    """Companion to the existing `test_rate_limit_dependency_blocks_after_threshold` — proves
    the plain (IP-only) `rate_limit` used for `/auth/token/refresh` also recovers once its
    window elapses, not just that it blocks."""
    dep = rate_limit("test-refresh-window", limit=1, window_seconds=1)
    client = redis.from_url(get_settings().redis_url, decode_responses=True)
    scope = {"type": "http", "client": ("9.9.9.202", 1), "headers": []}
    request = Request(scope)
    try:
        await dep(request)
        with pytest.raises(RateLimitExceededError):
            await dep(request)
        await asyncio.sleep(1.2)
        await dep(request)
    finally:
        await client.delete("ratelimit:test-refresh-window:9.9.9.202")
        await client.aclose()
