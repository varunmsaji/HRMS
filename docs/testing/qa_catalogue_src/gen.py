import ast, csv, glob, json, os, re, sys, collections
sys.path.insert(0, os.path.dirname(__file__))
import qa_lib
import cases_1, cases_2, cases_3  # noqa: F401  (executing them fills qa_lib.CASES)

REPO = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))
OUT = REPO + "/docs/testing"
CASES = qa_lib.CASES
import results_phase3
for _c in CASES:
    _c.setdefault('command', '')
    _o = dict(results_phase3.OVERRIDES.get(_c['case_id'], {}))
    for _k, _v in (('amb', 'ambiguity'), ('defect', 'defect_ref')):
        if _k in _o: _o[_v] = _o.pop(_k)
    _c.update(_o)

# ---------- live register
live = {r["id"]: r for r in csv.DictReader(open(OUT + "/qa_live_2026-10-25/register.csv"))}
WEAK = {  # assertion weaknesses found by reading the scripts (verified by reading, see QA_TRACEABILITY_MATRIX)
    "LV-28": "VACUOUS (`or True` in j3_leave.py:61) - cannot fail",
    "ATT-15": "DESTRUCTIVE probe: unscoped UPDATE on punch inside a committing connection if it succeeds",
    "EMP-09": "DISJUNCTIVE (422 OR clamped)", "EMP-13": "DISJUNCTIVE (400/409/412/422/428)",
    "LV-11": "DISJUNCTIVE (rejected OR 0-day)", "TEN-08": "DISJUNCTIVE (200/400/403/422)",
    "AUTH-14": "DISJUNCTIVE (401 OR 403)", "DEP-07": "DISJUNCTIVE (200 OR 503)", "TEN-10": "VACUOUS-IF-EMPTY lists",
    "SWP-02": "TECHNICAL ONLY (no 5xx)", "SWP-03": "TECHNICAL ONLY (no 5xx)", "SWP-08": "TECHNICAL ONLY (no 5xx)", "SWP-09": "TECHNICAL ONLY (no 5xx)",
    "RLS-06": "READ-ONLY privilege smoke", "AUD-01": "WEAK: >=1 audit row containing 'EMPLOYEE'",
}
BIZ = re.compile(r"balance|debit|ledger|rows?\b|invariant|exactly|punch(es)? |created|duplicate|restor|double|payslip|state|unchanged|invoice|run|DRAFT|accounting|employees", re.I)

def live_class(i):
    c = live[i]["check"]
    if i in ("LV-28",): return "NONE_VACUOUS"
    if i.startswith(("SWP", "DEP", "AUTH", "RBAC", "TEN", "DOC-0", "RLS")): return "TECHNICAL_OR_SECURITY_RESPONSE" if not re.search(r"row|unchanged|no .*left|exact", c, re.I) else "BUSINESS_OR_STATE"
    return "BUSINESS_OR_STATE" if BIZ.search(c) else "TECHNICAL_OR_SECURITY_RESPONSE"

# ---------- file -> cases
def cases_for(path):
    hit = [c["case_id"] for c in CASES if any(g and g in path for g in c["test_globs"].split(";"))]
    return hit

