"use client";

import { Plus, SlidersHorizontal } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { RosterEntryDialog } from "@/components/shift-roster/roster-entry-dialog";
import { RangePill } from "@/components/shift-roster/range-pill";
import { RosterHeader } from "@/components/shift-roster/roster-header";
import { useRosterAnchor } from "@/components/shift-roster/roster-context";
import { BusyRegion } from "@/components/common/busy-region";
import { EmptyState } from "@/components/common/empty-state";
import { ErrorState } from "@/components/common/error-state";
import { FormField } from "@/components/common/form-field";
import { PaginationControls } from "@/components/common/pagination-controls";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/native-select";
import { TableSkeleton } from "@/components/ui/skeleton";
import { isAbortError, useLatestRequest } from "@/hooks/use-latest-request";
import { apiClient } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import type { PaginationMeta } from "@/lib/api/types";
import { businessToday } from "@/lib/attendance/format";
import { useAuth } from "@/lib/auth/auth-context";
import { usePermissions } from "@/lib/auth/use-permissions";
import { employeeFullName, employeeNameSearchText } from "@/lib/employee/names";
import type { EmployeeOption } from "@/lib/employee/use-employee-directory";
import { buildCoverage } from "@/lib/shift-roster/coverage";
import type { ShiftRoster } from "@/lib/shift-roster/types";
import { cn } from "@/lib/utils";
import {
  clock12,
  hhmm,
  minutesBetween,
  OFF_TONE,
  PersonAvatar,
  ShiftCard,
  shiftTone,
  useShiftSchedules,
} from "@/components/shift-roster/shift-style";

interface ShiftOption {
  id: string;
  name: string;
  code: string | null;
  start_time?: string;
  end_time?: string;
  is_night_shift?: boolean;
}

function cellTitle(roster: ShiftRoster, shift: ShiftOption | undefined, name: string, date: string): string {
  const what = roster.is_week_off_override
    ? "Week off"
    : shift
      ? `${shift.name}${shift.start_time ? ` ${hhmm(shift.start_time)}–${hhmm(shift.end_time)}` : ""}`
      : "No shift";
  const extras = [
    roster.is_holiday_working_override ? "working holiday" : null,
    roster.status === "DRAFT" ? "draft, not live" : "published",
  ].filter(Boolean);
  return `${name} · ${date} · ${what} (${extras.join(", ")})`;
}

const DAY_OPTIONS = [7, 14, 31] as const;

/** Employee rows per server page. */
const GRID_EMPLOYEES_PER_PAGE = 50;
/** `GET /rosters` returns at most 500 rows per page. */
const ROSTER_ENTRIES_PER_PAGE = 500;
/** Safety bound on how many roster pages one grid view will pull into memory (5,000 entries). If
 * the range holds more, the grid says so instead of pretending the view is complete. */
const MAX_ROSTER_PAGES = 10;

function addDays(iso: string, days: number): string {
  const date = new Date(`${iso}T00:00:00Z`);
  date.setUTCDate(date.getUTCDate() + days);
  return date.toISOString().slice(0, 10);
}

function mondayOf(iso: string): string {
  const dow = (new Date(`${iso}T00:00:00Z`).getUTCDay() + 6) % 7;
  return addDays(iso, -dow);
}

function cellLabel(roster: ShiftRoster, shifts: Map<string, ShiftOption>): string {
  if (roster.is_week_off_override) return "OFF";
  const shift = roster.shift_id ? shifts.get(roster.shift_id) : undefined;
  const name = shift ? (shift.code ?? shift.name) : "—";
  return roster.is_holiday_working_override ? `${name}*` : name;
}

function employeeLabel(e: EmployeeOption): string {
  return employeeFullName(e);
}

interface RosterRange {
  entries: ShiftRoster[];
  total: number;
}

