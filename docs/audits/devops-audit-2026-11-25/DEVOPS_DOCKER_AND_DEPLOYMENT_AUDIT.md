# Docker and deployment audit

Audit date: 2026-11-25. Files read: `apps/api/Dockerfile`, `apps/web/Dockerfile`, `docker-compose.yml`, `docker-compose.prod.yml`, `docker-compose.vps.yml`, `docker-compose.monitoring.yml`, `infra/nginx/nginx.conf`, `infra/nginx/start.sh` (referenced by compose), `infra/docker/postgres/init/`. Running containers were inspected on the VPS. Images were not rebuilt.

## 1. Which Compose file is production?

`docker-compose.vps.yml` is the file on the server (`/opt/hrms`, mtime 2026-11-04). It is a variant of `docker-compose.prod.yml` that publishes API, web, and MinIO on loopback and omits the nginx and certbot services, because host nginx already owns 80 and 443.

`docker-compose.prod.yml` is the single-tenant design where Compose nginx publishes 80 and 443. It is not the running stack. Using it on this VPS would fight host nginx for those ports.

`docker-compose.yml` is local development. It publishes Postgres on 5433, Redis on 6380, and MinIO on 9000 and 9001, with fixed development passwords.

`docker-compose.monitoring.yml` is an optional overlay. It is not running.

## 2. Service-by-service

### FastAPI

| Item | Repository | Running container |
|---|---|---|
| Base | `python:3.12-slim`, multi-stage. Builder installs uv. Runtime does not | Image `hrms-api:latest` created 2026-11-04 |
| User | `hrms` uid 1000 | `Config.User` = `hrms` |
| Command | Gunicorn, Uvicorn worker, `exec` so it is PID 1, graceful timeout 30 s | Inherited unless overridden. API service does not override |
| Health | `GET /health/live` inside the image. Comment explains why this is not `/health/ready` | Status healthy |
| Restart | `unless-stopped` | Same, memory limit 0 |
| Ports | Prod file: none. VPS file: `127.0.0.1:8001:8000` | `127.0.0.1:8001` observed |
| Networks | `data` and `edge` (vps also `face`) | Present |
| Logs | json-file 10m × 5, plus volume `api_logs` | Driver configured in the file. On-disk application logs were not tailed |
| Env | `env_file: apps/api/env/.env.production`, `PROMETHEUS_MULTIPROC_DIR` | Database host confirmed as `postgres:5432/hrms_demo`. Other values not printed |
| Depends on | Postgres, Redis, MinIO healthy | Those three are healthy |
| Shutdown | Gunicorn graceful timeout 30 s | Not exercised |

The image copies Alembic, entrypoints, and scripts. Face-liveness assets are verified at build. Open-source face assets are included only when `FACE_OS_ASSETS=true`. The vps compose file sets that build arg. The prod compose file does not. The running image was built from the vps file's build section if the documented command was used. That was not re-proven from build history.

### Web

| Item | Repository | Running |
|---|---|---|
| Base | `node:20-alpine`, three stages, standalone output | `hrms-web:latest` created 2026-11-04 10:42 UTC |
| User | `node` | `node` |
| Health | `fetch` of `/login` | Healthy |
| Port | VPS: `127.0.0.1:3001:3000` | Matches |
| Build arg | `NEXT_PUBLIC_API_URL` required, inlined at build | Changing the URL requires a rebuild. Confirmed by the Dockerfile comment and by Next's behaviour |
| Depends on | None in vps file | Can start before the API. Acceptable for a static-ish frontend. Pages that call the API fail until the API is up |

### Worker

Same image as the API. Command runs Celery with concurrency from `CELERY_CONCURRENCY` defaulting to 2. Health check is `celery inspect ping` and the container is healthy. That ping proves some worker answered, which is correct for one replica. No memory or CPU limit. One sample: 2.16 GiB, 0.07% CPU, restart count 0 after about three weeks. PID 1 RSS was only about 90 MB, so the memory is in child processes. No OOM kill.

Depends on Postgres, Redis, and MinIO. It does not wait for the API. That is correct. It must be the same image as the API. Nothing checks the image ID matches.

### Beat

Same image. One replica by comment and by there being one container. Schedule file in `/tmp`, so a restart can repeat the last tick. Tasks are described as idempotent in `celery_app.py`. Health check is disabled. `docker inspect` reports health `none`. Restart policy brings back a crash. It does not detect a hung Beat. The scheduler heartbeat task is the intended signal, and it is only visible if something reads it. The host monitor does. Prometheus, which would alert on `hrms_celery_scheduler_heartbeat_age_seconds`, is not running.

### PostgreSQL

`postgres:16-alpine`, not a digest. Running 16.15. Health check `pg_isready`. Volume `postgres_data`. Init scripts mounted at `/docker-entrypoint-initdb.d`. Those scripts run only on an empty data directory. A later change to `002_app_role.sh` does not re-apply. No published port in the HRMS project. `shared_buffers` 128 MB and `max_connections` 100 are image defaults. No `deploy.resources`. User is the image default.

### Redis

`redis:7-alpine` with `appendonly yes`. Confirmed on the server. No password. No `maxmemory`. Policy `noeviction`, so a full memory condition returns write errors rather than evicting. About 10.5 MB used, so this is not an active incident. No published HRMS port. Persistence is the AOF on the Docker volume, which dies with the disk. It is not part of the age backup (the backup script copies Postgres, MinIO, and env files). Redis is a broker and a cache. Losing it drops queued jobs and rate-limit counters. That is acceptable if it is stated, and it is stated in the compose comment. It is not acceptable to treat Redis as a system of record. It is not one.