# ---------- backend tests (AST)
API = REPO + "/apps/api/tests"
EXT = {"MINIO_S3": r"storage|boto|minio|S3_", "REDIS": r"redis", "DOCKER_SUBPROCESS": r"docker|subprocess", "CELERY": r"celery", "DB": r"DATABASE_URL|get_session_factory|AsyncSession|session\.execute|create_async_engine|engine"}
rows, unmapped_files = [], []
nfun = 0
for p in sorted(glob.glob(API + "/**/test_*.py", recursive=True)):
    rel = "apps/api/tests/" + os.path.relpath(p, API)
    src = open(p).read()
    tree = ast.parse(src)
    ext = [k for k, rx in EXT.items() if re.search(rx, src, re.I)]
    tier = "unit" if "/unit/" in rel else "security" if "/security/" in rel else "integration"
    cs = cases_for(rel)
    if not cs: unmapped_files.append(rel)
    skip = "skipif" in src or "pytest.skip" in src
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test_"):
            seg = ast.get_source_segment(src, node) or ""
            asserts = [a for a in ast.walk(node) if isinstance(a, ast.Assert)]
            atxt = " ".join(ast.get_source_segment(src, a) or "" for a in asserts)
            para = any("parametrize" in (ast.get_source_segment(src, d) or "") for d in node.decorator_list)
            if not asserts and "raises" not in seg: cls = "NO_ASSERT_OR_RAISES_ONLY"
            elif tier == "unit": cls = "UNIT_LOGIC"
            elif atxt and all(("status_code" in (ast.get_source_segment(src, a) or "")) for a in asserts): cls = "API_STATUS_ONLY"
            else: cls = "API_BODY_OR_STATE"
            rows.append(dict(kind="backend_test", file=rel, identifier=node.name, line=node.lineno, tier=tier,
                             case_ids=";".join(cs) or "UNMAPPED", primary_case=cs[0] if cs else "UNMAPPED",
                             assertion_class_inferred=cls, parametrized=("Y" if para else "N"), file_has_skip=("Y" if skip else "N"),
                             external_deps=",".join(ext), live_status="", notes=""))
            nfun += 1

# ---------- web
WEB = REPO + "/apps/web"
webfiles = []
for p in sorted(glob.glob(WEB + "/src/**/*.test.ts*", recursive=True)):
    rel = "apps/web/" + os.path.relpath(p, WEB); s = open(p).read()
    n = len(re.findall(r"^\s*(?:it|test)(?:\.each\([^)]*\))?\(", s, re.M)); cs = cases_for(rel)
    webfiles.append((rel, n, cs))
    rows.append(dict(kind="web_test_file", file=rel, identifier=f"{n} it/test blocks (static count)", line="", tier="web-vitest",
                     case_ids=";".join(cs) or "UNMAPPED", primary_case=cs[0] if cs else "UNMAPPED", assertion_class_inferred="UNIT_UI_NOT_READ",
                     parametrized="", file_has_skip="", external_deps="", live_status="", notes="not executed in this phase (inherited: 522 passed)"))
MOB = REPO + "/apps/mobile"
mobfiles = []
for p in sorted(glob.glob(MOB + "/test/**/*_test.dart", recursive=True)):
    rel = "apps/mobile/" + os.path.relpath(p, MOB); s = open(p).read()
    n = len(re.findall(r"^\s*(?:testWidgets|test)\(", s, re.M)); cs = cases_for(rel)
    mobfiles.append((rel, n, cs))
    rows.append(dict(kind="mobile_test_file", file=rel, identifier=f"{n} test/testWidgets (static count)", line="", tier="flutter",
                     case_ids=";".join(cs) or "UNMAPPED", primary_case=cs[0] if cs else "UNMAPPED", assertion_class_inferred="NOT_READ",
                     parametrized="", file_has_skip="", external_deps="LIVE_BACKEND" if "/live/" in rel else "",
                     live_status="BLOCKED", notes="Flutter SDK absent; never executed in QA pass"))

# ---------- live checks
live_to_cases = collections.defaultdict(list)
for c in CASES:
    for i in filter(None, c["live_checks"].split(";")): live_to_cases[i].append(c["case_id"])
script_of = {}
for f in sorted(glob.glob(OUT + "/qa_live_2026-10-25/*.py")):
    s = open(f).read()
    for m in re.finditer(r"['\"]([A-Z]{2,5}-\d+)['\"]", s): script_of.setdefault(m.group(1), os.path.basename(f))
