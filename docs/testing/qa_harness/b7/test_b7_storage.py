"""QA B7 (part 2) - documents / object storage and failure injection against the DISPOSABLE MinIO (silo) and Redis only.

Catalogue ids: DOC-UP-001, DOC-XT-001, DOC-DL-001, DOC-STORE-001, JOB-HEALTH-001 (dependency-down path), AUTH-RATE-002.
Mounted read-only at /qa/b7; run through entry.py.  Every assertion checks BOTH the HTTP answer and the stored state:
`employee_document` rows (database) and objects in the bucket (boto3 list/head against the private MinIO).
Failure injection: "dead" dependencies are 127.0.0.1 ports with no listener inside the sandbox's own network namespace
(connection refused - identical to a stopped container); no container is stopped.  Black-holed (timeout) dependencies are NOT simulated.
Files are synthetic (magic-byte headers plus filler).  Nothing leaves the sandbox.
"""

import asyncio
import hashlib
import json
import os
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import boto3
import httpx
import pytest
from botocore.config import Config
from botocore.exceptions import ClientError
from httpx import AsyncClient
from sqlalchemy import text
from tests.integration.modules.attendance.test_employee_default_role_attendance import (
    _employee_user,
    _teardown as _att_teardown,
    _tenant,
)
from tests.integration.modules.employee.test_employee_documents import (
    _JPEG_BYTES,
    _PNG_BYTES,
    _create_employee,
    _register_tenant,
    _teardown,
)
from tests.integration.modules.employee_import.test_employee_import import (
    _build_csv,
    _cleanup_employee_rows,
    _cleanup_import_tables,
    _cleanup_org_structure,
)
from tests.integration.modules.employee.test_employee_assignment import _setup_org_structure
from tests.integration.modules.organisation.test_registration_flow import _cleanup

from hrms.core.config.settings import get_settings
from hrms.core.db.session import dispose_engine, get_session_factory, set_rls_company_id
from hrms.core.storage import DocumentStorageService

pytestmark = pytest.mark.asyncio
ART = Path(os.environ.get("QA_ARTIFACTS", "/tmp/qa-artifacts"))
PDF_BYTES = b"%PDF-1.4\n" + b"synthetic pdf body\n" * 5
DEAD = "http://127.0.0.1:1"


def rec(case: str, step: str, **observed: Any) -> None:
    ART.mkdir(parents=True, exist_ok=True)
    with (ART / f"{case}.jsonl").open("a") as fh:
        fh.write(json.dumps({"ts": datetime.now(UTC).isoformat(), "step": step, **observed}, default=str) + "\n")


async def q(sql: str, **params: Any) -> list[dict[str, Any]]:
    async with get_session_factory()() as session:
        return [dict(r) for r in (await session.execute(text(sql), params)).mappings().all()]


def s3() -> Any:
    st = get_settings()
    return boto3.client("s3", endpoint_url=st.s3_endpoint_url, aws_access_key_id=st.aws_access_key_id, aws_secret_access_key=st.aws_secret_access_key,
                        region_name=st.aws_region, config=Config(signature_version="s3v4"))


def keys(prefix: str) -> list[str]:
    r = s3().list_objects_v2(Bucket=get_settings().s3_bucket_documents, Prefix=prefix)
    return sorted(o["Key"] for o in r.get("Contents", []))


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


async def upload(client: AsyncClient, h: dict[str, str], emp: str, name: str, data: bytes, ctype: str = "application/octet-stream", doc_type: str = "PAN") -> Any:
    return await client.post(f"/v1/employees/{emp}/documents", headers=h, data={"document_type": doc_type}, files={"file": (name, data, ctype)})


async def doc_rows(company_id: Any) -> list[dict[str, Any]]:
    return await q("SELECT id::text id, employee_id::text employee_id, s3_key, content_type, size_bytes, original_filename FROM employee_document WHERE company_id = :c ORDER BY uploaded_at", c=str(company_id))


