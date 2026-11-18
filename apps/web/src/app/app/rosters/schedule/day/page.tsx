"use client";

import { useEffect, useMemo, useState } from "react";

import { BusyRegion } from "@/components/common/busy-region";
import { ErrorState } from "@/components/common/error-state";
import { FormField } from "@/components/common/form-field";
import { useToast } from "@/components/common/toast";
import { RangePill } from "@/components/shift-roster/range-pill";
import { useRosterAnchor } from "@/components/shift-roster/roster-context";
import { RosterHeader } from "@/components/shift-roster/roster-header";
import { hhmm, OFF_TONE, PersonAvatar, shiftTone, useShiftSchedules } from "@/components/shift-roster/shift-style";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { apiClient } from "@/lib/api/client";
import { ApiError, describeApiError } from "@/lib/api/errors";
import { businessToday } from "@/lib/attendance/format";
import { useAuth } from "@/lib/auth/auth-context";
import { usePermissions } from "@/lib/auth/use-permissions";
import { employeeFullName, employeeNameSearchText } from "@/lib/employee/names";
import type { EmployeeOption } from "@/lib/employee/use-employee-directory";
import type { ShiftRoster } from "@/lib/shift-roster/types";
import { cn } from "@/lib/utils";

interface ShiftOption {
  id: string;
  name: string;
  code: string | null;
  start_time?: string;
  end_time?: string;
  is_night_shift?: boolean;
}

/** Column key for employees with no roster entry on the chosen date (their default shift applies). */
const UNASSIGNED = "__unassigned__";
const WEEK_OFF = "__week_off__";
const NEUTRAL_TONE = "border-border-strong bg-surface-secondary text-foreground";
/** `GET /employees` is capped at 100 rows per page; the board pulls up to this many pages. */
const EMPLOYEES_PER_PAGE = 100;
const MAX_EMPLOYEE_PAGES = 10;

async function fetchAllEmployees(): Promise<{ data: EmployeeOption[]; more: boolean }> {
  const first = await apiClient.getList<EmployeeOption>("/employees", { page: 1, per_page: EMPLOYEES_PER_PAGE });
  const totalPages = first.pagination?.total_pages ?? 1;
  const rest = await Promise.all(
    Array.from({ length: Math.max(Math.min(totalPages, MAX_EMPLOYEE_PAGES) - 1, 0) }, (_, i) =>
      apiClient.getList<EmployeeOption>("/employees", { page: i + 2, per_page: EMPLOYEES_PER_PAGE }),
    ),
  );
  return { data: [first, ...rest].flatMap((r) => r.data), more: totalPages > MAX_EMPLOYEE_PAGES };
}

