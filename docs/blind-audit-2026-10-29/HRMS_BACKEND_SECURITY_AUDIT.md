# HRMS Backend Security Audit

Scope: FastAPI app `apps/api/src/hrms` (88.5k LOC Python 3.12, 354 routes). Static review; nothing executed against a running system.

## 1. Authentication & account security
| Area | Observation | Evidence | Status |
|---|---|---|---|
| Password hashing | argon2-cffi default `PasswordHasher`; min 8, max 128, letter+digit, common-password blocklist | `core/auth/passwords.py` | ✔ |
| Login | generic `INVALID_CREDENTIALS` for unknown account vs bad password; failed-count + `locked_until`; failed increment is committed before raising so rollback can't erase it | `modules/identity/service.py:70-95` | ✔ |
| Access token | HS256, 15 min, claims `sub, company_id, session_id, employee_id, type`; algorithm pinned on decode | `core/auth/jwt.py` | ✔ |
| Revocation | every request checks session not revoked, user ACTIVE, membership ACTIVE, company status | `core/auth/dependencies.py:350-403` | ✔ strong |
| Refresh token | opaque `token_urlsafe(48)`, **hash stored**, rotation, family reuse-detection revokes family, HttpOnly + SameSite=Lax + Path=/v1/auth cookie, `Secure` only when request scheme is https | `identity/service.py:270-290`, `core/auth/refresh_cookie.py` | ✔ (note: `Secure` depends on proxy headers being trusted — configure `trusted_proxy_hosts`) |
| Reset / verify / invite tokens | hashed at rest, TTL-bound, separate tables | `core/db/models/identity.py` | ✔ |
| Rate limiting | Redis sliding window, per-IP buckets, **fails closed** (503) if Redis is down | `shared/rate_limit.py:60-125` | ✔ |
| Secrets | non-development environments refuse dev-default / weak JWT, PII master key, DB creds | `core/config/settings.py:10-75` (`_guard_non_development_secrets`) | ✔ |
| Platform admin | separate principal/token/session tables, login limited 10/min, all other 20 routes require `Principal` | `modules/platform/router.py:42-70` | ✔ |
| Logging of secrets | engine `hide_parameters=True`; redaction module; no password/fingerprint logging found by grep in reviewed paths | `core/db/session.py:36` | ✔ (no exhaustive log-statement review) |
| CORS | explicit origin tuple, empty by default; `allow_credentials=True` | `app.py:99-100`, `settings.py:145` | ✔ provided origins are never `*` — guarded by `effective_cors_origins` (not read in full) |

**Not found / not verified:** OAuth (none present); email-verification enforcement on login (feature exists, enforcement path not traced); user-enumeration via `register_company` / `forgot_password` responses (not traced); lockout bypass via many IPs (per-account lock exists).

## 2. Injection & unsafe constructs
* 71 `text()` calls outside `core/db`; only two interpolate strings: `core/db/timeouts.py:32` (`SHOW {name}`) and `attendance/face_cleanup.py:106` (`({eligible})`). Both receive **module-level constants**, not request data → **F-04 (P3, confirmed safe today)**: brittle pattern; prefer allow-list assertion.
* No `eval/exec/pickle/yaml.load/subprocess/os.system` in `src/hrms`.

## 3. Data exposure & uploads
* Response schemas are Pydantic models per route; no wildcard ORM dumps seen in sampled routes. Exhaustive field-by-field review not done.
* Uploads/downloads: validation modules exist (`core/uploads.py`, file sniffing, 10 MB cap noted in code comments, nginx `client_max_body_size 15m` on the API server block). Presigned GET URLs for downloads (`core/storage.py:130`). **Not reviewed:** MIME sniff completeness, presigned TTL, content-disposition, antivirus.
* `/metrics`: bearer `hmac.compare_digest`, 404 when token unset, **and** nginx `return 404` for the public vhost (`infra/nginx/conf.d/hrms.conf.template`). ✔

## 4. Security findings
| ID | Sev | Conf. | Finding | Fix direction |
|---|---|---|---|---|
| F-05 | P2 | confirmed | RLS GUC is set from unverified header before auth (see Tenant report). | Set GUC only inside `get_tenant_context`; make `get_session` not read the header. |
| F-09 | P2 | confirmed | Redis (broker, rate-limit counters, result backend) started with `redis-server --appendonly yes` — **no `requirepass`/ACL**. Mitigated by being on the private `data` network only. | Add password/ACL; set `rediss://` if ever off-host. |
| F-13a | P2 | confirmed | Access token is persisted in `localStorage` (`apps/web/src/lib/auth/token-storage.ts`) – readable by any XSS (15-min exposure). Refresh token is correctly HttpOnly. | Acceptable for pilot; consider in-memory token + silent refresh. |
| F-16 | P3 | confirmed | `certbot/certbot:latest`, `zricethezav/gitleaks:latest` unpinned; postgres/redis/nginx tags floating. No `pip-audit`/`npm audit`/image scan step found in CI. | Pin by digest (as already done for MinIO); add audit steps. |
| F-17 | P3 | confirmed | Root `.env` `DATABASE_URL` targets a different DB/role (`hirico_user`, port 5432) than the HRMS dev stack (5433) – stale config / two sources of truth. Tracked repo-root clutter: `mavericks-kit.zip` (3.7 MB), `shirt.png`, `shorts.png`, `run_full_tests.py`. | Remove/relocate; one canonical env source. |
| F-18 | P3 | needs check | `backups/hrms_dev_mock_data.dump` (9 MB) sits in the working tree (untracked). If real employee data were ever used to build it, it is PII at rest; confirm it is `.gitignore`d and synthetic. | |
| F-24 | P3 | confirmed | `ALTER`-free `docker-compose.yml` (dev) hard-codes `hrms_app_dev_password`; guarded to dev only by tests (`tests/security/test_db01_credential_provisioning.py`). | fine; keep test. |

## 5. Dependencies
`pyproject.toml`: floor-pinned (`>=`) runtime deps with `uv.lock` (2,646 lines) → reproducible builds if CI uses `--frozen`; CI uses plain `uv sync --all-groups` (not `--frozen`), so lock drift is possible (F-16). Dev tools are an optional extra (good). Python `>=3.12`. Web: caret ranges + `package-lock.json`, CI uses `npm ci`. No local advisory database was available, so **no CVE verification was performed**.