# ====================================================================================== DOC-UP-001
async def test_doc_up_001_upload_validation_matrix(client: AsyncClient, seeded_plan_catalogue: None) -> None:
    c = "DOC-UP-001"
    h, cid, uid = await _register_tenant(client)
    try:
        emp = await _create_employee(client, h)
        prefix = f"employee/{cid}/"
        big = _JPEG_BYTES + b"\0" * (10 * 1024 * 1024)            # > 10 MiB limit
        samples = [  # (label, filename, bytes, declared content type, expect accepted)
            ("jpeg", "id card.jpg", _JPEG_BYTES, "image/jpeg", True),
            ("png", "scan.png", _PNG_BYTES, "image/png", True),
            ("pdf", "form.pdf", PDF_BYTES, "application/pdf", True),
            ("jpeg declared as pdf", "x.pdf", _JPEG_BYTES, "application/pdf", True),             # type comes from magic bytes, never the claim
            ("path traversal filename", "../../../etc/passwd.jpg", _JPEG_BYTES, "image/jpeg", True),
            ("very long filename", ("a" * 400) + ".jpg", _JPEG_BYTES, "image/jpeg", True),
            ("control chars in filename", "bad\r\nname\x00.jpg", _JPEG_BYTES, "image/jpeg", True),
            ("text named .jpg", "photo.jpg", b"just some text, not an image", "image/jpeg", False),
            ("html/script named .png", "p.png", b"<html><script>alert(1)</script></html>", "image/png", False),
            ("svg", "p.svg", b"<svg xmlns='http://www.w3.org/2000/svg'><script>1</script></svg>", "image/svg+xml", False),
            ("windows executable", "run.pdf", b"MZ\x90\x00" + b"\0" * 64, "application/pdf", False),
            ("zip", "a.png", b"PK\x03\x04" + b"\0" * 64, "image/png", False),
            ("empty file", "empty.jpg", b"", "image/jpeg", False),
            ("over 10 MiB", "huge.jpg", big, "image/jpeg", False),
        ]
        results: dict[str, Any] = {}
        accepted_hashes: dict[str, str] = {}
        for label, fname, data, ctype, expect_ok in samples:
            r = await upload(client, h, emp["id"], fname, data, ctype)
            body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
            results[label] = {"status": r.status_code, "code": (body.get("error") or {}).get("code"), "stored_name": (body.get("data") or {}).get("original_filename"),
                              "stored_type": (body.get("data") or {}).get("content_type")}
            if r.status_code == 201:
                accepted_hashes[label] = sha(data)
            assert r.status_code < 500, (label, r.status_code, r.text[:200])
            assert (r.status_code == 201) == expect_ok, (label, r.status_code, r.text[:200])
        # also an unknown document_type and a missing file part
        bad_type = await upload(client, h, emp["id"], "a.jpg", _JPEG_BYTES, "image/jpeg", doc_type="NOT_A_TYPE")
        no_file = await client.post(f"/v1/employees/{emp['id']}/documents", headers=h, data={"document_type": "PAN"})
        results["unknown document_type"] = {"status": bad_type.status_code}
        results["missing file part"] = {"status": no_file.status_code}
        assert 400 <= bad_type.status_code < 500 and 400 <= no_file.status_code < 500
        rows = await doc_rows(cid)
        objs = keys(prefix)
        n_ok = sum(1 for *_x, ok in samples if ok)
        rec(c, "upload matrix", results=results, db_rows=len(rows), bucket_objects=len(objs), expected_accepted=n_ok)
        assert len(rows) == n_ok == len(objs), "every rejected upload must leave neither a row nor an object"
        assert {r["s3_key"] for r in rows} == set(objs), "database references and bucket objects must be the same set"
        # stored content equals uploaded content; key never contains client-supplied names; sizes/types recorded from bytes
        for row in rows:
            body = s3().get_object(Bucket=get_settings().s3_bucket_documents, Key=row["s3_key"])
            data = body["Body"].read()
            assert len(data) == row["size_bytes"] and sha(data) in accepted_hashes.values()
            assert "passwd" not in row["s3_key"] and ".." not in row["s3_key"] and row["s3_key"].rsplit("/", 1)[-1].startswith("document.")
            assert body["ContentType"] == row["content_type"]
        assert results["jpeg declared as pdf"]["stored_type"] == "image/jpeg"
        names = [r["original_filename"] for r in rows]
        rec(c, "stored display filenames", names=names)
        assert all("/" not in n and ".." not in n and "\x00" not in n and "\n" not in n and len(n) <= 200 for n in names)
    finally:
        await _teardown(company_id=cid, user_id=uid)
        for k in keys(f"employee/{cid}/"):
            s3().delete_object(Bucket=get_settings().s3_bucket_documents, Key=k)