for i in ("SWP-02", "SWP-03"): script_of[i] = "j9_sweep.py"
unmapped_live = []
for i, r in live.items():
    cs = live_to_cases.get(i, [])
    if not cs: unmapped_live.append(i)
    rows.append(dict(kind="live_check", file="docs/testing/qa_live_2026-10-25/" + script_of.get(i, "?"), identifier=i, line="", tier="live-blackbox",
                     case_ids=";".join(cs) or "UNMAPPED", primary_case=cs[0] if cs else "UNMAPPED",
                     assertion_class_inferred=live_class(i), parametrized="", file_has_skip="",
                     external_deps="PRIVATE_STACK", live_status=r["status"], notes=WEAK.get(i, "")))

# ---------- case enrichment
bt_by_case = collections.defaultdict(set)
for r in rows:
    if r["kind"] in ("backend_test", "web_test_file", "mobile_test_file"):
        for c in r["case_ids"].split(";"): bt_by_case[c].add(r["file"])
fn_by_case = collections.Counter()
for r in rows:
    if r["kind"] == "backend_test":
        for c in r["case_ids"].split(";"): fn_by_case[c] += 1
for c in CASES:
    ls = [i for i in c["live_checks"].split(";") if i]
    stt = collections.Counter(live[i]["status"] for i in ls if i in live)
    if not ls: c["inherited_result"] = "NONE"
    elif stt.get("FAIL"): c["inherited_result"] = "INHERITED_FAIL (" + ",".join(f"{k}={v}" for k, v in stt.items()) + ")"
    elif stt.get("INFO"): c["inherited_result"] = "INHERITED_PASS_WITH_INFO (" + ",".join(f"{k}={v}" for k, v in stt.items()) + ")"
    else: c["inherited_result"] = f"INHERITED_PASS ({stt.get('PASS',0)} live checks)"
    c["existing_test_files"] = len(bt_by_case.get(c["case_id"], ()))
    c["existing_test_functions"] = fn_by_case.get(c["case_id"], 0)
    if c["status"] == "NOT_RUN" and not c["actual"]:
        bits = []
        if ls: bits.append(c["inherited_result"])
        if c["existing_test_files"]: bits.append(f"{c['existing_test_files']} existing automated test file(s) linked (inherited in 3,198-pass regression; not re-run)")
        c["actual"] = "NOT EXECUTED in this phase. " + "; ".join(bits) if bits else "NOT EXECUTED; no existing coverage found."
    if c["automation"] in ("AUTOMATED", "AUTOMATED+LIVE_SCRIPT") and not c["existing_test_files"] and not ls:
        c["automation"] = "NOT_AUTOMATED"
    DEF = {
      "Auth": ("session / refresh_token rows reflect each action (revoked_at set on logout, reuse, reset); no plaintext password or token in any column or log line", "no user enumeration; no secret/token echoed beyond the intended field; no 5xx or stack trace"),
      "Tenant isolation": ("every row read/written carries the caller's company_id; hash of the other tenant's rows identical before and after", "no 2xx carrying foreign data; denial does not reveal existence differently from a missing id"),
      "RBAC": ("denied actions leave 0 new/changed rows and 0 audit rows for the mutation", "no privilege escalation path; no 2xx for the forbidden action"),
      "Organisation": ("unique/exclusion constraints hold; version/If-Match counter advances once per change", "duplicate/overlapping input creates no row"),
      "Employee": ("one row per logical entity; effective-dated rows non-overlapping; PII columns encrypted at rest; audit_log row per mutation", "failed validation leaves no partial rows"),
      "Employee import": ("batch counters (total/succeeded/failed) equal row-level facts; employee count equals succeeded rows", "bad file creates no batch row, no S3 object, no employees"),
      "Documents": ("document row <-> storage object 1:1, key prefixed by tenant, hash equal", "rejected upload leaves no row and no object; no cross-tenant URL issued"),
      "Attendance": ("raw punch rows are only ever inserted; one row per (employee, idempotency_key)", "no row rewritten or deleted; no future-dated or foreign-tenant punch accepted"),
      "Attendance calc": ("attendance_day is a deterministic function of punches + versions used; locked days unchanged", "no silent PRESENT for missing data; no recalculation of locked days"),
      "Attendance regularization": ("approved request writes exactly the requested punches once; request status transitions are monotonic", "rejected/duplicate decisions write no punches"),
      "Shifts & rosters": ("published versions immutable; no overlapping effective ranges (exclusion constraint)", "invalid or overlapping definitions create no rows"),
      "Attendance policies": ("published versions immutable; assignment resolution stable for a given date", "no retroactive change to already-calculated locked days"),
      "Attendance periods": ("every calendar day in exactly one bucket; paid+lop+unpaid_off = payable; summaries frozen on CLOSED", "no mutation of dates inside a CLOSED period"),
      "Overtime": ("overtime_record minutes/class per formula; decided records frozen", "no OT for ineligible/leave days; no self-approval"),
      "Background jobs": ("persisted result rows exist exactly once per logical unit of work; no stuck PENDING/PROCESSING rows", "re-run/concurrent run changes nothing further; no half-applied effect"),
      "Observability & core": ("log/audit records exist for the action; redaction applied", "no PII/secret/token in logs; no writes outside the designated sink"),
      "Leave": ("balance == sum(leave_ledger) after every step; ledger rows append-only; application state transitions monotonic", "no double debit/credit; no negative balance beyond policy floor; no change on rejected request"),
      "Payroll": ("run lines reproducible from the snapshot; finalised rows immutable; one payslip per employee per run; Σ components = gross", "no unrounded/rounded drift outside the signed rule; no transition out of order; no payout from an unclosed period"),
      "Platform console": ("company.status and platform_audit_log row per action (append-only); company audit_log mirrors", "tenant tokens never accepted on platform routes and vice versa"),
      "Web": ("UI numbers equal API numbers equal DB values for the same record", "no duplicate submits; no raw server errors shown to the user"),
      "Mobile": ("UI numbers equal API numbers equal DB values for the same record", "no duplicate submits; secure token storage only"),
      "Environment & tooling": ("shared resources (hrms_dev, shared Redis index 0, hrms-minio, port 8000) unchanged", "no destructive action without explicit opt-in"),
    }
    if not c["db_invariants"].strip() and c["module"] in DEF:
        c["db_invariants"] = "[module default - refine at execution] " + DEF[c["module"]][0]
    if not c["negative_assertions"].strip() and c["module"] in DEF:
        c["negative_assertions"] = "[module default - refine at execution] " + DEF[c["module"]][1]
    if not c["db_invariants"].strip(): c["db_invariants"] = "n/a (not executable)"
    if not c["negative_assertions"].strip(): c["negative_assertions"] = "n/a (not executable)"
    if not c["actual"].strip():
        c["actual"] = {"BLOCKED": "BLOCKED: Flutter SDK absent (VERIFIED 2026-10-25); never executed.", "NOT_APPLICABLE": "Not applicable: feature not implemented / no UI / excluded by instruction (see rule_source and requirement)."}.get(c["status"], "NOT EXECUTED in this phase.")
    if not c["evidence"].strip():
        c["evidence"] = "NONE_YET - to be written under qa_runs/<RUN_ID>/" + c["case_id"] + ".jsonl when executed" if c["status"] in ("NOT_RUN", "BLOCKED") else "n/a"
    if not c["preconditions"].strip():
        e = c["env_required"]
        c["preconditions"] = ("None (pure logic)" if e.startswith("UNIT") and "PRIVATE" not in e else
                              "Operator access to the host; read-only commands" if e == "HOST" else
                              "n/a (not executable)" if c["status"] == "NOT_APPLICABLE" else
                              "Private disposable stack provisioned per QA_TEST_STRATEGY.md section 6 (DB at migration head, private Redis/MinIO, logging email sender); synthetic tenants created by the case itself")
    c["evidence"] = c["evidence"] or ("docs/testing/qa_live_2026-10-25/register.csv#" + ls[0] if ls else "")

