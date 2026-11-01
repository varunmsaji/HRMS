"""Break rule resolution (break management V1) — pure, no DB.

The effective break configuration of one employee on one date is built in a fixed order:

1. the effective `ShiftVersion` (resolved by date, never mutated here) and its break rules;
2. drop the rules the shift itself disabled (`is_enabled = false`);
3. apply the employee's effective `EmployeeBreakOverride` rows — `DISABLE` removes the named
   break, `REPLACE` swaps the fields it supplies, `ADD` contributes an extra break;
4. order by `(sort_order, name)`.

Every rule that comes out carries `rule_source` (`SHIFT` / `EMPLOYEE_OVERRIDE`) and the id of
the override that produced it, and `ResolvedBreaks.provenance` lists every override that
changed the result (including the ones that only removed a rule), so the calculation snapshot
can show exactly where each break came from. The original `shift_break` rows are never touched.
"""

from dataclasses import dataclass, field, replace
from datetime import date, time
from uuid import UUID

from hrms.modules.attendance.calculation import ShiftBreakData

#: Sorts an ADDed break after the shift's own breaks unless the override says otherwise.
_ADDED_SORT_BASE = 1000


@dataclass(frozen=True, slots=True)
class BreakOverrideData:
    """The fields of `employee_break_override` the resolver reads. `None` on a REPLACE means
    "keep the shift's value"."""

    id: UUID
    action: str  # REPLACE | ADD | DISABLE
    effective_from: date
    effective_to: date | None
    target_break_name: str | None = None
    shift_id: UUID | None = None
    revoked: bool = False
    name: str | None = None
    break_type: str | None = None
    break_kind: str | None = None
    mode: str | None = None
    start_time: time | None = None
    end_time: time | None = None
    window_start: time | None = None
    window_end: time | None = None
    min_minutes: int | None = None
    max_minutes: int | None = None
    scheduled_minutes: int | None = None
    is_paid: bool | None = None
    is_mandatory: bool | None = None
    crosses_midnight: bool | None = None
    excess_outcome: str | None = None
    auto_deduct_full: bool | None = None
    optional_recorded_deducts: bool | None = None
    optional_scheduled_fallback: bool | None = None
    sort_order: int | None = None


@dataclass(frozen=True, slots=True)
class ResolvedBreaks:
    breaks: list[ShiftBreakData]
    provenance: list[dict[str, str | None]] = field(default_factory=list)


def override_applies(
    override: BreakOverrideData, *, target_date: date, shift_id: UUID | None
) -> bool:
    if override.revoked:
        return False
    if target_date < override.effective_from:
        return False
    if override.effective_to is not None and target_date > override.effective_to:
        return False
    return override.shift_id is None or override.shift_id == shift_id


def _key(name: str | None) -> str:
    return (name or "").strip().lower()


def _replaced(base: ShiftBreakData, override: BreakOverrideData) -> ShiftBreakData:
    changes: dict[str, object] = {"rule_source": "EMPLOYEE_OVERRIDE", "override_id": override.id}
    for attr in (
        "name",
        "break_type",
        "break_kind",
        "mode",
        "start_time",
        "end_time",
        "window_start",
        "window_end",
        "min_minutes",
        "max_minutes",
        "scheduled_minutes",
        "is_paid",
        "is_mandatory",
        "crosses_midnight",
        "excess_outcome",
        "auto_deduct_full",
        "optional_recorded_deducts",
        "optional_scheduled_fallback",
        "sort_order",
    ):
        value = getattr(override, attr)
        if value is not None:
            changes[attr] = value
    return replace(base, **changes)  # type: ignore[arg-type]


def _added(override: BreakOverrideData) -> ShiftBreakData:
    kind = override.break_kind or "FIXED_WINDOW"
    return ShiftBreakData(
        id=override.id,
        break_kind=kind,
        start_time=override.start_time,
        end_time=override.end_time,
        window_start=override.window_start,
        window_end=override.window_end,
        min_minutes=override.min_minutes,
        max_minutes=override.max_minutes,
        is_paid=bool(override.is_paid),
        is_mandatory=True if override.is_mandatory is None else override.is_mandatory,
        name=override.name or "Break",
        break_type=override.break_type or "OTHER",
        mode=override.mode,
        scheduled_minutes=override.scheduled_minutes,
        crosses_midnight=bool(override.crosses_midnight),
        excess_outcome=override.excess_outcome,
        auto_deduct_full=bool(override.auto_deduct_full),
        optional_recorded_deducts=(
            True
            if override.optional_recorded_deducts is None
            else override.optional_recorded_deducts
        ),
        optional_scheduled_fallback=bool(override.optional_scheduled_fallback),
        is_enabled=True,
        sort_order=(override.sort_order if override.sort_order is not None else _ADDED_SORT_BASE),
        rule_source="EMPLOYEE_OVERRIDE",
        override_id=override.id,
    )