# ====================================================================================== DOC-DL-001 (+ dangling metadata)
async def test_doc_dl_001_presigned_download_expiry_tamper_and_missing_object(client: AsyncClient, seeded_plan_catalogue: None) -> None:
    c = "DOC-DL-001"
    st = get_settings()
    h, cid, uid = await _register_tenant(client)
    try:
        emp = await _create_employee(client, h)
        data = PDF_BYTES + os.urandom(2048)
        up = await upload(client, h, emp["id"], "salary slip.pdf", data, "application/pdf")
        assert up.status_code == 201, up.text
        doc = up.json()["data"]
        listing = (await client.get(f"/v1/employees/{emp['id']}/documents", headers=h)).json()["data"]
        url = listing[0]["download_url"]
        async with httpx.AsyncClient() as raw:
            ok = await raw.get(url)
            bad_sig = await raw.get(url.replace("X-Amz-Signature=", "X-Amz-Signature=00"))
            no_query = await raw.get(url.split("?", 1)[0])
        rec(c, "default URL", status=ok.status_code, sha_equal=sha(ok.content) == sha(data), disposition=ok.headers.get("content-disposition"),
            tampered_signature=bad_sig.status_code, unsigned=no_query.status_code, expires_param=[p for p in url.split("&") if p.startswith("X-Amz-Expires")])
        assert ok.status_code == 200 and sha(ok.content) == sha(data)
        assert "attachment" in ok.headers.get("content-disposition", "")
        assert bad_sig.status_code in (400, 403) and no_query.status_code in (401, 403)

        # expiry: sign directly with a 2 s lifetime (the API's own lifetime is the 300 s default) and fetch after it passed
        key = (await doc_rows(cid))[0]["s3_key"]
        short = await DocumentStorageService(st).presigned_get_url(key=key, expires_in=2)
        async with httpx.AsyncClient() as raw:
            early = await raw.get(short)
            await asyncio.sleep(3.5)
            late = await raw.get(short)
        rec(c, "expiry (2 s URL)", before_expiry=early.status_code, after_expiry=late.status_code, late_body=late.text[:160])
        assert early.status_code == 200 and late.status_code == 403

        # dangling metadata: object removed behind the API's back
        s3().delete_object(Bucket=st.s3_bucket_documents, Key=key)
        listing2 = await client.get(f"/v1/employees/{emp['id']}/documents", headers=h)
        async with httpx.AsyncClient() as raw:
            gone = await raw.get(listing2.json()["data"][0]["download_url"])
        rows = await doc_rows(cid)
        rec(c, "OBSERVATION dangling metadata", list_status=listing2.status_code, url_issued=bool(listing2.json()["data"]), fetch_status=gone.status_code, db_rows=len(rows), objects=len(keys(f"employee/{cid}/")))
        assert listing2.status_code == 200 and gone.status_code == 404           # URL is issued (signing is local) but the fetch is a clean 404
        deleted = await client.delete(f"/v1/employees/{emp['id']}/documents/{doc['id']}", headers=h)
        rec(c, "delete when the object is already gone", status=deleted.status_code, rows_after=len(await doc_rows(cid)))
        assert deleted.status_code == 200 and (await doc_rows(cid)) == []
    finally:
        await _teardown(company_id=cid, user_id=uid)


