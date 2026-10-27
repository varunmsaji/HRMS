"""Runs INSIDE the QA runner. Proves (a) strict target allow-list, (b) the sandbox network namespace
has only loopback, (c) nothing shared is reachable, (d) no Docker socket / stray env files /
proxy variables. Exit 0 only if every check holds. Writes /artifacts/preflight_isolation.json."""
import json
import os
import socket
import sys
from urllib.parse import urlsplit

sys.path.insert(0, ".")
sys.path.insert(0, "src")
from tests import isolation_guard  # noqa: E402
from hrms.core.config.settings import get_settings  # noqa: E402

run = os.environ["QA_RUN_ID"]
checks: list[dict] = []


def chk(name, ok, detail=""):
    checks.append({"check": name, "ok": bool(ok), "detail": str(detail)})


os.environ["HRMS_QA_STRICT"] = "1"
problems = isolation_guard.strict_problems(os.environ)
chk("strict allow-list (db names, loopback private ports, providers, empty .env)", not problems, problems)

S = get_settings()
eff = {
    "database": f"{urlsplit(S.database_url).hostname}:{urlsplit(S.database_url).port}/{urlsplit(S.database_url).path.lstrip('/')}",
    "redis": f"{urlsplit(S.redis_url).hostname}:{urlsplit(S.redis_url).port}",
    "celery_broker": f"{urlsplit(S.celery_broker).hostname}:{urlsplit(S.celery_broker).port}",
    "s3": f"{urlsplit(S.s3_endpoint_url).hostname}:{urlsplit(S.s3_endpoint_url).port}",
    "email_provider": S.email_provider,
    "face_provider": S.face_verification_provider,
}
chk("Settings (after .env + env) resolve to the same private targets",
    eff["database"] == f"127.0.0.1:{urlsplit(os.environ['DATABASE_URL']).port}/hrms_qa_{run.replace('-', '_')}"
    and eff["redis"] == f"127.0.0.1:{urlsplit(os.environ['REDIS_URL']).port}" and eff["celery_broker"] == eff["redis"]
    and eff["s3"] == f"127.0.0.1:{urlsplit(os.environ['S3_ENDPOINT_URL']).port}", eff)
chk("email provider logging, face disabled", eff["email_provider"] == "logging" and eff["face_provider"] == "disabled")

# --- network namespace: loopback only, no routes -------------------------------------------------
ifaces = [l.split(":")[0].strip() for l in open("/proc/net/dev").read().splitlines()[2:]]
routes = [l for l in open("/proc/net/route").read().splitlines()[1:] if l.strip()]
chk("only the loopback interface exists", ifaces == ["lo"], ifaces)
chk("routing table is empty (no gateway, no egress)", routes == [], routes)

# --- masked env files / docker socket / proxies / mounts ------------------------------------------
repo = os.path.abspath(os.path.join(os.getcwd(), "..", ".."))
leaks = []
for root, dirs, files in os.walk(repo):
    dirs[:] = [d for d in dirs if d not in ("node_modules", ".venv", ".git")]
    for f in files:
        if (f == ".env" or f.startswith(".env.")) and not f.endswith((".example", ".template")):
            p = os.path.join(root, f)
            if os.path.getsize(p) > 0:
                leaks.append(p)
chk("every non-example .env* file in the repo is masked (size 0)", not leaks, leaks)
chk("no docker socket in the sandbox", not os.path.exists("/var/run/docker.sock") and not os.path.exists("/run/docker.sock"))
chk("no proxy variables", not [k for k in os.environ if k.lower().endswith("_proxy")])
mounts = [l.split()[4] for l in open("/proc/self/mountinfo").read().splitlines()]
chk("no docker.sock / host root mounted", not [m for m in mounts if "docker.sock" in m or m in ("/host", "/hostfs")], [m for m in mounts if "docker" in m])


def can_connect(host, port, timeout=1.0):
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


own = [(urlsplit(os.environ["DATABASE_URL"]).port, "postgres"), (urlsplit(os.environ["REDIS_URL"]).port, "redis"), (urlsplit(os.environ["S3_ENDPOINT_URL"]).port, "minio")]
for port, name in own:
    chk(f"reach own {name} on 127.0.0.1:{port}", can_connect("127.0.0.1", port))
own_ports = {p for p, _ in own}
probes = [("127.0.0.1", p) for p in (5432, 5433, 6379, 6380, 9000, 9001, 8000, 3306, 631, 3000) if p not in own_ports]
for ip in filter(None, os.environ.get("SHARED_IPS", "").split(",")):
    probes += [(ip, p) for p in (5432, 6379, 9000)]
for ip in filter(None, os.environ.get("HOST_IPS", "").split(",")):
    probes += [(ip, p) for p in (5433, 6380, 9000, 8000, 5432, 6379)]
probes += [("172.17.0.1", p) for p in (5433, 6380, 9000, 8000)] + [("1.1.1.1", 443), ("8.8.8.8", 53)]
for host, port in probes:
    chk(f"UNREACHABLE {host}:{port}", not can_connect(host, port))
names = [n for n in os.environ.get("SHARED_NAMES", "").split(",") if n]
for n in names + ["host.docker.internal", "github.com"]:
    try:
        socket.gethostbyname(n); resolved = True
    except OSError:
        resolved = False
    chk(f"name does not resolve: {n}", not resolved)

hold = os.environ.get("QA_HOLD_ID", "")
out = {"run": run, "hold_container_id": hold, "effective": eff, "probes": len(probes), "checks": checks, "all_ok": all(c["ok"] for c in checks)}
os.makedirs("/artifacts", exist_ok=True)
json.dump(out, open("/artifacts/preflight_isolation.json", "w"), indent=1)
for c in checks:
    print(("PASS " if c["ok"] else "FAIL ") + c["check"] + ("" if c["ok"] else f"  [{c['detail']}]"))
print("ISOLATION", "PROVED" if out["all_ok"] else "NOT PROVED")
sys.exit(0 if out["all_ok"] else 1)