/** Every roster entry in [from, to], across pages of the bounded endpoint, up to
 * {@link MAX_ROSTER_PAGES}. The first page tells us the total; the rest are fetched in parallel. */
async function fetchRosterRange(from: string, to: string, signal: AbortSignal): Promise<RosterRange> {
  const query = { date_from: from, date_to: to, per_page: ROSTER_ENTRIES_PER_PAGE };
  const first = await apiClient.getList<ShiftRoster>("/rosters", { ...query, page: 1 }, { signal });
  const totalPages = Math.min(first.pagination?.total_pages ?? 1, MAX_ROSTER_PAGES);
  const rest = await Promise.all(
    Array.from({ length: Math.max(totalPages - 1, 0) }, (_, i) =>
      apiClient.getList<ShiftRoster>("/rosters", { ...query, page: i + 2 }, { signal }),
    ),
  );
  return {
    entries: [first, ...rest].flatMap((r) => r.data),
    total: first.pagination?.total ?? first.data.length,
  };
}

/** Team roster grid: employees as rows (paged on the server, so everyone is reachable), dates as
 * columns, each cell the rostered shift. A day with no entry falls back to the employee's default
 * shift. Roster entries for the whole date range are loaded across pages; if the range exceeds the
 * safety bound the grid shows a warning rather than a silently partial view. */