# ====================================================================================== DOC-XT-001
async def test_doc_xt_001_cross_tenant_and_peer_employee_denial(client: AsyncClient, seeded_plan_catalogue: None) -> None:
    c = "DOC-XT-001"
    a = await _tenant(client)
    b = await _tenant(client)
    try:
        a_id, a_h = await _employee_user(client, a, "Asha")
        p_id, p_h = await _employee_user(client, a, "Peer")
        up = await upload(client, a.admin, a_id, "pan.jpg", _JPEG_BYTES, "image/jpeg")
        assert up.status_code == 201, up.text
        doc = up.json()["data"]
        rows_before, objs_before = await doc_rows(a.company_id), keys(f"employee/{a.company_id}/")
        probes: dict[str, Any] = {}
        # another tenant's admin
        probes["T2 admin list"] = (await client.get(f"/v1/employees/{a_id}/documents", headers=b.admin)).status_code
        probes["T2 admin upload for T1 employee"] = (await upload(client, b.admin, a_id, "x.jpg", _JPEG_BYTES, "image/jpeg")).status_code
        probes["T2 admin delete"] = (await client.delete(f"/v1/employees/{a_id}/documents/{doc['id']}", headers=b.admin)).status_code
        probes["T2 admin review"] = (await client.post(f"/v1/employees/{a_id}/documents/{doc['id']}/review", headers={**b.admin, "If-Match": "1"}, json={"status": "VERIFIED"})).status_code
        # same-tenant peer employee (SELF scope)
        peer_list = await client.get(f"/v1/employees/{a_id}/documents", headers=p_h)
        probes["peer employee list"] = peer_list.status_code
        probes["peer employee upload for A"] = (await upload(client, p_h, a_id, "x.jpg", _JPEG_BYTES, "image/jpeg")).status_code
        probes["peer employee delete"] = (await client.delete(f"/v1/employees/{a_id}/documents/{doc['id']}", headers=p_h)).status_code
        own = await client.get(f"/v1/employees/{a_id}/documents", headers=a_h)
        probes["owner employee list"] = own.status_code
        # no download URL may appear in any refusal
        refusals = [peer_list]
        for r in refusals:
            assert "download_url" not in r.text and "X-Amz" not in r.text
        rows_after, objs_after = await doc_rows(a.company_id), keys(f"employee/{a.company_id}/")
        rec(c, "probes", results=probes, owner_gets_url=bool(own.status_code == 200 and own.json()["data"] and own.json()["data"][0].get("download_url")),
            rows_unchanged=rows_before == rows_after, objects_unchanged=objs_before == objs_after)
        for k, v in probes.items():
            if k != "owner employee list":
                assert v in (403, 404), (k, v)
        assert probes["owner employee list"] == 200
        assert rows_before == rows_after and objs_before == objs_after
        # a presigned URL is a bearer capability (not tenant-bound): record, do not assert
        url = own.json()["data"][0]["download_url"]
        async with httpx.AsyncClient() as raw:
            anon = await raw.get(url)
        rec(c, "OBSERVATION presigned URL is a bearer capability", anonymous_fetch_status=anon.status_code, ttl="300 s default")
    finally:
        for k in keys(f"employee/{a.company_id}/") + keys(f"employee/{b.company_id}/"):
            s3().delete_object(Bucket=get_settings().s3_bucket_documents, Key=k)
        await _cleanup_docs(a.company_id)
        await _att_teardown(a, b)


async def _cleanup_docs(cid: Any) -> None:
    async with get_session_factory()() as session:
        await session.execute(text("DELETE FROM employee_document WHERE company_id = :c"), {"c": str(cid)})
        await session.commit()


