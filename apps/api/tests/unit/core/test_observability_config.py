"""Static consistency of the observability deliverables (runs in CI without Prometheus/Grafana):
alert rules and dashboards may only reference series the code really exports, every alert has a
runbook anchor and a catalog entry, and the deployment files keep `/metrics` private."""

import json
import re
from pathlib import Path

import yaml
from prometheus_client import generate_latest

from hrms.core.observability import metrics as m
from hrms.core.observability import scrape

REPO = Path(__file__).resolve().parents[5]
PROM = REPO / "infra/monitoring/prometheus"
SEVERITIES = {"critical", "high", "warning"}


def exported_series() -> set[str]:
    names: set[str] = set()
    for metric in m.ALL_METRICS:
        # A labelled metric has no samples until first used, so derive the series names from its
        # type (what the exposition format will contain) rather than from `collect()`.
        base = metric._name  # noqa: SLF001
        suffixes = {
            "counter": ("_total",),
            "histogram": ("_bucket", "_sum", "_count"),
            "gauge": ("",),
        }[metric._type]  # noqa: SLF001
        names.update(base + suffix for suffix in suffixes)
    source = Path(scrape.__file__).read_text()
    names.update(re.findall(r'"(hrms_[a-z0-9_]+)"', source))
    # `_gauge(f"hrms_db_pool_{key}", ...)` is built from a literal tuple of suffixes
    names.update(f"hrms_db_pool_{k}" for k in ("size", "checked_out", "overflow", "capacity"))
    return names


def referenced_series(text: str) -> set[str]:
    return set(re.findall(r"\bhrms_[a-z0-9_]+", text))


def rules() -> list[dict[str, object]]:
    doc = yaml.safe_load((PROM / "alerts.yml").read_text())
    return [rule for group in doc["groups"] for rule in group["rules"]]


def test_alert_rules_only_reference_series_the_code_exports() -> None:
    exported = exported_series()
    missing = {
        (rule["alert"], name)
        for rule in rules()
        for name in referenced_series(str(rule["expr"]))
        if name not in exported
    }
    assert not missing, missing


def test_dashboards_only_reference_exported_series() -> None:
    exported = exported_series()
    for path in (REPO / "infra/monitoring/grafana/dashboards").glob("*.json"):
        doc = json.loads(path.read_text())
        assert doc["panels"], path
        text = " ".join(t["expr"] for p in doc["panels"] for t in p["targets"])
        assert referenced_series(text) <= exported, (path.name, referenced_series(text) - exported)


def test_every_alert_is_complete_documented_and_has_a_runbook_anchor() -> None:
    runbook = (REPO / "docs/operations/OBSERVABILITY_RUNBOOK.md").read_text()
    catalog = (REPO / "docs/operations/OBSERVABILITY_ALERT_CATALOG.md").read_text()
    names = [str(r["alert"]) for r in rules()]
    assert len(names) == len(set(names))
    for rule in rules():
        name = str(rule["alert"])
        assert rule["labels"]["severity"] in SEVERITIES, name  # type: ignore[index]
        assert "for" in rule and rule["annotations"]["summary"], name  # type: ignore[index]
        anchor = str(rule["annotations"]["runbook"]).split("#")[1]  # type: ignore[index]
        assert f'<a id="{anchor}"></a>' in runbook, (name, anchor)
        assert f"`{name}`" in catalog, name


def test_alert_expressions_never_group_by_identifying_labels() -> None:
    for rule in rules():
        for forbidden in ("company", "employee", "user", "email", "request_id", "task_id"):
            assert forbidden not in str(rule["expr"]), (rule["alert"], forbidden)


def test_runtime_exposition_contains_no_forbidden_label_names() -> None:
    body = generate_latest().decode()
    for forbidden in ("company_id", "employee_id", "user_id", "request_id", "email"):
        assert f'{forbidden}="' not in body


def test_prometheus_config_scrapes_only_the_authenticated_private_endpoint() -> None:
    cfg = yaml.safe_load((PROM / "prometheus.yml").read_text())
    api = next(j for j in cfg["scrape_configs"] if j["job_name"] == "hrms-api")
    assert api["metrics_path"] == "/metrics"
    assert api["authorization"]["credentials_file"].endswith("metrics_token")
    assert api["static_configs"][0]["targets"] == ["api:8000"]


def test_nginx_never_proxies_metrics_and_compose_shares_the_metrics_volume() -> None:
    nginx = (REPO / "infra/nginx/conf.d/hrms.conf.template").read_text()
    assert re.search(r"location = /metrics \{\s*return 404;", nginx)
    compose = yaml.safe_load((REPO / "docker-compose.prod.yml").read_text())
    for service in ("api", "worker", "beat"):
        spec = compose["services"][service]
        assert "metrics_mp:/app/metrics" in spec["volumes"], service
        assert spec["environment"]["PROMETHEUS_MULTIPROC_DIR"] == "/app/metrics", service
    assert "ports" not in compose["services"]["api"]


def test_optional_monitoring_stack_publishes_no_ports_and_caps_resources() -> None:
    compose = yaml.safe_load((REPO / "docker-compose.monitoring.yml").read_text())
    for name, spec in compose["services"].items():
        assert "ports" not in spec, name
        assert spec["mem_limit"], name
    command = " ".join(compose["services"]["prometheus"]["command"])
    assert "retention.size" in command and "retention.time" in command
