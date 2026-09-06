"""Unit tests for the approval-chain stage resolution (`leave/approval_chain.py`,
LEAVE_DECISION_LOG.md LD-05/LD-23) — no DB/HTTP, pure functions only."""

from uuid import uuid4

from hrms.modules.leave.approval_chain import effective_stage_sequence, next_approval_stage

MANAGER = uuid4()
HOD = uuid4()


def test_manager_chain_with_resolved_manager_is_single_stage() -> None:
    assert effective_stage_sequence(
        "MANAGER", manager_id=MANAGER, department_head_id=None
    ) == ("MANAGER",)
    assert (
        next_approval_stage(
            "MANAGER", "MANAGER", manager_id=MANAGER, department_head_id=None
        )
        is None
    )


def test_manager_chain_with_no_manager_falls_back_to_hr() -> None:
    assert effective_stage_sequence(
        "MANAGER", manager_id=None, department_head_id=None
    ) == ("HR",)
    assert (
        next_approval_stage("MANAGER", "HR", manager_id=None, department_head_id=None) is None
    )


def test_manager_then_hr_two_stage_sequence() -> None:
    assert effective_stage_sequence(
        "MANAGER_THEN_HR", manager_id=MANAGER, department_head_id=None
    ) == ("MANAGER", "HR")
    assert (
        next_approval_stage(
            "MANAGER_THEN_HR", "MANAGER", manager_id=MANAGER, department_head_id=None
        )
        == "HR"
    )
    assert (
        next_approval_stage(
            "MANAGER_THEN_HR", "HR", manager_id=MANAGER, department_head_id=None
        )
        is None
    )


def test_manager_then_hr_no_manager_collapses_to_single_hr_stage() -> None:
    assert effective_stage_sequence(
        "MANAGER_THEN_HR", manager_id=None, department_head_id=None
    ) == ("HR",)
    assert (
        next_approval_stage(
            "MANAGER_THEN_HR", "HR", manager_id=None, department_head_id=None
        )
        is None
    )


def test_three_stage_chain_all_resolved() -> None:
    chain = "MANAGER_THEN_HOD_THEN_HR"
    assert effective_stage_sequence(
        chain, manager_id=MANAGER, department_head_id=HOD
    ) == ("MANAGER", "HOD", "HR")
    next_stage = next_approval_stage
    assert next_stage(chain, "MANAGER", manager_id=MANAGER, department_head_id=HOD) == "HOD"
    assert next_stage(chain, "HOD", manager_id=MANAGER, department_head_id=HOD) == "HR"
    assert next_stage(chain, "HR", manager_id=MANAGER, department_head_id=HOD) is None


def test_three_stage_chain_skips_unresolved_hod() -> None:
    chain = "MANAGER_THEN_HOD_THEN_HR"
    assert effective_stage_sequence(
        chain, manager_id=MANAGER, department_head_id=None
    ) == ("MANAGER", "HR")
    assert (
        next_approval_stage(chain, "MANAGER", manager_id=MANAGER, department_head_id=None)
        == "HR"
    )


def test_three_stage_chain_skips_unresolved_manager() -> None:
    chain = "MANAGER_THEN_HOD_THEN_HR"
    assert effective_stage_sequence(
        chain, manager_id=None, department_head_id=HOD
    ) == ("HOD", "HR")
    assert next_approval_stage(chain, "HOD", manager_id=None, department_head_id=HOD) == "HR"


def test_three_stage_chain_neither_resolved_falls_back_to_hr() -> None:
    chain = "MANAGER_THEN_HOD_THEN_HR"
    assert effective_stage_sequence(chain, manager_id=None, department_head_id=None) == ("HR",)
    assert next_approval_stage(chain, "HR", manager_id=None, department_head_id=None) is None


def test_hr_chain_is_always_single_stage() -> None:
    assert effective_stage_sequence("HR", manager_id=MANAGER, department_head_id=HOD) == ("HR",)


def test_auto_chain_has_no_stages() -> None:
    assert effective_stage_sequence("AUTO", manager_id=None, department_head_id=None) == ()
