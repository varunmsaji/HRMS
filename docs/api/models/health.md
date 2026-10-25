# Data models - health

Generated from the Pydantic/OpenAPI schemas. `Required` = present in the schema's `required` list (for *Read* models this means the server always sends it). `Nullable` = schema allows `null`. "Server-generated" lists fields that appear on a `*Read` model but not on its `*Create`/`*Update` counterpart (derived by name match - an inference, not a declared flag).

## HealthData
<a id="healthdata"></a>

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `status` | no | enum `ok`/`degraded` | no | default=`"ok"` | - |
| `database` | no | enum `ok`/`error` | no | default=`"ok"` | - |
| `redis` | no | enum `ok`/`error`/`skipped` | no | default=`"skipped"` | - |

## ReadinessData
<a id="readinessdata"></a>

Dependency-aware — distinct from `HealthData`/`/health` (unchanged, kept for backward compatibility with existing callers) and from liveness (`/health/live`, no dependency checks at all). Consumed by Nginx/an orchestrator to decide whether to route traffic here, not by Docker's own container `HEALTHCHECK` (that targets `/health/live` — see `apps/api/Dockerfile` — precisely so a dependency outage doesn't trigger container restart storms).

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `ready` | yes | boolean | no | - | - |
| `database` | yes | enum `ok`/`error` | no | - | - |
| `redis` | yes | enum `ok`/`error` | no | - | - |
| `storage_configured` | yes | boolean | no | - | - |

