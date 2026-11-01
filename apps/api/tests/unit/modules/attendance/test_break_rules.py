"""Override resolution (`attendance/break_rules.py`) — pure, no DB."""

from datetime import date, time
from uuid import uuid4

from hrms.modules.attendance.break_rules import (
    BreakOverrideData,
    resolve_breaks,
    validate_rule_set,
)
from hrms.modules.attendance.calculation import ShiftBreakData

SHIFT = uuid4()
D = date(2026, 8, 10)


def rule(name: str, start: tuple[int, int], end: tuple[int, int], **kw: object) -> ShiftBreakData:
    base: dict[str, object] = dict(
        id=uuid4(),
        break_kind="FIXED_WINDOW",
        start_time=time(*start),
        end_time=time(*end),
        window_start=None,
        window_end=None,
        min_minutes=None,
        max_minutes=None,
        is_paid=False,
        is_mandatory=True,
        name=name,
        mode="AUTO_DEDUCT",
        scheduled_minutes=(end[0] * 60 + end[1]) - (start[0] * 60 + start[1]),
    )
    base.update(kw)
    return ShiftBreakData(**base)  # type: ignore[arg-type]


def override(action: str, **kw: object) -> BreakOverrideData:
    base: dict[str, object] = dict(
        id=uuid4(), action=action, effective_from=date(2026, 1, 1), effective_to=None
    )
    base.update(kw)
    return BreakOverrideData(**base)  # type: ignore[arg-type]


LUNCH = rule("Lunch", (13, 0), (14, 0))
TEA = rule("Tea", (16, 0), (16, 15), is_paid=True, sort_order=1)


def test_no_override_returns_the_shift_breaks_untouched() -> None:
    result = resolve_breaks([LUNCH, TEA], [], target_date=D, shift_id=SHIFT)
    assert result.breaks == [LUNCH, TEA] and result.provenance == []
    assert all(b.rule_source == "SHIFT" for b in result.breaks)


def test_replace_changes_only_the_supplied_fields_and_labels_the_source() -> None:
    ov = override("REPLACE", target_break_name="lunch", scheduled_minutes=30, end_time=time(13, 30))
    (lunch, tea) = resolve_breaks([LUNCH, TEA], [ov], target_date=D, shift_id=SHIFT).breaks
    assert lunch.scheduled_minutes == 30 and lunch.end_time == time(13, 30)
    assert lunch.start_time == time(13, 0) and lunch.mode == "AUTO_DEDUCT"  # inherited
    assert lunch.rule_source == "EMPLOYEE_OVERRIDE" and lunch.override_id == ov.id
    assert lunch.id == LUNCH.id and tea is TEA
    assert LUNCH.scheduled_minutes == 60  # the shift's own rule is never mutated


def test_disable_removes_the_break_and_records_why() -> None:
    ov = override("DISABLE", target_break_name="Tea")
    result = resolve_breaks([LUNCH, TEA], [ov], target_date=D, shift_id=SHIFT)
    assert result.breaks == [LUNCH]
    assert result.provenance == [{"action": "DISABLE", "name": "Tea", "override_id": str(ov.id)}]


def test_add_contributes_an_extra_break_after_the_shift_breaks() -> None:
    ov = override(
        "ADD",
        name="Rest",
        break_kind="FIXED_WINDOW",
        mode="OPTIONAL_PUNCH",
        start_time=time(10, 0),
        end_time=time(10, 15),
        scheduled_minutes=15,
        is_paid=True,
    )
    result = resolve_breaks([LUNCH, TEA], [ov], target_date=D, shift_id=SHIFT)
    assert [b.name for b in result.breaks] == ["Lunch", "Tea", "Rest"]
    added = result.breaks[-1]
    assert added.rule_source == "EMPLOYEE_OVERRIDE" and added.is_paid and added.id == ov.id


def test_add_never_shadows_an_existing_break() -> None:
    ov = override(
        "ADD",
        name="LUNCH",
        break_kind="FIXED_WINDOW",
        mode="AUTO_DEDUCT",
        start_time=time(12, 0),
        end_time=time(12, 30),
    )
    assert resolve_breaks([LUNCH], [ov], target_date=D, shift_id=SHIFT).breaks == [LUNCH]


def test_overrides_are_effective_dated() -> None:
    ov = override(
        "DISABLE",
        target_break_name="Lunch",
        effective_from=date(2026, 8, 11),
        effective_to=date(2026, 8, 20),
    )
    for day, expected in (
        (date(2026, 8, 10), 1),
        (date(2026, 8, 11), 0),
        (date(2026, 8, 20), 0),
        (date(2026, 8, 21), 1),
    ):
        got = resolve_breaks([LUNCH], [ov], target_date=day, shift_id=SHIFT).breaks
        assert len(got) == expected, day


def test_revoked_and_other_shift_overrides_do_not_apply() -> None:
    revoked = override("DISABLE", target_break_name="Lunch", revoked=True)
    other_shift = override("DISABLE", target_break_name="Lunch", shift_id=uuid4())
    got = resolve_breaks([LUNCH], [revoked, other_shift], target_date=D, shift_id=SHIFT).breaks
    assert got == [LUNCH]
    scoped = override("DISABLE", target_break_name="Lunch", shift_id=SHIFT)
    assert resolve_breaks([LUNCH], [scoped], target_date=D, shift_id=SHIFT).breaks == []


def test_override_naming_a_missing_break_is_inert() -> None:
    ov = override("REPLACE", target_break_name="Nap", scheduled_minutes=5)
    assert resolve_breaks([LUNCH], [ov], target_date=D, shift_id=SHIFT).breaks == [LUNCH]


def test_resolution_is_deterministic_whatever_the_load_order() -> None:
    a = override(
        "REPLACE", target_break_name="Lunch", scheduled_minutes=45, effective_from=date(2026, 1, 1)
    )
    b = override(
        "REPLACE", target_break_name="Lunch", scheduled_minutes=30, effective_from=date(2026, 6, 1)
    )
    one = resolve_breaks([LUNCH], [a, b], target_date=D, shift_id=SHIFT).breaks
    two = resolve_breaks([LUNCH], [b, a], target_date=D, shift_id=SHIFT).breaks
    assert one == two and one[0].scheduled_minutes == 30  # the later-dated override wins


def test_shift_disabled_break_is_dropped_before_overrides() -> None:
    off = rule("Lunch", (13, 0), (14, 0), is_enabled=False)
    ov = override("REPLACE", target_break_name="Lunch", scheduled_minutes=30)
    assert resolve_breaks([off], [ov], target_date=D, shift_id=SHIFT).breaks == []


def test_validate_rule_set() -> None:
    assert validate_rule_set([LUNCH, TEA]) is None
    assert "duplicate" in (validate_rule_set([LUNCH, rule("lunch", (15, 0), (15, 15))]) or "")
    assert "overlap" in (validate_rule_set([LUNCH, rule("Late", (13, 30), (14, 30))]) or "")
    assert "exceeds the break window" in (
        validate_rule_set([rule("Big", (13, 0), (13, 30), scheduled_minutes=45)]) or ""
    )
    assert "max_minutes" in (validate_rule_set([rule("X", (9, 0), (10, 0), max_minutes=0)]) or "")
    assert "must differ" in (validate_rule_set([rule("Z", (9, 0), (9, 0))]) or "")
    # a break across midnight overlaps one early in the morning of the same shift
    night = rule("Meal", (23, 30), (0, 30))
    assert validate_rule_set([night, rule("Early", (0, 0), (1, 0))]) is not None
    assert validate_rule_set([night, rule("Later", (2, 0), (3, 0))]) is None
