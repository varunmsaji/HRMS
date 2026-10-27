# QA provisioning evidence — 2026-10-26T17:50+0530

`ISOLATION PROVED`

No application HTTP request, migration, grant script, or test ran. `GET /health` was not called.

## Resources owned by project `hrms-qa`

| Resource | Name | Target |
|---|---|---|
| Postgres container | `hrms-qa-postgres` | `127.0.0.1:15433`, database `hrms_qa_20261026` |
| Postgres volume | `hrms_qa_pg_20261026` | this container only |
| Redis container | `hrms-qa-redis` | `127.0.0.1:16380`, no volume from `hrms_redis_data` |
| MinIO container | `hrms-qa-minio` | `127.0.0.1:19000` and `127.0.0.1:19001` |
| MinIO volume | `hrms_qa_minio_20261026` | this container only |
| Network | `hrms-qa-net` | project `hrms-qa` |
| Bucket | `hrms-qa-20261026` | private, listed through port `19000` only |
| API | PID 1312568 | `127.0.0.1:18000`, cwd `docs/qa/comprehensive_hrms/runtime` |
| Worker | PID 1312569 | broker `127.0.0.1:16380/1`, no beat |
| Secrets | `runtime/qa.env` | mode `0600`, not printed |

`SELECT current_database()` on `hrms-qa-postgres` returned `hrms_qa_20261026`. Redis `PING` on `127.0.0.1:16380` returned `PONG`. Index 0 size is 0. Index 1 size is 2, both keys are Kombu bindings (`_kombu.binding.celery.pidbox`, `_kombu.binding.default`), not queued tasks.

## Effective configuration

API, worker, and a one-shot `Settings()` load in the runtime directory agree:

- Database `127.0.0.1:15433/hrms_qa_20261026`
- Redis `127.0.0.1:16380/0`
- Celery broker and result backend `127.0.0.1:16380/1`
- S3 `http://127.0.0.1:19000`, bucket `hrms-qa-20261026`
- `EMAIL_PROVIDER=logging`, `EMAIL_OUTBOX_DISPATCH=none`, SMTP host and provider tokens length 0
- `FACE_VERIFICATION_PROVIDER=disabled`
- No marker for `hrms_dev`, port `6380`, port `5433`, bucket `hrms-documents`, or `hostinger`
- No connection from these PIDs to ports 25, 465, or 587

Developer containers kept their original IDs and start time `2026-10-25T23:35:28Z`: `hrms-postgres` `b90719b25090`, `hrms-redis` `e451a0191fa9`, `hrms-minio` `dc8318a20fd4`. Volumes `hrms_postgres_data`, `hrms_redis_data`, and `hrms_minio_data` were not mounted by the QA containers.

## Not done

Migrations, grants, tenant seed, Batch 0, Batch S, and `GET /health`. The QA database has no application schema.
