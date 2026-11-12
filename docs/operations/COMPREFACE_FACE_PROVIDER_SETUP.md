# CompreFace face provider - setup

Written for: the engineer/operator who runs CompreFace and selects it as a face provider.

Date: 2026-11-09. **Not yet run against a live CompreFace instance.** The adapter is covered by unit
tests against a mocked HTTP transport only. CompreFace's error bodies are not in its published docs,
so the "no face" and "subject not found" handling (section 5) must be confirmed on a real instance
before CompreFace decides any punch. Thresholds are uncalibrated defaults.

CompreFace is a fourth engine behind the same provider port as Face++, Azure and the open-source
engine (`apps/api/src/hrms/modules/attendance/compreface_face_provider.py`). It replaces nothing:
`FACE_VERIFICATION_PROVIDER` picks which engine decides new punches, and every engine's stored data
stays deletable after a switch.

## 1. What runs

CompreFace 1.2.0 (Apache-2.0, `exadel/compreface-*` images), five containers behind the
`compreface` compose profile: its own Postgres, `compreface-admin`, `compreface-api`,
`compreface-core` (the model) and `compreface-fe` (admin UI + proxy). Budget about 2-3 GB RAM,
mostly `compreface-core`: fine on KVM 4, tight on KVM 2.

`SAVE_IMAGES_TO_DB=false`: CompreFace keeps embeddings only, never the photos.

Model licence: the default `compreface-core` image uses a FaceNet model. Its training-data terms
have not been reviewed for commercial use. Check them the same way as for the open-source engine
before production.

## 2. Start it

Development (the API runs on the host):

```bash
docker compose --profile compreface up -d
```

The admin UI and API are at http://localhost:8090 (loopback only).

VPS: set `COMPREFACE_POSTGRES_PASSWORD` in the repo-root `.env`, then:

```bash
docker compose -f docker-compose.vps.yml --profile compreface up -d
```

The API and worker reach CompreFace at `http://compreface-api:8080` over the internal `face`
network. The admin UI is published on `127.0.0.1:8091` only. Open it through a tunnel:

```bash
ssh -L 8091:127.0.0.1:8091 <vps>
```

## 3. Create the API key (one time)

In the admin UI: sign up (the first user is the owner), create an application, then inside it
create a **Recognition** service. Copy that service's API key. That key can read and change every
face in the service, so treat it like a password.

## 4. Configure the API

In `apps/api/.env` (dev) or `apps/api/env/.env.production`:

```
COMPREFACE_BASE_URL=http://localhost:8090        # VPS: http://compreface-api:8080
COMPREFACE_API_KEY=<recognition service key>
FACE_VERIFICATION_PROVIDER=compreface
```

To observe it next to the current engine first, leave `FACE_VERIFICATION_PROVIDER` as it is and set
`FACE_VERIFICATION_SHADOW_PROVIDER=compreface` with `FACE_PROVIDER_COMPARISON_ENABLED=true`
(`FACE_PROVIDER_SHADOW_COMPARISON.md`).

Boot is refused without a key, or with plain `http` to anything other than a Docker service name or
loopback. CompreFace-only thresholds (on 0..1, uncalibrated):

| Setting | Default | Meaning |
|---|---|---|
| `COMPREFACE_MATCH_MIN_SIMILARITY` | 0.90 | a punch frame must reach this |
| `COMPREFACE_ENROLLMENT_ANGLE_MIN_SIMILARITY` | 0.80 | each turned capture vs the front one |
| `COMPREFACE_DET_PROB_THRESHOLD` | 0.8 | minimum face-detection confidence |

Apply the migration that allows the `COMPREFACE` value (`alembic upgrade head`, revision
`20261110090000`).

Switching the deciding engine means employees enroll again, because each engine's face data is
separate.

## 5. To confirm on a live instance

- A photo with no face returns HTTP 400 with `code` 28. The adapter also accepts the message text.
- Deleting a subject that no longer exists returns 404, or a 4xx whose message says "not found".
  Anything else is treated as a failed deletion and retried by the deletion outbox.
- A photo with two faces is still accepted as an example. The adapter then checks the face count and
  removes the example.

Measure latency with `apps/api/scripts/face/provider_benchmark.py compreface --images DIR`.