export default function RosterGridPage() {
  const { user } = useAuth();
  const { can } = usePermissions();
  const canManage = can("ATTENDANCE.ROSTER_MANAGE");
  const today = businessToday(user?.company_timezone ?? "Asia/Kolkata");
  const [anchor, setStart] = useRosterAnchor(today);
  const start = mondayOf(anchor);
  const [days, setDays] = useState<number>(7);
  const [showFilters, setShowFilters] = useState(false);
  const [search, setSearch] = useState("");
  const [onlyRostered, setOnlyRostered] = useState(false);
  const [employeePage, setEmployeePage] = useState(1);

  const [range, setRange] = useState<RosterRange | null>(null);
  const [rosterLoading, setRosterLoading] = useState(true);
  const [rosterError, setRosterError] = useState<ApiError | null>(null);
  const [employees, setEmployees] = useState<EmployeeOption[] | null>(null);
  const [employeePagination, setEmployeePagination] = useState<PaginationMeta | null>(null);
  const [employeesLoading, setEmployeesLoading] = useState(true);
  const [employeesError, setEmployeesError] = useState<ApiError | null>(null);
  const [shifts, setShifts] = useState<ShiftOption[]>([]);
  const [editTarget, setEditTarget] = useState<{
    roster: ShiftRoster | null;
    employeeId: string;
    employeeName: string;
    date: string;
  } | null>(null);
  const beginRosterRequest = useLatestRequest();
  const beginEmployeeRequest = useLatestRequest();

  useEffect(() => {
    void apiClient
      .get<ShiftOption[]>("/shifts")
      .then(setShifts)
      .catch(() => setShifts([]));
  }, []);

  const dates = useMemo(() => Array.from({ length: days }, (_, i) => addDays(start, i)), [start, days]);
  const end = dates[dates.length - 1];

  useEffect(() => {
    const request = beginEmployeeRequest();
    setEmployeesLoading(true);
    setEmployeesError(null);
    apiClient
      .getList<EmployeeOption>(
        "/employees",
        { page: employeePage, per_page: GRID_EMPLOYEES_PER_PAGE },
        { signal: request.signal },
      )
      .then(({ data, pagination }) => {
        if (!request.isCurrent()) return;
        setEmployees(data);
        setEmployeePagination(pagination);
      })
      .catch((err) => {
        if (isAbortError(err) || !request.isCurrent()) return;
        setEmployees(null);
        setEmployeePagination(null);
        setEmployeesError(
          err instanceof ApiError
            ? err
            : new ApiError({ status: 0, code: "UNKNOWN_ERROR", message: "Something went wrong." }),
        );
      })
      .finally(() => {
        if (request.isCurrent()) setEmployeesLoading(false);
      });
  }, [beginEmployeeRequest, employeePage]);

  useEffect(() => {
    const request = beginRosterRequest();
    setRosterLoading(true);
    setRosterError(null);
    fetchRosterRange(start, end, request.signal)
      .then((result) => {
        if (request.isCurrent()) setRange(result);
      })
      .catch((err) => {
        if (isAbortError(err) || !request.isCurrent()) return;
        setRange(null);
        setRosterError(
          err instanceof ApiError
            ? err
            : new ApiError({ status: 0, code: "UNKNOWN_ERROR", message: "Something went wrong." }),
        );
      })
      .finally(() => {
        if (request.isCurrent()) setRosterLoading(false);
      });
  }, [beginRosterRequest, start, end]);

  const usedShiftIds = useMemo(
    () => (range?.entries ?? []).map((r) => r.shift_id).filter((id): id is string => Boolean(id)),
    [range],
  );
  const schedules = useShiftSchedules(usedShiftIds, start);

  const shiftById = useMemo(() => new Map(shifts.map((s) => [s.id, s])), [shifts]);

  const cells = useMemo(() => {
    const map = new Map<string, ShiftRoster>();
    for (const r of range?.entries ?? []) map.set(`${r.employee_id}|${r.roster_date}`, r);
    return map;
  }, [range]);

  /** Scheduled hours per employee across the visible range: shift length less its breaks. */
  const hoursByEmployee = useMemo(() => {
    const totals = new Map<string, number>();
    for (const r of range?.entries ?? []) {
      if (r.is_week_off_override || !r.shift_id) continue;
      const shift = shiftById.get(r.shift_id);
      const sched = schedules.get(r.shift_id);
      const from = sched?.start ?? shift?.start_time;
      const to = sched?.end ?? shift?.end_time;
      if (!from || !to) continue;
      const mins = Math.max(minutesBetween(from, to) - (sched?.breakMinutes ?? 0), 0);
      totals.set(r.employee_id, (totals.get(r.employee_id) ?? 0) + mins);
    }
    return totals;
  }, [range, shiftById, schedules]);

  const rosteredIds = useMemo(() => new Set((range?.entries ?? []).map((r) => r.employee_id)), [range]);

  const rows = useMemo(() => {
    const q = search.trim().toLowerCase();
    return (employees ?? []).filter((e) => {
      if (onlyRostered && !rosteredIds.has(e.id)) return false;
      if (!q) return true;
      return `${employeeNameSearchText(e)} ${e.employee_code ?? ""}`.toLowerCase().includes(q);
    });
  }, [employees, rosteredIds, search, onlyRostered]);

  function handleSaved(saved: ShiftRoster) {
    setRange((current) => {
      if (!current) return current;
      const exists = current.entries.some((r) => r.id === saved.id);
      return {
        total: exists ? current.total : current.total + 1,
        entries: exists
          ? current.entries.map((r) => (r.id === saved.id ? saved : r))
          : [...current.entries, saved],
      };
    });
  }

  const coverage = useMemo(
    () => buildCoverage(range?.entries ?? [], dates, (id) => shiftById.get(id)?.name),
    [range, dates, shiftById],
  );

  const legend = useMemo(() => {
    const used = new Set((range?.entries ?? []).map((r) => r.shift_id).filter(Boolean) as string[]);
    return shifts.filter((s) => used.has(s.id));
  }, [range, shifts]);

  const rangeLabel = useMemo(() => {
    const fmt = (iso: string) =>
      new Date(`${iso}T00:00:00Z`).toLocaleDateString("en-GB", {
        day: "numeric",
        month: "short",
        year: "numeric",
        timeZone: "UTC",
      });
    return `${fmt(start)} – ${fmt(end)}`;
  }, [start, end]);
  const onThisWeek = start === mondayOf(today);

  const truncated = range !== null && range.total > range.entries.length;
  const loading = employeesLoading || rosterLoading;
  const error = employeesError ?? rosterError;
  const hasData = employees !== null && range !== null;

  return (
    <div className="space-y-6">
      <RosterHeader
        title="Schedule"
        description="Who works which shift each day. A blank cell means no roster entry, so the employee's default shift applies."
      >
        <RangePill
          label={rangeLabel}
          prevLabel="Previous range"
          nextLabel="Next range"
          onPrev={() => setStart(addDays(start, -days))}
          onNext={() => setStart(addDays(start, days))}
        />
        {onThisWeek ? null : (
          <Button type="button" variant="outline" className="rounded-full" onClick={() => setStart(mondayOf(today))}>
            This week
          </Button>
        )}
        <Button
          type="button"
          variant="outline"
          size="icon"
          className={cn("size-11 rounded-full", showFilters && "border-primary text-primary")}
          aria-label="Filters"
          aria-expanded={showFilters}
          onClick={() => setShowFilters((v) => !v)}
        >
          <SlidersHorizontal aria-hidden="true" />
        </Button>
        {canManage ? (
          <Button
            type="button"
            size="icon"
            className="size-11 rounded-full"
            aria-label="Add roster entry"
            onClick={() => setEditTarget({ roster: null, employeeId: "", employeeName: "", date: "" })}
          >
            <Plus className="!size-5" aria-hidden="true" />
          </Button>
        ) : null}
      </RosterHeader>

      {showFilters ? (
      <div className="space-y-3 rounded-2xl border border-border bg-surface p-4 shadow-elevation-1">
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <FormField id="grid-start" label="Go to date">
          <Input
            type="date"
            value={start}
            onChange={(e) => e.target.value && setStart(e.target.value)}
          />
        </FormField>
        <FormField id="grid-days" label="Days">
          <NativeSelect value={days} onChange={(e) => setDays(Number(e.target.value))}>
            {DAY_OPTIONS.map((d) => (
              <option key={d} value={d}>
                {d} days
              </option>
            ))}
          </NativeSelect>
        </FormField>
        <FormField id="grid-search" label="Filter this page" description="Searches the employees shown below.">
          <Input
            placeholder="Search name or code"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </FormField>
      </div>
      <label className="flex items-center gap-2 text-sm text-foreground-secondary">
        <Checkbox checked={onlyRostered} onChange={(e) => setOnlyRostered(e.target.checked)} />
        Only show employees with an entry in this range (on this page)
      </label>
      </div>
      ) : null}

      {truncated ? (
        <div role="alert" className="rounded-md border border-warning-border bg-warning-subtle px-3 py-2 text-sm">
          Showing the first {range?.entries.length.toLocaleString()} of {range?.total.toLocaleString()}{" "}
          roster entries in this range — some cells may be blank even though an entry exists. Choose a
          shorter range to see everything.
        </div>
      ) : null}

      {loading && !hasData ? (
        <div role="status" aria-label="Loading roster">
          <TableSkeleton rows={8} columns={8} />
          <span className="sr-only">Loading roster…</span>
        </div>
      ) : null}
      {error && !loading ? <ErrorState message={error.message} /> : null}

      {hasData && !error ? (
        rows.length === 0 ? (
          <EmptyState
            title="No employees to show."
            description={
              onlyRostered || search
                ? "No one on this page matches. Clear the filter or go to another page."
                : "There are no employees on this page."
            }
          />
        ) : (
          <BusyRegion busy={loading} label="Refreshing roster…">
            <div className="max-h-[75vh] overflow-auto rounded-3xl border border-border-subtle bg-surface shadow-elevation-1">
              <table className="min-w-full border-separate border-spacing-0 text-xs">
                <thead>
                  <tr>
                    <th className="sticky left-0 top-0 z-30 min-w-60 border-b border-border-subtle bg-primary-subtle/40 px-6 py-4 text-left text-sm font-medium text-foreground backdrop-blur">
                      Employee name
                    </th>
                    {dates.map((d) => {
                      const dt = new Date(`${d}T00:00:00Z`);
                      const isToday = d === today;
                      return (
                        <th
                          key={d}
                          className={cn(
                            "sticky top-0 z-20 border-b border-border-subtle bg-primary-subtle/40 px-2 py-3 text-center text-sm font-medium backdrop-blur",
                            isToday ? "text-primary" : "text-foreground",
                          )}
                          aria-current={isToday ? "date" : undefined}
                        >
                          <span className="block">
                            {dt.toLocaleDateString("en-GB", { weekday: "short", timeZone: "UTC" })}
                          </span>
                          <span
                            className={cn(
                              "mt-0.5 inline-block rounded-full px-2 text-[11px] font-normal tabular-nums",
                              isToday ? "bg-primary text-primary-foreground" : "text-foreground-muted",
                            )}
                          >
                            {dt.toLocaleDateString("en-GB", { day: "numeric", month: "short", timeZone: "UTC" })}
                          </span>
                        </th>
                      );
                    })}
                  </tr>
                </thead>
                <tbody>
                  {rows.map((e) => {
                    const mins = hoursByEmployee.get(e.id) ?? 0;
                    const hours = mins === 0 ? "0h" : mins % 60 === 0 ? `${mins / 60}h` : `${Math.floor(mins / 60)}h ${mins % 60}m`;
                    return (
                    <tr key={e.id} className="group">
                      <td className="sticky left-0 z-10 min-w-60 border-b border-border-subtle bg-surface px-6 py-3 text-sm">
                        <div className="flex items-center gap-3.5">
                          <PersonAvatar name={employeeLabel(e)} className="size-12 text-sm" />
                          <span className="min-w-0">
                            <span className="block truncate font-medium text-foreground">{employeeLabel(e)}</span>
                            <span className="mt-0.5 block text-xs text-foreground-muted">
                              <span title="Scheduled hours in this range, breaks excluded">{hours}</span>
                              {e.employee_code ? <span> · {e.employee_code}</span> : null}
                            </span>
                          </span>
                        </div>
                      </td>
                      {dates.map((d) => {
                        const r = cells.get(`${e.id}|${d}`);
                        const off = r?.is_week_off_override;
                        const shift = r?.shift_id ? shiftById.get(r.shift_id) : undefined;
                        const sched = r?.shift_id ? schedules.get(r.shift_id) : undefined;
                        const breakMins = sched?.breakMinutes ?? 0;
                        const from = sched?.start ?? shift?.start_time;
                        const to = sched?.end ?? shift?.end_time;
                        return (
                          <td
                            key={d}
                            className={cn(
                              "h-[104px] min-w-36 border-b border-l border-border-subtle p-1.5 align-top",
                              d === today && "bg-primary-subtle/20",
                            )}
                          >
                            {r ? (
                              <button
                                type="button"
                                disabled={!canManage}
                                onClick={() =>
                                  setEditTarget({ roster: r, employeeId: e.id, employeeName: employeeLabel(e), date: d })
                                }
                                title={cellTitle(r, shift, employeeLabel(e), d)}
                                aria-label={cellTitle(r, shift, employeeLabel(e), d)}
                                className={cn(
                                  "block h-full w-full rounded-lg transition-shadow",
                                  canManage ? "cursor-pointer hover:shadow-elevation-2 focus-visible:ring-2 focus-visible:ring-ring" : "cursor-default",
                                )}
                              >
                                <ShiftCard
                                  className="h-full"
                                  tone={off ? OFF_TONE : shiftTone(shift)}
                                  draft={r.status === "DRAFT"}
                                  time={!off && from ? `${clock12(from)} – ${clock12(to)}` : undefined}
                                  label={
                                    off
                                      ? "Week off"
                                      : `${shift?.name ?? cellLabel(r, shiftById)}${r.is_holiday_working_override ? " · holiday" : ""}`
                                  }
                                  breakMins={off ? 0 : breakMins}
                                />
                              </button>
                            ) : canManage ? (
                              <button
                                type="button"
                                onClick={() =>
                                  setEditTarget({ roster: null, employeeId: e.id, employeeName: employeeLabel(e), date: d })
                                }
                                aria-label={`Add roster entry for ${employeeLabel(e)} on ${d}`}
                                className="flex h-full w-full items-center justify-center rounded-lg border border-dashed border-transparent text-foreground-muted opacity-0 transition hover:border-border-strong hover:opacity-100 focus-visible:opacity-100"
                              >
                                <Plus className="size-4" aria-hidden="true" />
                              </button>
                            ) : null}
                          </td>
                        );
                      })}
                    </tr>
                    );
                  })}
                </tbody>
                {coverage.rows.length > 0 ? (
                  <tfoot>
                    <tr className="border-t-2 border-border bg-surface-secondary">
                      <th
                        scope="rowgroup"
                        colSpan={dates.length + 1}
                        className="sticky left-0 px-3 py-1.5 text-left text-2xs font-semibold uppercase tracking-wider text-foreground-muted"
                      >
                        Rostered per day — all employees, not just this page
                      </th>
                    </tr>
                    {coverage.rows.map((row) => (
                      <tr key={row.key} className="border-t border-border">
                        <th
                          scope="row"
                          className="sticky left-0 z-10 bg-background px-3 py-1.5 text-left text-xs font-medium"
                        >
                          {row.label}
                          <span className="ml-1 font-normal text-foreground-muted">({row.people})</span>
                        </th>
                        {dates.map((d) => {
                          const n = row.byDate.get(d) ?? 0;
                          return (
                            <td
                              key={d}
                              className={`px-1 py-1.5 text-center tabular-nums ${
                                d === today ? "border-x-2 border-primary bg-primary-subtle/30" : ""
                              } ${n === 0 ? "text-foreground-muted" : "font-semibold"}`}
                              aria-label={`${row.label} on ${d}: ${n}`}
                            >
                              {n === 0 ? "–" : n}
                            </td>
                          );
                        })}
                      </tr>
                    ))}
                  </tfoot>
                ) : null}
              </table>
            </div>
          </BusyRegion>
        )
      ) : null}

      {employeePagination && !error ? (
        <PaginationControls
          pagination={employeePagination}
          onPageChange={setEmployeePage}
          disabled={employeesLoading}
          className="rounded-md border"
        />
      ) : null}
      {legend.length > 0 ? (
        <ul className="flex flex-wrap items-center gap-2 text-xs" aria-label="Shift colour legend">
          {legend.map((s) => (
            <li key={s.id} className={`rounded-md border-l-4 px-2 py-1 font-medium ${shiftTone(s)}`}>
              {s.code ?? s.name}
              {s.code ? <span className="ml-1 font-normal opacity-80">{s.name}</span> : null}
            </li>
          ))}
          <li className={`rounded-md border-l-4 px-2 py-1 font-medium ${OFF_TONE}`}>OFF</li>
        </ul>
      ) : null}
      <RosterEntryDialog
        open={editTarget !== null}
        onOpenChange={(open) => {
          if (!open) setEditTarget(null);
        }}
        roster={editTarget?.roster ?? null}
        employeeId={editTarget?.employeeId}
        employeeLabel={editTarget?.employeeName}
        rosterDate={editTarget?.date}
        onSaved={handleSaved}
      />
      <p className="text-xs text-foreground-muted">
        {canManage ? "Click a cell to edit it, or the + on a blank cell to add an entry. " : ""}OFF = week off · * = working holiday · dashed = draft (not live).
      </p>
    </div>
  );
}
