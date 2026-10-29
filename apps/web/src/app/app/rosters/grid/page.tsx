"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

import { EmptyState } from "@/components/common/empty-state";
import { ErrorState } from "@/components/common/error-state";
import { FormField } from "@/components/common/form-field";
import { LoadingState } from "@/components/common/loading-state";
import { PageHeader } from "@/components/common/page-header";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/native-select";
import { apiClient } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import { businessToday } from "@/lib/attendance/format";
import { useAuth } from "@/lib/auth/auth-context";
import type { ShiftRoster } from "@/lib/shift-roster/types";

interface EmployeeOption {
  id: string;
  first_name: string;
  last_name: string | null;
  employee_code: string | null;
}

interface ShiftOption {
  id: string;
  name: string;
  code: string | null;
}

const DAY_OPTIONS = [7, 14, 31] as const;

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

/** Team roster grid: employees as rows, dates as columns, each cell the rostered shift. Shows
 * roster entries only; days with no entry fall back to the employee's default shift. */
export default function RosterGridPage() {
  const { user } = useAuth();
  const today = businessToday(user?.company_timezone ?? "Asia/Kolkata");
  const [start, setStart] = useState(() => mondayOf(today));
  const [days, setDays] = useState<number>(14);
  const [search, setSearch] = useState("");

  const [rosters, setRosters] = useState<ShiftRoster[] | null>(null);
  const [employees, setEmployees] = useState<EmployeeOption[]>([]);
  const [shifts, setShifts] = useState<ShiftOption[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<ApiError | null>(null);

  useEffect(() => {
    void apiClient
      .getList<EmployeeOption>("/employees", { per_page: 100 })
      .then(({ data }) => setEmployees(data))
      .catch(() => setEmployees([]));
    void apiClient
      .get<ShiftOption[]>("/shifts")
      .then(setShifts)
      .catch(() => setShifts([]));
  }, []);

  const dates = useMemo(() => Array.from({ length: days }, (_, i) => addDays(start, i)), [start, days]);
  const end = dates[dates.length - 1];

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    const params = new URLSearchParams({ date_from: start, date_to: end });
    apiClient
      .get<ShiftRoster[]>(`/rosters?${params.toString()}`)
      .then((data) => {
        if (!cancelled) setRosters(data);
      })
      .catch((err) => {
        if (cancelled) return;
        setRosters(null);
        setError(
          err instanceof ApiError
            ? err
            : new ApiError({ status: 0, code: "UNKNOWN_ERROR", message: "Something went wrong." }),
        );
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [start, end]);

  const shiftById = useMemo(() => new Map(shifts.map((s) => [s.id, s])), [shifts]);

  const cells = useMemo(() => {
    const map = new Map<string, ShiftRoster>();
    for (const r of rosters ?? []) map.set(`${r.employee_id}|${r.roster_date}`, r);
    return map;
  }, [rosters]);

  const rows = useMemo(() => {
    const q = search.trim().toLowerCase();
    const rostered = new Set((rosters ?? []).map((r) => r.employee_id));
    return employees.filter((e) => {
      if (!rostered.has(e.id)) return false;
      if (!q) return true;
      const name = `${e.first_name} ${e.last_name ?? ""} ${e.employee_code ?? ""}`.toLowerCase();
      return name.includes(q);
    });
  }, [employees, rosters, search]);

  return (
    <div className="space-y-6">
      <div>
        <Link href="/app/rosters" className="text-sm text-foreground-secondary hover:underline">
          ← Shift Rosters
        </Link>
      </div>
      <PageHeader
        title="Team Roster Grid"
        description="Who is on which shift, by date. Employees with no roster entry in the range are not shown."
      />

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-4">
        <FormField id="grid-start" label="Starting">
          <Input type="date" value={start} onChange={(e) => e.target.value && setStart(e.target.value)} />
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
        <FormField id="grid-search" label="Employee">
          <Input placeholder="Search name or code" value={search} onChange={(e) => setSearch(e.target.value)} />
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

      {loading ? <LoadingState label="Loading roster…" /> : null}
      {error && !loading ? <ErrorState message={error.message} /> : null}

      {!loading && !error ? (
        rows.length === 0 ? (
          <EmptyState title="No shifts rostered in this range." description="Only employees with a roster entry are shown. Try another date range." />
        ) : (
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
                        <div>{dt.toLocaleDateString("en-GB", { weekday: "short", timeZone: "UTC" })}</div>
                        <div>{dt.getUTCDate()}/{dt.getUTCMonth() + 1}</div>
                      </th>
                    );
                  })}
                </tr>
              </thead>
              <tbody>
                {rows.map((e) => (
                  <tr key={e.id} className="border-t border-border">
                    <td className="sticky left-0 z-10 bg-background px-3 py-2 text-sm">
                      {[e.first_name, e.last_name].filter(Boolean).join(" ")}
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
        )
      ) : null}
      <p className="text-xs text-foreground-muted">
        OFF = week off · * = working holiday · dashed = draft (not live).
      </p>
    </div>
  );
}