# ====================================================================================== DOC-STORE-001
@pytest.fixture
def dead_storage(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("S3_ENDPOINT_URL", DEAD)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


async def test_doc_store_001_storage_unavailable_upload_import_delete_list(client: AsyncClient, seeded_plan_catalogue: None, monkeypatch: pytest.MonkeyPatch) -> None:
    c = "DOC-STORE-001"
    h, cid, uid = await _register_tenant(client)
    org = await _setup_org_structure(client, h)
    try:
        emp = await _create_employee(client, h)
        good = await upload(client, h, emp["id"], "ok.jpg", _JPEG_BYTES, "image/jpeg")
        assert good.status_code == 201
        doc_id = good.json()["data"]["id"]
        prefix = f"employee/{cid}/"
        base_rows, base_objs = len(await doc_rows(cid)), len(keys(prefix))
        monkeypatch.setenv("S3_ENDPOINT_URL", DEAD)
        get_settings.cache_clear()
        t0 = time.time()
        out: dict[str, Any] = {}
        up = await upload(client, h, emp["id"], "new.jpg", _JPEG_BYTES, "image/jpeg")
        out["document upload"] = {"status": up.status_code, "code": (up.json().get("error") or {}).get("code"), "has_request_id": bool((up.json().get("error") or {}).get("request_id")), "secs": round(time.time() - t0, 1)}
        t1 = time.time()
        imp = await client.post("/v1/employee-imports", headers=h, files={"file": ("employees.csv", _build_csv(org), "text/csv")})
        out["import upload"] = {"status": imp.status_code, "code": (imp.json().get("error") or {}).get("code"), "secs": round(time.time() - t1, 1)}
        dele = await client.delete(f"/v1/employees/{emp['id']}/documents/{doc_id}", headers=h)
        out["delete"] = {"status": dele.status_code, "code": (dele.json().get("error") or {}).get("code") if dele.status_code >= 400 else None}
        lst = await client.get(f"/v1/employees/{emp['id']}/documents", headers=h)
        out["list"] = {"status": lst.status_code, "n": len(lst.json().get("data", [])) if lst.status_code == 200 else None}
        ready = await client.get("/health/ready")
        out["ready"] = {"status": ready.status_code, "body": ready.json().get("data")}
        batches = (await q("SELECT count(*) n FROM employee_import_batch WHERE company_id = :c", c=str(cid)))[0]["n"]
        rows_now = len(await doc_rows(cid))
        monkeypatch.undo()
        get_settings.cache_clear()
        objs_now = len(keys(prefix))
        rec(c, "storage endpoint unreachable (connection refused)", results=out, doc_rows_before=base_rows, doc_rows_after=rows_now, bucket_objects_before=base_objs, bucket_objects_after=objs_now, import_batches=batches)
        assert up.status_code >= 500 and up.status_code < 600 and up.json().get("error", {}).get("code"), out
        assert imp.status_code >= 500 and imp.status_code < 600
        assert rows_now == base_rows and objs_now == base_objs and batches == 0, "a failed storage write left rows/batches"
        assert dele.status_code >= 500 and rows_now == base_rows, "delete must not drop the row when the object could not be removed"
        for v in out.values():
            assert v.get("secs", 0) < 60
        # recovery: the same upload works once storage is back, nothing stuck
        again = await upload(client, h, emp["id"], "new.jpg", _JPEG_BYTES, "image/jpeg")
        assert again.status_code == 201
        assert len(await doc_rows(cid)) == base_rows + 1 and len(keys(prefix)) == base_objs + 1
    finally:
        monkeypatch.undo()
        get_settings.cache_clear()
        await _cleanup_import_tables(company_id=cid)
        await _cleanup_org_structure(company_id=cid)
        await _teardown(company_id=cid, user_id=uid)
        for k in keys(f"employee/{cid}/"):
            s3().delete_object(Bucket=get_settings().s3_bucket_documents, Key=k)


@pytest.mark.xfail(strict=True, reason="DEF-B7-01: object-store write/delete is not compensated when the database step fails (orphan object / dangling row)")
async def test_doc_store_001_interrupted_write_leaves_orphan_object_or_dangling_row(client: AsyncClient, seeded_plan_catalogue: None, monkeypatch: pytest.MonkeyPatch) -> None:
    """The service writes the OBJECT first and the ROW second (upload) and removes the OBJECT first and the ROW second (delete).
    Inject a database failure into the second step of each and look at what is left behind."""
    c = "DOC-STORE-001"
    from hrms.modules.employee.repository import EmployeeDocumentRepository as EmployeeRepository

    h, cid, uid = await _register_tenant(client)
    try:
        emp = await _create_employee(client, h)
        prefix = f"employee/{cid}/"
        orig_insert, orig_delete = EmployeeRepository.insert_document, EmployeeRepository.delete_document

        async def boom(*a: Any, **k: Any) -> Any:
            raise RuntimeError("simulated database failure")

        monkeypatch.setattr(EmployeeRepository, "insert_document", boom)
        r = await upload(client, h, emp["id"], "x.jpg", _JPEG_BYTES, "image/jpeg")
        rows, objs = await doc_rows(cid), keys(prefix)
        rec(c, "upload: database fails after the object was written", status=r.status_code, db_rows=len(rows), bucket_objects=len(objs), orphan_keys=objs)
        monkeypatch.setattr(EmployeeRepository, "insert_document", orig_insert)
        orphan_after_failed_upload = len(objs) - len(rows)

        good = await upload(client, h, emp["id"], "y.jpg", _JPEG_BYTES, "image/jpeg")
        assert good.status_code == 201
        doc_id = good.json()["data"]["id"]
        monkeypatch.setattr(EmployeeRepository, "delete_document", boom)
        d = await client.delete(f"/v1/employees/{emp['id']}/documents/{doc_id}", headers=h)
        rows2, objs2 = await doc_rows(cid), keys(prefix)
        dangling = [r_ for r_ in rows2 if r_["s3_key"] not in objs2]
        rec(c, "delete: database fails after the object was removed", status=d.status_code, db_rows=len(rows2), bucket_objects=len(objs2), dangling_rows=len(dangling))
        monkeypatch.setattr(EmployeeRepository, "delete_document", orig_delete)
        assert r.status_code >= 500 and d.status_code >= 500
        # the API contract: nothing visible to the client was changed, whichever inconsistency is left behind
        listing = await client.get(f"/v1/employees/{emp['id']}/documents", headers=h)
        rec(c, "FINDING-CANDIDATE storage/database consistency", orphan_objects_after_failed_upload=orphan_after_failed_upload, dangling_rows_after_failed_delete=len(dangling),
            list_status=listing.status_code, list_count=len(listing.json()["data"]))
        # Expected by the catalogue: no row/object for rejected uploads.  Record, then assert the strong form so a leak is a FAIL.
        assert orphan_after_failed_upload == 0, f"{orphan_after_failed_upload} orphan object(s) left in storage after a failed upload"
        assert len(dangling) == 0, f"{len(dangling)} document row(s) point at a deleted object after a failed delete"
    finally:
        monkeypatch.undo()
        await _teardown(company_id=cid, user_id=uid)
        for k in keys(f"employee/{cid}/"):
            s3().delete_object(Bucket=get_settings().s3_bucket_documents, Key=k)


# ====================================================================================== dependency-down paths
@pytest.fixture
def dead_redis(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in ("REDIS_URL", "CELERY_BROKER_URL", "CELERY_RESULT_BACKEND"):
        monkeypatch.setenv(var, "redis://127.0.0.1:1/0")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


async def test_job_health_001_redis_unavailable_ready_503_live_200(client: AsyncClient, dead_redis: None) -> None:
    c = "JOB-HEALTH-001"
    t0 = time.time()
    live = await client.get("/health/live")
    ready = await client.get("/health/ready")
    rec(c, "Redis unreachable (connection refused)", live=live.status_code, ready=ready.status_code, body=ready.json(), secs=round(time.time() - t0, 1))
    assert live.status_code == 200 and ready.status_code == 503
    assert ready.json()["data"]["redis"] != "ok" and ready.json()["data"]["database"] == "ok"


async def test_auth_rate_002_redis_unavailable_login_behaviour(client: AsyncClient, make_tenant_unverified: Any) -> None:
    """Observation test: what does login do when the rate-limit store is unreachable (fail-open or fail-closed)?"""
    c = "AUTH-RATE-002"
    email, pw = make_tenant_unverified
    os.environ["REDIS_URL"] = "redis://127.0.0.1:1/0"
    get_settings.cache_clear()
    try:
        t0 = time.time()
        r = await client.post("/v1/auth/login", json={"email": email, "password": pw})
        bad = await client.post("/v1/auth/login", json={"email": email, "password": "Wrong-Pass-1!"})
        secs = round(time.time() - t0, 1)
        attempts = []
        for i in range(7):
            attempts.append((await client.post("/v1/auth/login", json={"email": email, "password": f"Wrong-{i}-Pass!"})).status_code)
        locked = (await client.post("/v1/auth/login", json={"email": email, "password": pw})).status_code
        rec(c, "brute force with the rate-limit store down (account lockout is database-backed)", wrong_attempts=attempts, correct_password_after=locked)
        assert 423 in attempts and locked == 423, "per-account lockout must still work without Redis"
        rec(c, "login with the rate-limit store down", valid=[r.status_code, (r.json().get("error") or {}).get("code")], wrong=[bad.status_code, (bad.json().get("error") or {}).get("code")], secs=secs)
        assert r.status_code < 500 or r.json().get("error", {}).get("code"), "login must answer with a stable envelope"
        assert secs < 60
    finally:
        os.environ["REDIS_URL"] = ORIGINAL_REDIS
        get_settings.cache_clear()


ORIGINAL_REDIS = os.environ["REDIS_URL"]


@pytest.fixture
async def make_tenant_unverified(client: AsyncClient, seeded_plan_catalogue: None) -> Any:
    from tests.integration.modules.organisation.test_registration_flow import VALID_PASSWORD, _payload

    payload = _payload()
    r = await client.post("/v1/companies/register", json=payload)
    assert r.status_code == 201, r.text
    cid = r.json()["data"]["company_id"]
    async with get_session_factory()() as session:
        await session.execute(text('UPDATE "user" SET email_verified_at = now() WHERE email = :e'), {"e": payload["admin_email"]})
        uid = (await session.execute(text('SELECT id FROM "user" WHERE email = :e'), {"e": payload["admin_email"]})).scalar_one()
        await session.commit()
    yield payload["admin_email"], VALID_PASSWORD
    from uuid import UUID
    await _cleanup(company_id=UUID(cid), user_id=uid)


async def test_job_retry_001_enqueue_failure_on_import_upload_leaves_consistent_state(client: AsyncClient, seeded_plan_catalogue: None, monkeypatch: pytest.MonkeyPatch) -> None:
    """The import API stores the CSV, commits the batch row and THEN publishes the Celery task.  If the broker publish fails, what
    is left behind?  (mock of the publish step: kombu OperationalError; the broker itself is not touched)."""
    c = "JOB-RETRY-001"
    from kombu.exceptions import OperationalError as KombuOperationalError

    from hrms.modules.employee_import import tasks as it

    h, cid, uid = await _register_tenant(client)
    org = await _setup_org_structure(client, h)
    try:
        def refuse(*a: Any, **k: Any) -> None:
            raise KombuOperationalError("simulated broker outage")

        monkeypatch.setattr(it.process_batch, "apply_async", refuse)
        r = await client.post("/v1/employee-imports", headers=h, files={"file": ("employees.csv", _build_csv(org), "text/csv")})
        batches = await q("SELECT id::text id, status, s3_key FROM employee_import_batch WHERE company_id = :c", c=str(cid))
        objs = keys("")  # whole bucket in this disposable run
        rec(c, "broker publish fails after the batch row is committed", http=r.status_code, code=(r.json().get("error") or {}).get("code") if r.status_code >= 400 else None, batches=batches,
            bucket_objects=len(objs))
        listing = await client.get("/v1/employee-imports", headers=h) if False else None
        stuck = [b for b in batches if b["status"] in ("PENDING", "PROCESSING")]
        rec(c, "FINDING-CANDIDATE", stuck_batches=len(stuck), note="a PENDING batch with no queued task is only recovered by the reconciliation job/runbook, if one exists")
        assert r.status_code in (201, 202) or (500 <= r.status_code < 600 and r.json().get("error", {}).get("code"))
        # either the request failed AND no batch is left, or the request succeeded with a recoverable batch; a failed request with a live PENDING batch is a defect
        if r.status_code >= 500:
            assert not stuck, "request failed but a PENDING batch (plus its stored CSV) remains with no task to process it"
    finally:
        monkeypatch.undo()
        await _cleanup_import_tables(company_id=cid)
        await _cleanup_org_structure(company_id=cid)
        await _cleanup(company_id=cid, user_id=uid)
