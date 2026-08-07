# Document 10 — Authentication Architecture

**Version:** 2.0 — new document. Authentication was previously scattered across Document 05 §2
(endpoint list) and Document 10 v1.0 §3.2 (a handful of security requirements). It is elevated to
its own document because the auth model — multi-company sessions, JWT + refresh rotation, MFA,
SAML/OIDC — is complex enough, and security-critical enough, to need a single authoritative
specification. The auth **model** (what a session means, multi-company switching, token lifetimes)
is entirely unchanged from v1.0; this document adds the FastAPI/Python implementation detail that
did not previously exist.

---

## 1. Token Model

| Token | Lifetime | Storage | Contains |
|---|---|---|---|
| **Access token** (JWT) | 15 minutes | Client memory (web), Keychain/Keystore (mobile) | `sub` (user_id), `company_id` (active tenant), `employee_id` (nullable), `session_id`, `iat`, `exp` — **no roles or permissions embedded**; those are resolved server-side per request from the current `role`/`user_role` tables (via the Redis-cached lookup, Document 03 §6), not trusted from an old token, so a permission change takes effect on the next request rather than waiting for token expiry |
| **Refresh token** | 30 days, rotating | HttpOnly, Secure, SameSite=Strict cookie (web); encrypted local storage (mobile, identified by `X-Client-Type: mobile`) | Opaque random token; the server stores only its hash plus a `token_family_id` |

**Why the access token carries no roles/permissions:** embedding permissions in the JWT was
considered and rejected (as in v1.0). Permissions change more often than a 15-minute token would
reflect (a role revoked mid-session must take effect immediately for anything security-sensitive —
Document 19 §7 "Deactivated user" rule: sessions revoked within 60 seconds), and a stale-permission
JWT is a worse failure mode than one extra Redis lookup per request.

### 1.1 Refresh Token Rotation & Reuse Detection