### MinIO (pgsty/silo)

Pinned digest in vps and prod files, and that digest is what `docker ps` shows (`635197cb9f36`). Dev file uses `:latest`. Health check is a TCP connect to 9000 because the image has no curl. Loopback publish `127.0.0.1:9100` so host nginx can proxy `storage.krewoxa.com`. Public request returned 403. Volume `minio_data` is included in the daily encrypted backup. Init container sets the bucket to anonymous none.

### Nginx

Not a container on this VPS. Host nginx is the edge. The Compose nginx (`nginx:1.27-alpine`) and the templates in `infra/nginx/` are for the other compose file. Host config is outside git. JSON access log and token-path redaction exist in the repo template. Whether the live `krewoxa` site file has the same redaction was not fully compared. HSTS is present. `client_max_body_size` in the repo template's main file is 15m.

### Certbot

Compose certbot is unused here. Host `certbot.timer` is active. Certificate expiry 2027-01-30.

### Monitoring services

Defined, not running. See the observability audit.

### CompreFace

Profile-gated. Not running. RAM comment in the vps file says 2–3 GB. Turning it on beside a 2.16 GB worker on an 8 GB host would require a measurement first.

## 3. Cross-cutting questions

| Question | Answer |
|---|---|
| Containers running as root unnecessarily? | API, worker, Beat, and web are not. Postgres, Redis, and MinIO use upstream images. Their entrypoints drop privileges. The compose file does not set `user:`. Hirico's host uvicorn runs as root. That is outside HRMS and still on the box |
| Mutable tags? | Yes for Postgres, Redis, nginx, certbot, Python, and Node. No for production MinIO and the MinIO client. Application images are the mutable tag `latest` |
| Image size? | Not measured. Multi-stage builds are in place, which is the main size control |
| Secrets in images? | Dockerfiles do not copy env files. `NEXT_PUBLIC_API_URL` is baked into the web image, and it is a public URL. Production secrets are env-file mounts |
| Exposed to the internet? | HRMS containers are on loopback or unpublished. Host nginx is public on 80 and 443. Hirico's uvicorn listens on `0.0.0.0:8000`. UFW does not allow 8000. It was not probed from outside |
| Volumes protected? | Docker named volumes on the single disk. Backups cover Postgres and MinIO. Redis volume is local AOF only |
| Start order? | API, worker, and Beat wait for healthy Postgres, Redis, and MinIO. Web does not wait. Beat does not wait for a worker, so the first ticks after a cold start can sit in Redis until the worker is up. That is safe if tasks are idempotent |
| Health checks meaningful? | API liveness is meaningful and deliberately shallow. Readiness exists at `/health/ready` and returned 200 from the public URL. Worker ping is meaningful for one replica. Beat has none. MinIO TCP check does not prove the bucket exists |
| Resource limits? | Not on the running HRMS containers |
| Compose enough? | Yes. One host, seven containers, no need for a scheduler. Kubernetes would add a control plane this team would have to operate. The missing piece is a registry and a deploy script, not an orchestrator |

## 4. Deployment strategies

What happens today is a recreate: `docker compose up -d` replaces the container. For the web service the runbook keeps the previous image tag, so rollback is a retag and recreate. During the recreate the site is down for seconds. That is acceptable at this traffic.

Rolling, blue-green, and canary need a second copy of the process and a load balancer that can shift. Host nginx can do blue-green with two loopback ports. That is more moving parts than this VPS needs until deploys are frequent and a bad API release has already hurt. The simplest reliable strategy is:

1. Build immutable tags in CI (`sha-de83274`), push to GHCR.
2. On the VPS, pull that tag for api, worker, and beat together.
3. Run `migrate` once, from that same tag, before recreating the three processes.
4. Recreate api, then worker, then beat.
5. Curl `/health/ready` from the host. If it fails, retag the previous digest and recreate the three again.
6. Leave the web on its own tag when the change is frontend-only, as the current runbook already does.

Database migrations need a rule the current tree does not enforce: a migration that ships in the same release as code must be backward compatible with the previous process, because the old containers are still running until step 4. Expand and contract. The `migrate` service already refuses to run on every start, which is the right default. Do not move it into the API command.

Background tasks: stop Beat first or accept one overlapping run, then stop the worker with a long stop timeout so `acks_late` tasks can finish or be redelivered. The current worker stop behaviour was not timed. Gunicorn's graceful timeout does not apply to the Celery command.

## 5. Repeatability and downtime

A deploy is repeatable only if the person copies the same files and uses the same build args. `/opt/hrms` is not git, so there is no `git rev-parse` on the server to prove what is running. Downtime is the recreate window, not a rolling overlap. Rollback of the API does not roll back a migration. Alembic downgrades exist for some revisions and are tested in the migration job for specific cases. They are not a general undo for the thirteen revisions the live database has not applied yet.

## 6. Local development differences that matter

| Dev compose | Production vps compose |
|---|---|
| Fixed passwords in the file | Required variables, no defaults for database and MinIO passwords |
| Ports published on the host | Loopback only, or unpublished |
| `pgsty/silo:latest` | Digest pin |
| Redis without AOF | AOF on |
| CompreFace optional on 8090 | Optional on 8091, not running |
| No API container | API container |

CI follows the dev ports and the prod MinIO digest. That split is documented in `ci.yml` and is coherent.