def resolve_breaks(
    shift_breaks: list[ShiftBreakData],
    overrides: list[BreakOverrideData],
    *,
    target_date: date,
    shift_id: UUID | None,
) -> ResolvedBreaks:
    """Deterministic: the same inputs always give the same list, whatever order the overrides
    were loaded in (they are applied by `(effective_from, id)`)."""
    live = sorted(
        (o for o in overrides if override_applies(o, target_date=target_date, shift_id=shift_id)),
        key=lambda o: (o.effective_from, str(o.id)),
    )
    current = [b for b in shift_breaks if b.is_enabled]
    if not live:
        # No override in force: the shift's own breaks, in their own order, untouched.
        return ResolvedBreaks(breaks=current)

    provenance: list[dict[str, str | None]] = []
    added: list[ShiftBreakData] = []

    def find(name: str | None) -> int | None:
        wanted = _key(name)
        for index, rule in enumerate(current):
            if _key(rule.name) == wanted:
                return index
        return None

    for override in live:
        if override.action == "ADD":
            rule = _added(override)
            if find(rule.name) is not None or any(_key(a.name) == _key(rule.name) for a in added):
                # An ADD never silently shadows an existing break — the service refuses to
                # create it, and a stale one is skipped here rather than guessed at.
                continue
            added.append(rule)
            provenance.append({"action": "ADD", "name": rule.name, "override_id": str(override.id)})
            continue
        index = find(override.target_break_name)
        if index is None:
            continue  # nothing by that name in this shift version: the override is inert
        base = current[index]
        if override.action == "DISABLE":
            del current[index]
            provenance.append(
                {"action": "DISABLE", "name": base.name, "override_id": str(override.id)}
            )
        elif override.action == "REPLACE":
            current[index] = _replaced(base, override)
            provenance.append(
                {"action": "REPLACE", "name": base.name, "override_id": str(override.id)}
            )

    resolved = sorted([*current, *added], key=lambda b: (b.sort_order, _key(b.name)))
    return ResolvedBreaks(breaks=resolved, provenance=provenance)


def _minutes(value: time) -> int:
    return value.hour * 60 + value.minute


def _fixed_span(rule: ShiftBreakData) -> tuple[int, int] | None:
    if rule.break_kind != "FIXED_WINDOW" or rule.start_time is None or rule.end_time is None:
        return None
    start, end = _minutes(rule.start_time), _minutes(rule.end_time)
    return (start, end + 1440 if end <= start else end)


def validate_rule_set(rules: list[ShiftBreakData]) -> str | None:
    """The first problem in a resolved set of breaks, or `None`. Used to refuse an override that
    would leave an employee with an unusable configuration (the shift form applies the same
    rules to a version's own breaks)."""
    seen: set[str] = set()
    spans: list[tuple[str, tuple[int, int]]] = []
    for rule in (r for r in rules if r.is_enabled):
        key = _key(rule.name)
        if not key:
            return "every break needs a name"
        if key in seen:
            return f"duplicate break name '{rule.name}'"
        seen.add(key)
        if rule.mode is None:
            continue
        if rule.break_kind == "FIXED_WINDOW":
            if rule.start_time is None or rule.end_time is None:
                return f"'{rule.name}': start and end times are required"
            if rule.start_time == rule.end_time:
                return f"'{rule.name}': start and end times must differ"
        else:
            if rule.window_start is None or rule.window_end is None:
                return f"'{rule.name}': a window start and end are required"
            if rule.window_end <= rule.window_start:
                return f"'{rule.name}': the window must end after it starts"
            if not rule.scheduled_minutes and rule.mode == "AUTO_DEDUCT":
                return f"'{rule.name}': an automatic break needs scheduled_minutes"
        if rule.max_minutes is not None and rule.max_minutes < 1:
            return f"'{rule.name}': max_minutes must be at least 1"
        if (
            rule.min_minutes is not None
            and rule.max_minutes is not None
            and rule.min_minutes > rule.max_minutes
        ):
            return f"'{rule.name}': min_minutes exceeds max_minutes"
        if (
            rule.scheduled_minutes is not None
            and rule.max_minutes is not None
            and rule.scheduled_minutes > rule.max_minutes
        ):
            return f"'{rule.name}': scheduled_minutes exceeds max_minutes"
        span = _fixed_span(rule)
        if span is not None:
            if rule.scheduled_minutes and rule.scheduled_minutes > span[1] - span[0]:
                return f"'{rule.name}': scheduled_minutes exceeds the break window"
            spans.append((rule.name, span))
    for i, (name_a, a) in enumerate(spans):
        for name_b, b in spans[i + 1 :]:
            for shift in (-1440, 0, 1440):
                if a[0] < b[1] + shift and b[0] + shift < a[1]:
                    return f"'{name_a}' and '{name_b}' overlap"
    return None
