"""Leave approval-chain stage resolution (LEAVE_DECISION_LOG.md LD-05/LD-23).

Pure functions only — no I/O, no session. `LeaveApplicationService` resolves manager/department-
head identities (or their absence) itself, then calls these to decide the starting stage at
submit time and the next stage at approval time.

Generalizes the fallback-to-HR behavior LD-05 already established for `MANAGER`/
`MANAGER_THEN_HR` (resolution failure never blocks submission and never auto-approves — it
routes to HR instead) to the new three-stage `MANAGER_THEN_HOD_THEN_HR` chain: any stage whose
reviewer can't be identified is dropped from *this application's* effective sequence, and HR is
always the guaranteed backstop.
"""

from uuid import UUID

# The nominal, full stage list per chain type. `AUTO`/unknown chains have no approval stage at
# all — callers branch on that before reaching these sequences.
_STAGE_SEQUENCES: dict[str, tuple[str, ...]] = {
    "MANAGER": ("MANAGER",),
    "MANAGER_THEN_HR": ("MANAGER", "HR"),
    "MANAGER_THEN_HOD_THEN_HR": ("MANAGER", "HOD", "HR"),
    "HR": ("HR",),
}


def effective_stage_sequence(
    approval_chain: str,
    *,
    manager_id: UUID | None,
    department_head_id: UUID | None,
) -> tuple[str, ...]:
    """This specific application's stage sequence — the nominal sequence for `approval_chain`
    with any identity-requiring stage dropped if it didn't resolve. `HR` never requires an
    identity (a company-wide permission grant, not a specific person), so it's always kept.

    Falls back to a single `("HR",)` stage if every identity-requiring stage in the nominal
    sequence dropped out — even for the plain `MANAGER` chain, which has no `HR` stage
    nominally: with no manager on record, HR is this application's only possible reviewer
    (LD-05's original "resolution failure routes to HR" behavior, preserved exactly)."""
    nominal = _STAGE_SEQUENCES.get(approval_chain, ())
    if not nominal:
        return ()

    resolved = {"MANAGER": manager_id is not None, "HOD": department_head_id is not None}
    filtered = tuple(stage for stage in nominal if resolved.get(stage, True))
    return filtered if filtered else ("HR",)


def next_approval_stage(
    approval_chain: str,
    current_stage: str,
    *,
    manager_id: UUID | None,
    department_head_id: UUID | None,
) -> str | None:
    """The stage after `current_stage` in this application's effective sequence, or `None` if
    `current_stage` is final. Recomputes the same sequence `effective_stage_sequence` would have
    produced at submit time from the two identities snapshotted on the row — deterministic, no
    re-resolution against current org-chart state."""
    sequence = effective_stage_sequence(
        approval_chain, manager_id=manager_id, department_head_id=department_head_id
    )
    try:
        index = sequence.index(current_stage)
    except ValueError:
        return None
    if index + 1 < len(sequence):
        return sequence[index + 1]
    return None