function addDays(iso: string, days: number): string {
  const d = new Date(`${iso}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + days);
  return d.toISOString().slice(0, 10);
}

function columnOf(r: ShiftRoster | undefined): string {
  if (!r) return UNASSIGNED;
  if (r.is_week_off_override) return WEEK_OFF;
  return r.shift_id ?? UNASSIGNED;
}

function fullName(e: EmployeeOption): string {
  return employeeFullName(e);
}

/** Shift board: one column per shift for a single date. Drag an employee card between columns to
 * assign or change their shift for that day. A drop writes the roster entry and publishes it, so it
 * takes effect immediately. */
export default function RosterBoardPage() {
  const { user } = useAuth();
  const { can } = usePermissions();
  const { toast } = useToast();
  const canManage = can("ATTENDANCE.ROSTER_MANAGE");
  const [date, setDate] = useRosterAnchor(businessToday(user?.company_timezone ?? "Asia/Kolkata"));
  const dayLabel = useMemo(
    () =>
      new Date(`${date}T00:00:00Z`).toLocaleDateString("en-GB", {
        weekday: "short",
        day: "numeric",
        month: "short",
        year: "numeric",
        timeZone: "UTC",
      }),
    [date],
  );
  const [shifts, setShifts] = useState<ShiftOption[]>([]);
  const [employees, setEmployees] = useState<EmployeeOption[] | null>(null);
  const [entries, setEntries] = useState<ShiftRoster[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<ApiError | null>(null);
  const [dragId, setDragId] = useState<string | null>(null);
  const [overCol, setOverCol] = useState<string | null>(null);
  const [savingId, setSavingId] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [picked, setPicked] = useState<string | null>(null);
  const [lastMove, setLastMove] = useState<{ employeeId: string; name: string; from: string } | null>(null);
  const [copying, setCopying] = useState(false);
  const [moreEmployees, setMoreEmployees] = useState(false);

  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    let live = true;
    Promise.all([
      apiClient.get<ShiftOption[]>("/shifts"),
      fetchAllEmployees(),
      apiClient.getList<ShiftRoster>("/rosters", { date_from: date, date_to: date, per_page: 500 }),
    ])
      .then(([shiftList, emps, rosters]) => {
        if (!live) return;
        setShifts(shiftList);
        setEmployees(emps.data);
        setMoreEmployees(emps.more);
        setEntries(rosters.data);
      })
      .catch((err) => {
        if (!live) return;
        setError(
          err instanceof ApiError
            ? err
            : new ApiError({ status: 0, code: "UNKNOWN_ERROR", message: "Something went wrong." }),
        );
      })
      .finally(() => {
        if (live) setLoading(false);
      });
    return () => {
      live = false;
    };
  }, [date, reloadKey]);

  function changeDate(next: string) {
    setLoading(true);
    setError(null);
    setLastMove(null);
    setPicked(null);
    setDate(next);
  }

  const entryByEmployee = useMemo(() => new Map(entries.map((r) => [r.employee_id, r])), [entries]);

  const shiftIds = useMemo(() => shifts.map((s) => s.id), [shifts]);
  const schedules = useShiftSchedules(shiftIds, date);

  const columns = useMemo(
    () => [
      { key: UNASSIGNED, title: "Unassigned", sub: "Default shift applies", tone: NEUTRAL_TONE },
      ...shifts.map((s) => {
        const sched = schedules.get(s.id);
        const start = sched?.start ?? s.start_time;
        const end = sched?.end ?? s.end_time;
        const brk = sched?.breakMinutes ?? 0;
        const parts = [s.name];
        if (start) parts.push(`${hhmm(start)}–${hhmm(end)}`);
        if (brk > 0) parts.push(`${brk} m break`);
        return { key: s.id, title: s.code ?? s.name, sub: parts.join(" · "), tone: shiftTone(s) };
      }),
      { key: WEEK_OFF, title: "Week off", sub: "Not working", tone: OFF_TONE },
    ],
    [shifts, schedules],
  );

  const byColumn = useMemo(() => {
    const map = new Map<string, EmployeeOption[]>();
    for (const c of columns) map.set(c.key, []);
    const q = search.trim().toLowerCase();
    for (const e of employees ?? []) {
      if (q && !`${employeeNameSearchText(e)} ${e.employee_code ?? ""}`.toLowerCase().includes(q)) continue;
      const key = columnOf(entryByEmployee.get(e.id));
      (map.get(key) ?? map.get(UNASSIGNED))!.push(e);
    }
    return map;
  }, [columns, employees, entryByEmployee, search]);

  async function moveTo(employeeId: string, target: string, recordUndo = true) {
    const existing = entryByEmployee.get(employeeId);
    const from = columnOf(existing);
    if (from === target) return;
    const emp = (employees ?? []).find((e) => e.id === employeeId);
    setSavingId(employeeId);
    try {
      if (target === UNASSIGNED) {
        if (existing) {
          await apiClient.delete<ShiftRoster>(`/rosters/${existing.id}`, {
            ifMatch: String(existing.version),
          });
          setEntries((cur) => cur.filter((r) => r.id !== existing.id));
        }
      } else {
        const weekOff = target === WEEK_OFF;
        const fields = { shift_id: weekOff ? null : target, is_week_off_override: weekOff };
        let saved = existing
          ? await apiClient.patch<ShiftRoster>(`/rosters/${existing.id}`, fields, {
              ifMatch: String(existing.version),
            })
          : await apiClient.post<ShiftRoster>("/rosters", {
              employee_id: employeeId,
              roster_date: date,
              ...fields,
            });
        if (saved.status === "DRAFT") {
          saved = await apiClient.post<ShiftRoster>(
            `/rosters/${saved.id}/publish`,
            {},
            { ifMatch: String(saved.version) },
          );
        }
        const result = saved;
        setEntries((cur) => [...cur.filter((r) => r.id !== result.id), result]);
      }
      setLastMove(recordUndo && emp ? { employeeId, name: fullName(emp), from } : null);
    } catch (err) {
      toast({ title: "Could not change shift", description: describeApiError(err), variant: "danger" });
      setLoading(true);
      setReloadKey((k) => k + 1);
    } finally {
      setSavingId(null);
    }
  }

  async function copyToNextDay() {
    const next = addDays(date, 1);
    if (!window.confirm(`Copy ${entries.length} roster entries from ${date} to ${next}? Employees who already have an entry on ${next} are skipped.`)) return;
    setCopying(true);
    try {
      const existing = await apiClient.getList<ShiftRoster>("/rosters", {
        date_from: next,
        date_to: next,
        per_page: 500,
      });
      const taken = new Set(existing.data.map((r) => r.employee_id));
      let copied = 0;
      for (const r of entries) {
        if (taken.has(r.employee_id)) continue;
        const created = await apiClient.post<ShiftRoster>("/rosters", {
          employee_id: r.employee_id,
          roster_date: next,
          shift_id: r.shift_id,
          is_week_off_override: r.is_week_off_override,
          is_holiday_working_override: r.is_holiday_working_override,
        });
        await apiClient.post<ShiftRoster>(`/rosters/${created.id}/publish`, {}, { ifMatch: String(created.version) });
        copied += 1;
      }
      toast({
        title: `Copied ${copied} entries to ${next}`,
        description: copied < entries.length ? `${entries.length - copied} skipped (already rostered).` : undefined,
        variant: "success",
      });
    } catch (err) {
      toast({ title: "Copy stopped part-way", description: describeApiError(err), variant: "danger" });
    } finally {
      setCopying(false);
    }
  }

  function onDrop(target: string) {
    const id = dragId;
    setDragId(null);
    setOverCol(null);
    if (id) void moveTo(id, target);
  }

  return (
    <div className="space-y-6">
      <RosterHeader
        title="Schedule"
        description={
          canManage
            ? "Drag an employee into a shift column to assign or change their shift for the day. Or tap a card, then tap a column (works on touch). Dropping on Unassigned removes the day's entry. Changes go live immediately."
            : "Who is on which shift for the chosen day."
        }
      >
        <RangePill
          label={dayLabel}
          prevLabel="Previous day"
          nextLabel="Next day"
          onPrev={() => changeDate(addDays(date, -1))}
          onNext={() => changeDate(addDays(date, 1))}
        />
      </RosterHeader>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <FormField id="board-date" label="Date">
          <Input type="date" value={date} onChange={(e) => e.target.value && changeDate(e.target.value)} />
        </FormField>
        <FormField id="board-search" label="Find employee">
          <Input placeholder="Search name or code" value={search} onChange={(e) => setSearch(e.target.value)} />
        </FormField>
        {canManage ? (
          <div className="flex items-end gap-2">
            <Button
              type="button"
              variant="outline"
              disabled={!lastMove || savingId !== null}
              onClick={() => lastMove && void moveTo(lastMove.employeeId, lastMove.from, false).then(() => setLastMove(null))}
            >
              {lastMove ? `Undo: ${lastMove.name}` : "Undo"}
            </Button>
            <Button type="button" variant="outline" disabled={copying || entries.length === 0} onClick={() => void copyToNextDay()}>
              {copying ? "Copying…" : "Copy to next day"}
            </Button>
          </div>
        ) : null}
      </div>
      {canManage && picked ? (
        <p className="rounded-md border border-primary bg-primary-subtle px-3 py-2 text-sm" role="status">
          Selected {fullName((employees ?? []).find((e) => e.id === picked) ?? ({ first_name: "employee", last_name: null } as EmployeeOption))}
          . Tap a column to move them there, or tap the card again to cancel.
        </p>
      ) : null}
      {error ? <ErrorState message={error.message} /> : null}
      {employees ? (
        <BusyRegion busy={loading} label="Refreshing board…">
          <div className="flex gap-3 overflow-x-auto pb-2">
            {columns.map((col) => {
              const people = byColumn.get(col.key) ?? [];
              return (
                <section
                  key={col.key}
                  aria-label={`${col.title}, ${people.length} employees`}
                  onDragOver={(e) => {
                    if (!canManage || !dragId) return;
                    e.preventDefault();
                    setOverCol(col.key);
                  }}
                  onDragLeave={() => setOverCol((c) => (c === col.key ? null : c))}
                  onDrop={(e) => {
                    e.preventDefault();
                    onDrop(col.key);
                  }}
                  onClick={() => {
                    if (!canManage || !picked) return;
                    const id = picked;
                    setPicked(null);
                    void moveTo(id, col.key);
                  }}
                  className={`flex max-h-[70vh] w-64 shrink-0 flex-col overflow-hidden rounded-2xl border bg-surface shadow-elevation-1 ${
                    overCol === col.key ? "border-primary ring-2 ring-primary" : "border-border"
                  }`}
                >
                  <header className={cn("border-b border-l-4 border-b-border px-3 py-2.5", col.tone)}>
                    <div className="flex items-center justify-between text-sm font-semibold">
                      {col.title}
                      <span className="rounded-full bg-surface px-2 py-0.5 text-xs font-medium text-foreground-secondary">
                        {people.length}
                      </span>
                    </div>
                    <div className="truncate text-2xs opacity-80">{col.sub}</div>
                  </header>
                  <ul className="flex-1 space-y-2 overflow-y-auto p-2">
                    {people.map((e) => {
                      const draft = entryByEmployee.get(e.id)?.status === "DRAFT";
                      return (
                        <li
                          key={e.id}
                          draggable={canManage && savingId !== e.id}
                          onDragStart={(ev) => {
                            ev.dataTransfer.effectAllowed = "move";
                            ev.dataTransfer.setData("text/plain", e.id);
                            setDragId(e.id);
                          }}
                          onDragEnd={() => {
                            setDragId(null);
                            setOverCol(null);
                          }}
                          onClick={(ev) => {
                            if (!canManage) return;
                            ev.stopPropagation();
                            setPicked((cur) => (cur === e.id ? null : e.id));
                          }}
                          className={cn(
                            "flex items-center gap-2.5 rounded-md border-l-4 px-2.5 py-2 text-sm",
                            col.tone,
                            canManage && "cursor-grab active:cursor-grabbing",
                            picked === e.id && "ring-2 ring-primary",
                            draft && "border-y border-r border-dashed border-y-foreground-muted border-r-foreground-muted",
                            (savingId === e.id || dragId === e.id) && "opacity-50",
                          )}
                        >
                          <PersonAvatar name={fullName(e)} className="size-8 bg-surface" />
                          <span className="min-w-0">
                            <span className="block truncate font-medium text-foreground">{fullName(e)}</span>
                            {e.employee_code ? (
                              <span className="block text-xs text-foreground-muted">{e.employee_code}</span>
                            ) : null}
                          </span>
                        </li>
                      );
                    })}
                    {people.length === 0 ? (
                      <li className="px-1 py-4 text-center text-xs text-foreground-muted">
                        {canManage ? "Drop or tap here" : "No one"}
                      </li>
                    ) : null}
                  </ul>
                </section>
              );
            })}
          </div>
        </BusyRegion>
      ) : null}
      {moreEmployees ? (
        <p className="text-xs text-foreground-muted">
          Showing the first {(MAX_EMPLOYEE_PAGES * EMPLOYEES_PER_PAGE).toLocaleString()} employees. Use search on the Week view for the rest.
        </p>
      ) : null}
    </div>
  );
}
