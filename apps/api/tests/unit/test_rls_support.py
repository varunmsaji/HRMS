"""Pure logic of the two-role harness guard (`tests/rls_support.py`); no database."""

from tests import rls_support

OK = {
    "name": "hrms_app",
    "rolsuper": False,
    "rolbypassrls": False,
    "rolcreaterole": False,
    "rolcreatedb": False,
    "rolreplication": False,
}


def test_unprivileged_role_passes() -> None:
    assert rls_support.unprivileged_problems(OK) == []


def test_each_dangerous_attribute_is_reported() -> None:
    for flag in ("rolsuper", "rolbypassrls", "rolcreaterole", "rolcreatedb", "rolreplication"):
        problems = rls_support.unprivileged_problems({**OK, flag: True})
        assert len(problems) == 1 and "hrms_app" in problems[0], flag


def test_an_unknown_attribute_state_fails_closed() -> None:
    attrs = {k: v for k, v in OK.items() if k != "rolbypassrls"}
    assert rls_support.unprivileged_problems(attrs)


def test_runtime_url_defaults_to_the_app_role_on_the_same_database() -> None:
    env = {"DATABASE_URL": "postgresql://hrms:secret@127.0.0.1:15432/hrms_qa_x?sslmode=disable"}
    assert (
        rls_support.runtime_url(env)
        == "postgresql://hrms_app:hrms_app_dev_password@127.0.0.1:15432/hrms_qa_x"
    )


def test_explicit_runtime_url_wins_and_query_is_dropped() -> None:
    env = {
        "DATABASE_URL": "postgresql://hrms:p@127.0.0.1:1/db",
        "HRMS_APP_DATABASE_URL": "postgresql://hrms_app:z@127.0.0.1:1/db?x=1",
    }
    assert rls_support.runtime_url(env) == "postgresql://hrms_app:z@127.0.0.1:1/db"
    assert rls_support.admin_url(env) == "postgresql://hrms:p@127.0.0.1:1/db"


def test_runtime_url_must_target_the_same_database_as_admin_with_a_different_user() -> None:
    admin = "postgresql://hrms:a@127.0.0.1:15432/hrms_qa_x"
    assert (
        rls_support.target_problems(admin, "postgresql://hrms_app:b@127.0.0.1:15432/hrms_qa_x")
        == []
    )
    assert rls_support.target_problems(admin, "postgresql://hrms_app:b@127.0.0.1:15432/other")
    assert rls_support.target_problems(admin, "postgresql://hrms_app:b@127.0.0.1:5433/hrms_qa_x")
    assert rls_support.target_problems(admin, "postgresql://hrms_app:b@10.0.0.9:15432/hrms_qa_x")
    same_user = rls_support.target_problems(admin, "postgresql://hrms:b@127.0.0.1:15432/hrms_qa_x")
    assert same_user == ["runtime and admin URLs use the same user"]
    # Problems never echo a URL or credential.
    assert all("@" not in p and ":a" not in p for p in same_user)