FIELDS = ["case_id", "module", "feature", "requirement", "rule_source", "test_type", "priority", "preconditions", "role_tenant", "test_data",
          "steps", "command", "expected", "actual", "inherited_result", "db_invariants", "negative_assertions", "status", "automation", "evidence",
          "defect_ref", "ambiguity", "env_required", "shared_resource_risk", "live_checks", "existing_test_files", "existing_test_functions", "test_globs"]
with open(OUT + "/QA_TEST_CASES.csv", "w", newline="") as f:
    w = csv.DictWriter(f, FIELDS, extrasaction="ignore"); w.writeheader(); w.writerows(CASES)
MF = ["kind", "file", "identifier", "line", "tier", "case_ids", "primary_case", "assertion_class_inferred", "parametrized", "file_has_skip", "external_deps", "live_status", "notes"]
with open(OUT + "/QA_TEST_MAP.csv", "w", newline="") as f:
    w = csv.DictWriter(f, MF); w.writeheader(); w.writerows(rows)

# ---------- stats
st = {}
st["cases_total"] = len(CASES)
st["cases_by_status"] = collections.Counter(c["status"] for c in CASES)
st["cases_by_module"] = collections.Counter(c["module"] for c in CASES)
st["cases_by_priority"] = collections.Counter(c["priority"] for c in CASES)
st["cases_by_type"] = collections.Counter(c["test_type"] for c in CASES)
act = [c for c in CASES if c["status"] != "NOT_APPLICABLE"]
st["denominator_active"] = len(act)
st["with_live"] = sum(1 for c in act if c["live_checks"])
st["with_tests"] = sum(1 for c in act if c["existing_test_files"])
st["with_either"] = sum(1 for c in act if c["live_checks"] or c["existing_test_files"])
st["with_neither"] = [c["case_id"] for c in act if not (c["live_checks"] or c["existing_test_files"])]
st["with_live_and_test"] = sum(1 for c in act if c["live_checks"] and c["existing_test_files"])
st["backend_files"] = len([r for r in rows if r["kind"] == "backend_test"] and {r["file"] for r in rows if r["kind"] == "backend_test"})
st["backend_functions"] = nfun
st["backend_funcs_by_tier"] = collections.Counter(r["tier"] for r in rows if r["kind"] == "backend_test")
st["backend_funcs_by_class"] = collections.Counter(r["assertion_class_inferred"] for r in rows if r["kind"] == "backend_test")
st["backend_param"] = sum(1 for r in rows if r["kind"] == "backend_test" and r["parametrized"] == "Y")
st["unmapped_backend_files"] = unmapped_files
st["unmapped_live"] = unmapped_live
st["web_files"] = len(webfiles); st["web_blocks"] = sum(n for _, n, _ in webfiles)
st["web_unmapped"] = [f for f, n, c in webfiles if not c]
st["mobile_files"] = len(mobfiles); st["mobile_blocks"] = sum(n for _, n, _ in mobfiles)
st["mobile_unmapped"] = [f for f, n, c in mobfiles if not c]
st["live_by_class"] = collections.Counter(r["assertion_class_inferred"] for r in rows if r["kind"] == "live_check")
st["live_weak"] = {k: v for k, v in WEAK.items()}
st["ext_dep_files"] = collections.Counter()
for r in rows:
    if r["kind"] == "backend_test":
        pass
st["files_with_ext"] = {}
seen = set()
for r in rows:
    if r["kind"] == "backend_test" and r["file"] not in seen:
        seen.add(r["file"])
        for d in r["external_deps"].split(","):
            if d: st["files_with_ext"].setdefault(d, []).append(r["file"])
json.dump(st, open(os.path.dirname(__file__) + "/stats.json", "w"), indent=1, default=lambda o: dict(o))
print(json.dumps({k: v for k, v in st.items() if k not in ("files_with_ext",)}, indent=1, default=lambda o: dict(o))[:6000])
