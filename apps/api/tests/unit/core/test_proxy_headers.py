"""OPS-02 (PLATFORM_READINESS_SECURITY_AUDIT_2026-09-17) — `hrms.app.create_app` wires
`uvicorn.middleware.proxy_headers.ProxyHeadersMiddleware` with `trusted_hosts=settings.
trusted_proxy_hosts` as the outermost middleware. These tests drive that exact middleware
directly against raw ASGI scopes: the framework's own trusted-proxy implementation (reversed
`X-Forwarded-For` walk, stopping at the first host outside the trusted set) rather than a
custom parser, so no home-grown IP-spoofing bug can creep in here.
"""

from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from hrms.core.config.settings import Settings


async def _resolved_client(
    trusted_hosts: list[str], peer_ip: str, forwarded_for: str | None
) -> tuple[str, int] | None:
    captured: dict[str, object] = {}

    async def inner_app(scope: dict, receive: object, send: object) -> None:
        captured["client"] = scope.get("client")

    middleware = ProxyHeadersMiddleware(inner_app, trusted_hosts=trusted_hosts)

    headers = []
    if forwarded_for is not None:
        headers.append((b"x-forwarded-for", forwarded_for.encode()))
    scope = {"type": "http", "client": (peer_ip, 12345), "headers": headers}

    async def receive() -> dict:
        return {"type": "http.request"}

    async def send(message: dict) -> None:
        return None

    await middleware(scope, receive, send)
    return captured["client"]  # type: ignore[return-value]


# Case A — direct, untrusted connection: a spoofed header must never override the socket peer.
async def test_direct_untrusted_request_ignores_spoofed_forwarded_for() -> None:
    client = await _resolved_client([], "203.0.113.9", "10.10.10.10")
    assert client is not None
    assert client[0] == "203.0.113.9"


# Case B — trusted reverse proxy: the forwarded client IP is used.
async def test_trusted_proxy_uses_the_forwarded_client_ip() -> None:
    client = await _resolved_client(["10.0.0.5"], "10.0.0.5", "198.51.100.7")
    assert client is not None
    assert client[0] == "198.51.100.7"


# Case C — untrusted proxy: header present but the immediate peer isn't in the trusted list.
async def test_untrusted_proxy_header_is_ignored() -> None:
    client = await _resolved_client(["10.0.0.5"], "10.0.0.99", "198.51.100.7")
    assert client is not None
    assert client[0] == "10.0.0.99"


# Case D — two users behind the same trusted proxy resolve to distinct client IPs.
async def test_two_users_behind_the_same_trusted_proxy_get_distinct_ips() -> None:
    client_one = await _resolved_client(["10.0.0.5"], "10.0.0.5", "198.51.100.1")
    client_two = await _resolved_client(["10.0.0.5"], "10.0.0.5", "198.51.100.2")
    assert client_one is not None and client_two is not None
    assert client_one[0] == "198.51.100.1"
    assert client_two[0] == "198.51.100.2"
    assert client_one[0] != client_two[0]


async def test_multi_hop_chain_resolves_to_the_first_untrusted_hop() -> None:
    """Two trusted proxies in front of the app; neither "take the first" nor "take the last"
    comma-separated entry would be correct here — the real client is the first entry that
    is *not* itself a trusted hop, found by walking the header in reverse."""
    client = await _resolved_client(
        ["10.0.0.5", "10.0.0.6"],
        peer_ip="10.0.0.5",
        forwarded_for="198.51.100.42, 10.0.0.6",
    )
    assert client is not None
    assert client[0] == "198.51.100.42"


async def test_trusted_proxy_hosts_supports_cidr_networks() -> None:
    client = await _resolved_client(["10.0.0.0/24"], "10.0.0.42", "198.51.100.7")
    assert client is not None
    assert client[0] == "198.51.100.7"


async def test_empty_trusted_hosts_never_trusts_any_peer() -> None:
    """The `Settings.trusted_proxy_hosts` default — the safe-by-default posture."""
    settings = Settings(environment="development")
    client = await _resolved_client(list(settings.trusted_proxy_hosts), "10.0.0.5", "198.51.100.7")
    assert client is not None
    assert client[0] == "10.0.0.5"
