"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

import { BusyRegion } from "@/components/common/busy-region";
import { EmptyState } from "@/components/common/empty-state";
import { ErrorState } from "@/components/common/error-state";
import { FormField } from "@/components/common/form-field";
import { PageHeader } from "@/components/common/page-header";
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
import type { EmployeeOption } from "@/lib/employee/use-employee-directory";
import type { ShiftRoster } from "@/lib/shift-roster/types";

interface ShiftOption {
  id: string;
  name: string;
  code: string | null;
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
  return [e.first_name, e.last_name].filter(Boolean).join(" ");
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
  const today = businessToday(user?.company_timezone ?? "Asia/Kolkata");
  const [start, setStart] = useState(() => mondayOf(today));
  const [days, setDays] = useState<number>(14);
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

  const shiftById = useMemo(() => new Map(shifts.map((s) => [s.id, s])), [shifts]);

  const cells = useMemo(() => {
    const map = new Map<string, ShiftRoster>();
    for (const r of range?.entries ?? []) map.set(`${r.employee_id}|${r.roster_date}`, r);
    return map;
  }, [range]);

  const rosteredIds = useMemo(() => new Set((range?.entries ?? []).map((r) => r.employee_id)), [range]);

  const rows = useMemo(() => {
    const q = search.trim().toLowerCase();
    return (employees ?? []).filter((e) => {
      if (onlyRostered && !rosteredIds.has(e.id)) return false;
      if (!q) return true;
      return `${e.first_name} ${e.last_name ?? ""} ${e.employee_code ?? ""}`.toLowerCase().includes(q);
    });
  }, [employees, rosteredIds, search, onlyRostered]);

  const truncated = range !== null && range.total > range.entries.length;
  const loading = employeesLoading || rosterLoading;
  const error = employeesError ?? rosterError;
  const hasData = employees !== null && range !== null;

  return (
    <div className="space-y-6">
      <div>
        <Link href="/app/rosters" className="text-sm text-foreground-secondary hover:underline">
          ← Shift Rosters
        </Link>
      </div>
      <PageHeader
        title="Team Roster Grid"
        description="Who is on which shift, by date. Employees are listed a page at a time; a blank cell means no roster entry, so their default shift applies."
      />

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-4">
        <FormField id="grid-start" label="Starting">
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
        <div className="flex items-end gap-2">
          <Button type="button" variant="outline" onClick={() => setStart(addDays(start, -days))}>
            ← Prev
          </Button>
          <Button type="button" variant="outline" onClick={() => setStart(addDays(start, days))}>
            Next →
          </Button>
        </div>
      </div>

      <label className="flex items-center gap-2 text-sm text-foreground-secondary">
        <Checkbox checked={onlyRostered} onChange={(e) => setOnlyRostered(e.target.checked)} />
        Only show employees with an entry in this range (on this page)
      </label>

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
            <div className="overflow-x-auto rounded-md border border-border">
              <table className="min-w-full border-collapse text-xs">
                <thead>
                  <tr className="bg-surface-secondary">
                    <th className="sticky left-0 z-10 min-w-44 bg-surface-secondary px-3 py-2 text-left font-medium">
                      Employee
                    </th>
                    {dates.map((d) => {
                      const dt = new Date(`${d}T00:00:00Z`);
                      const weekend = dt.getUTCDay() === 0 || dt.getUTCDay() === 6;
                      return (
                        <th
                          key={d}
                          className={`px-2 py-2 text-center font-medium ${weekend ? "text-foreground-muted" : ""} ${d === today ? "text-primary" : ""}`}
                        >
                          <div>
                            {dt.toLocaleDateString("en-GB", { weekday: "short", timeZone: "UTC" })}
                          </div>
                          <div>
                            {dt.getUTCDate()}/{dt.getUTCMonth() + 1}
                          </div>
                        </th>
                      );
                    })}
                  </tr>
                </thead>
                <tbody>
                  {rows.map((e) => (
                    <tr key={e.id} className="border-t border-border">
                      <td className="sticky left-0 z-10 bg-background px-3 py-2 text-sm">
                        {employeeLabel(e)}
                        {e.employee_code ? (
                          <span className="ml-1 text-foreground-muted">({e.employee_code})</span>
                        ) : null}
                      </td>
                      {dates.map((d) => {
                        const r = cells.get(`${e.id}|${d}`);
                        const off = r?.is_week_off_override;
                        return (
                          <td key={d} className="px-1 py-1 text-center">
                            {r ? (
                              <span
                                title={r.status === "DRAFT" ? "Draft (not live)" : "Published"}
                                className={`inline-block min-w-10 rounded px-1.5 py-1 ${
                                  off
                                    ? "bg-surface-secondary text-foreground-secondary"
                                    : "bg-primary-subtle text-primary"
                                } ${r.status === "DRAFT" ? "border border-dashed border-border" : ""}`}
                              >
                                {cellLabel(r, shiftById)}
                              </span>
                            ) : null}
                          </td>
                        );
                      })}
                    </tr>
                  ))}
                </tbody>
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
      <p className="text-xs text-foreground-muted">
        OFF = week off · * = working holiday · dashed = draft (not live).
      </p>
    </div>
  );
}