Every refresh exchanges the current refresh token for a new one and invalidates the old one
(rotation). All refresh tokens issued from one login share a `token_family_id`. If a refresh token
is presented that has already been rotated away (i.e. it's not the current token in its family),
this is treated as **token theft**: the entire family is revoked, all associated sessions are
killed, and the user is notified (`security.new_device_login`-style alert). This is unchanged from
v1.0 and is implemented via the `session`/`refresh_token` tables (Document 08 §3.5).

```python
# core/auth/service.py
class AuthService:
    async def refresh(self, presented_token: str) -> TokenPair:
        record = await self._repo.get_by_token_hash(hash_token(presented_token))
        if record is None or record.revoked_at is not None:
            # Reuse of an already-rotated or revoked token: theft signal
            if record is not None:
                await self._repo.revoke_family(record.token_family_id, reason="REUSE_DETECTED")
            raise InvalidTokenError()
        ...
```

---

## 2. Password & Credential Handling

- Passwords hashed with **Argon2id** via `argon2-cffi` (was: Argon2id via a Node Argon2 binding —
  same algorithm, same parameters, different library; this is a straight library swap with no
  behavioural change and no need to force a password reset for existing users in a real migration).
- Password policy, lockout (`failed_attempts`, `locked_until`), and reset-token handling are
  unchanged from v1.0 and modelled on the `user` table (Document 08 §3.2).
- OTP-based login (mobile-first flow) generates a 6-digit OTP, stored hashed in Redis with a short
  TTL (5 minutes) and a per-account/per-IP rate limit (Document 09 §1.9), delivered via the SMS/
  WhatsApp integration (Document 22 §3).

---

## 3. Multi-Factor Authentication (MFA)

**Status: designed now, enabled Phase 2+ ("MFA (Future)" per the official stack decision) —** the
data model (`user.mfa_secret_enc`, `user.mfa_enabled`) and the `/auth/mfa/*` endpoints (Document 09
§2) are built in Phase 1 so that turning MFA on later is a feature flag, not a schema migration.

- **TOTP** (RFC 6238) via `pyotp`, secret encrypted at rest with the same column-level encryption
  scheme used for PAN/Aadhaar/bank data (Document 14 §1).
- Enrolment flow: generate secret → show QR code (`pyotp.totp.TOTP(secret).provisioning_uri(...)`)
  → verify one code before enabling → issue backup codes (hashed, single-use).
- MFA challenge sits between password/OTP verification and token issuance: a successful first factor
  returns `mfa_required: true` with a short-lived MFA challenge token instead of access/refresh
  tokens; `/auth/mfa/verify` exchanges a valid TOTP code plus the challenge token for the real token
  pair.
- Enterprise tenants may **require** MFA for specific roles (Company Admin, Payroll roles) via a
  tenant-level policy flag, enforced at login before token issuance — this is a genuine Phase 2/3
  enterprise-sales requirement (separation-of-duties adjacent to Document 19 §3.4) and the schema
  supports it from day one even though the enforcement toggle ships later.

---

## 4. Enterprise SSO: SAML 2.0 and OIDC

Per-tenant configuration (`integration_config`, Document 22 §11), supporting Google Workspace,
Microsoft Entra ID, and Okta (Document 22 §10).

| Protocol | Library | Notes |
|---|---|---|
| SAML 2.0 | `python3-saml` | Handles SP-initiated login, ACS endpoint (`POST /auth/sso/{tenant}/acs`), metadata (`GET /auth/sso/{tenant}/metadata`), signature validation. |
| OIDC | `authlib` | Authorization-code flow with PKCE; used for Google Workspace and Entra ID where OIDC is preferred over SAML. |

**JIT (just-in-time) provisioning:** on first successful SSO login, if no `user`/`user_company`
record exists for the asserted identity, one is created automatically per the tenant's configured
default role and attribute-mapping rules — this must never auto-grant a role above the tenant's
configured default (a privilege-escalation vector if misconfigured, tested explicitly in Document 15
§6).

**SCIM 2.0** (automated user provisioning/deprovisioning) is a Phase 3 enterprise requirement
(Document 22 §10, unchanged) — noted here because it shares the same `user`/`user_company`
provisioning code path as JIT and should be designed with that reuse in mind when built.

---

## 5. Multi-Company Sessions

A `user` may belong to multiple `company` tenants via `user_company` (Document 08 §3.2/§3.3). The
access token's `company_id` claim identifies the **active** tenant for the current session; switching
requires `POST /auth/company/switch`, which issues a fresh token pair scoped to the new company
after re-validating membership — it does not simply patch the `company_id` claim client-side, since
the claim must be trustworthy without a second server round-trip for every subsequent request.

```python
# core/auth/dependencies.py
async def get_current_user(
    token: Annotated[str, Depends(oauth2_scheme)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AuthenticatedUser:
    payload = decode_and_verify(token)  # raises InvalidTokenError on bad signature/expiry
    user = await UserRepository().get(session, payload.sub)
    if user is None or user.status != "ACTIVE":
        raise InvalidTokenError()
    return AuthenticatedUser(user_id=user.id, company_id=payload.company_id,
                              employee_id=payload.employee_id, session_id=payload.session_id)
```

This `AuthenticatedUser` is what `get_tenant_context` (Document 07 §2.1) consumes to validate the
`X-Company-Id` header against the token's `company_id` claim — a mismatch is a `401`, not silently
honouring whichever value the client sent.

---

## 6. Session & Device Management

- `GET /auth/sessions` / `DELETE /auth/sessions/{id}` — unchanged endpoint surface (Document 09 §2).
- Each `session` row records `device_info`, `ip`, and is independently revocable — a user (or an
  admin, or an automated security response) can kill one device's session without logging out
  everywhere.
- `POST /auth/logout/all` revokes every session and every refresh-token family for the user.
- **Deactivation propagation:** when an admin deactivates a user (Document 19 §7), a Celery task
  fires within the 60-second SLA to revoke all active sessions and refresh-token families — this is
  a domain event (`UserDeactivated`) consumed the same way any other cross-module event is
  (Document 07 §7), not a special-cased code path.

---

## 7. Impersonation / Break-Glass

Per Document 19 §7 and Document 14 §4 (unchanged from v1.0): Platform Ops may impersonate a tenant
user for support, subject to: a stated reason (required field, stored), a time limit (max 30
minutes, auto-expiring token), a persistent on-screen banner in the impersonated session, full audit
logging (`audit_log.impersonated_by`, Document 08 §11), and a set of forbidden actions during
impersonation (payroll finalisation, permission changes, data export — enforced the same way any
other permission check is, via `Depends(require_permission(...))` additionally checking
`not is_impersonating` for that specific action list).

---

## 8. Public/Unauthenticated Endpoints

A small, explicitly enumerated set of routes skip the `get_current_user` dependency entirely rather
than being "allowed through" an auth middleware exception list (Document 07 §4 explains why this is
a `Depends`-based, not middleware-based, decision): careers page browsing/apply, offer-response links
(signed token, not a session), candidate preboarding portal (signed token), webhook receivers
(HMAC-signature verified, Document 09 §4), and the health-check endpoint. Each of these has its own,
narrower trust mechanism (signed URL, HMAC, or genuinely public read) documented at its own router —
there is no generic "public" flag that could be misapplied to a route that shouldn't have it.

---

## 9. What Changed vs. What Didn't (migration summary for this document)

| Aspect | v1.0 (NestJS) | v2.0 (FastAPI) | Changed? |
|---|---|---|---|
| Token model, lifetimes, rotation, theft detection | As above | As above | **No** — pure model, unchanged |
| Multi-company session switching | As above | As above | **No** |
| MFA design (TOTP, backup codes, tenant-enforced) | As above | As above | **No** |
| SSO protocols supported | SAML 2.0, OIDC | SAML 2.0, OIDC | **No** |
| Password hashing algorithm | Argon2id | Argon2id | **No** — algorithm unchanged, library swapped |
| JWT library | Passport + a Node JWT library | `python-jose` or `authlib` | **Yes** — implementation only |
| SAML library | Node SAML library (e.g. `@node-saml/passport-saml`) | `python3-saml` | **Yes** — implementation only |
| OIDC library | `openid-client` or NestJS Passport strategy | `authlib` | **Yes** — implementation only |
| TOTP library | `otplib` (Node) | `pyotp` | **Yes** — implementation only |
| Auth as NestJS Guards | `@UseGuards(JwtAuthGuard)` | `Depends(get_current_user)` | **Yes** — DI mechanism, per Document 07 §2 |
