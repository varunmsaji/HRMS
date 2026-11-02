"use client";

import { ArrowDown, ArrowUp, Search } from "lucide-react";
import Link from "next/link";
import { useMemo, useState } from "react";

import { AttendanceStatusBadge } from "@/components/attendance/attendance-status-badge";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  PRESENCE_LABELS,
  employeeName,
  formatShortDate,
  initials,
  presenceOf,
  type EmployeeLite,
} from "@/lib/attendance/dashboard";
import { formatClockTime, formatMinutes } from "@/lib/attendance/format";
import type { AttendanceDay } from "@/lib/attendance/types";

export interface WhosInRow {
  id: string;
  employeeId: string;
  /** `null` = in scope but the daily calculation has produced no record yet. */
  day: AttendanceDay | null;
}

type SortKey = "name" | "checkin" | "hours";
const PAGE_SIZE = 25;

interface WhosInPanelProps {
  rows: WhosInRow[];
  employeesById: Map<string, EmployeeLite>;
  shiftNames: Map<string, string>;
  timezone: string;
  /** True when `rows` can span more than one day (a whole-range Needs Attention drill) — shows
   * which date each row belongs to, since the same employee can appear more than once. */
  showDate?: boolean;
  /** Department per employee, when it has loaded — shown under the name. */
  directory?: Map<string, { department: string | null }>;
}

function Avatar({ name }: { name: string }) {
  return (
    <span
      aria-hidden="true"
      className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-primary-subtle text-xs font-semibold text-primary"
    >
      {initials(name)}
    </span>
  );
}

function flagBadges(day: AttendanceDay) {
  return (
    <>
      {day.is_late ? <Badge variant="warning">Late {day.late_minutes > 0 ? `${day.late_minutes}m` : ""}</Badge> : null}
      {day.is_early_out ? (
        <Badge variant="warning">Early out {day.early_departure_minutes > 0 ? `${day.early_departure_minutes}m` : ""}</Badge>
      ) : null}
      {day.missing_punch ? <Badge variant="danger">Missing punch</Badge> : null}
    </>
  );
}

/** The employee list behind every drill-down: search, sort and paging over the rows the page
 * already holds. Desktop shows a table; small screens show the same rows as compact cards. */
export function WhosInPanel({ rows, employeesById, shiftNames, timezone, showDate = false, directory }: WhosInPanelProps) {
  const [query, setQuery] = useState("");
  const [sort, setSort] = useState<{ key: SortKey; dir: 1 | -1 }>({ key: "name", dir: 1 });
  const [page, setPage] = useState(1);
  // A new `rows` array means the drill-down, range or filters changed. Count those changes so the
  // list can fade in fresh instead of snapping (adjusting state during render, not in an effect).
  const [seenRows, setSeenRows] = useState(rows);
  const [generation, setGeneration] = useState(0);
  if (seenRows !== rows) {
    setSeenRows(rows);
    setGeneration((g) => g + 1);
  }

  const view = useMemo(() => {
    const q = query.trim().toLowerCase();
    const decorated = rows.map((row) => {
      const employee = employeesById.get(row.employeeId);
      return { row, employee, name: employeeName(employee, row.employeeId) };
    });
    const filtered = q
      ? decorated.filter(
          (d) => d.name.toLowerCase().includes(q) || (d.employee?.employee_code ?? "").toLowerCase().includes(q),
        )
      : decorated;
    const value = (d: (typeof decorated)[number]): string | number => {
      if (sort.key === "name") return d.name.toLowerCase();
      if (sort.key === "checkin") return d.row.day?.actual_first_in ?? "";
      return d.row.day?.worked_minutes ?? -1;
    };
    return filtered.slice().sort((a, b) => {
      const av = value(a);
      const bv = value(b);
      return (av < bv ? -1 : av > bv ? 1 : 0) * sort.dir;
    });
  }, [rows, employeesById, query, sort]);

  const pageCount = Math.max(1, Math.ceil(view.length / PAGE_SIZE));
  const current = Math.min(page, pageCount);
  const slice = view.slice((current - 1) * PAGE_SIZE, current * PAGE_SIZE);

  function toggleSort(key: SortKey) {
    setSort((prev) => (prev.key === key ? { key, dir: prev.dir === 1 ? -1 : 1 } : { key, dir: 1 }));
  }
  const sortIcon = (key: SortKey) =>
    sort.key === key ? sort.dir === 1 ? <ArrowUp className="h-3 w-3" aria-hidden="true" /> : <ArrowDown className="h-3 w-3" aria-hidden="true" /> : null;
  const ariaSort = (key: SortKey) => (sort.key === key ? (sort.dir === 1 ? "ascending" : "descending") : "none");

  const cells = (d: (typeof slice)[number]) => {
    const day = d.row.day;
    return {
      date: day ? formatShortDate(day.attendance_date) : "—",
      shift: day?.shift_id ? (shiftNames.get(day.shift_id) ?? "—") : "—",
      checkIn: formatClockTime(day?.actual_first_in, timezone),
      checkOut: formatClockTime(day?.actual_last_out, timezone),
      hours: day?.actual_first_in ? formatMinutes(day.worked_minutes) : "—",
      presence: day ? PRESENCE_LABELS[presenceOf(day)] : "No record yet",
    };
  };

  return (
    <div className="space-y-3">
      <div className="relative max-w-xs">
        <Search className="pointer-events-none absolute left-2.5 top-2.5 h-4 w-4 text-foreground-muted" aria-hidden="true" />
        <Input
          type="search"
          aria-label="Search employees"
          placeholder="Search name or ID"
          className="pl-8"
          value={query}
          onChange={(e) => {
            setQuery(e.target.value);
            setPage(1);
          }}
        />
      </div>

      {view.length === 0 ? (
        <p className="rounded-md border border-dashed border-border px-4 py-8 text-center text-sm text-foreground-secondary">
          No attendance days match these filters.
        </p>
      ) : (
        <>
          <div key={`t-${generation}-${current}-${sort.key}-${sort.dir}`} className="hidden animate-in fade-in-0 overflow-x-auto rounded-md border border-border duration-motion-base md:block">
            <table className="w-full text-sm">
              <thead className="bg-surface-secondary text-xs uppercase tracking-wide text-foreground-muted">
                <tr>
                  <th scope="col" aria-sort={ariaSort("name")} className="px-3 py-2 text-left font-medium">
                    <button type="button" className="inline-flex items-center gap-1 uppercase" onClick={() => toggleSort("name")}>
                      Employee {sortIcon("name")}
                    </button>
                  </th>
                  {showDate ? <th scope="col" className="px-3 py-2 text-left font-medium">Date</th> : null}
                  <th scope="col" className="px-3 py-2 text-left font-medium">Shift</th>
                  <th scope="col" aria-sort={ariaSort("checkin")} className="px-3 py-2 text-left font-medium">
                    <button type="button" className="inline-flex items-center gap-1 uppercase" onClick={() => toggleSort("checkin")}>
                      Check-in {sortIcon("checkin")}
                    </button>
                  </th>
                  <th scope="col" className="px-3 py-2 text-left font-medium">Check-out</th>
                  <th scope="col" aria-sort={ariaSort("hours")} className="px-3 py-2 text-left font-medium">
                    <button type="button" className="inline-flex items-center gap-1 uppercase" onClick={() => toggleSort("hours")}>
                      Worked {sortIcon("hours")}
                    </button>
                  </th>
                  <th scope="col" className="px-3 py-2 text-left font-medium">Status</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {slice.map((d) => {
                  const c = cells(d);
                  return (
                    <tr key={d.row.id} className="hover:bg-accent">
                      <td className="px-3 py-2">
                        <div className="flex items-center gap-2.5">
                          <Avatar name={d.name} />
                          <div className="min-w-0">
                            <Link href={`/app/attendance/employee/${d.row.employeeId}`} className="font-medium text-foreground hover:underline">
                              {d.name}
                            </Link>
                            {d.employee?.employee_code || directory?.get(d.row.employeeId)?.department ? (
                              <p className="text-xs text-foreground-muted">
                                {[d.employee?.employee_code, directory?.get(d.row.employeeId)?.department].filter(Boolean).join(" · ")}
                              </p>
                            ) : null}
                          </div>
                        </div>
                      </td>
                      {showDate ? <td className="px-3 py-2 text-foreground-secondary">{c.date}</td> : null}
                      <td className="px-3 py-2 text-foreground-secondary">{c.shift}</td>
                      <td className="px-3 py-2 text-foreground-secondary">{c.checkIn}</td>
                      <td className="px-3 py-2 text-foreground-secondary">{c.checkOut}</td>
                      <td className="px-3 py-2 text-foreground-secondary">{c.hours}</td>
                      <td className="px-3 py-2">
                        {d.row.day ? (
                          <div className="space-y-1">
                            <div className="flex flex-wrap items-center gap-1">
                              <AttendanceStatusBadge status={d.row.day.attendance_status} />
                              {flagBadges(d.row.day)}
                            </div>
                            {c.presence !== "—" ? <p className="text-xs text-foreground-muted">{c.presence}</p> : null}
                          </div>
                        ) : (
                          <Badge variant="outline">No record</Badge>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          <ul key={`l-${generation}-${current}-${sort.key}-${sort.dir}`} className="animate-in fade-in-0 space-y-2 duration-motion-base md:hidden">
            {slice.map((d) => {
              const c = cells(d);
              return (
                <li key={d.row.id} className="rounded-lg border border-border p-3">
                  <div className="flex items-center gap-2.5">
                    <Avatar name={d.name} />
                    <div className="min-w-0 flex-1">
                      <Link href={`/app/attendance/employee/${d.row.employeeId}`} className="block truncate font-medium text-foreground">
                        {d.name}
                      </Link>
                      <p className="text-xs text-foreground-muted">{d.employee?.employee_code ?? "—"}</p>
                    </div>
                    {d.row.day ? <AttendanceStatusBadge status={d.row.day.attendance_status} /> : <Badge variant="outline">No record</Badge>}
                  </div>
                  <dl className="mt-2 grid grid-cols-3 gap-2 text-xs">
                    {showDate ? <div><dt className="text-foreground-muted">Date</dt><dd>{c.date}</dd></div> : null}
                    <div><dt className="text-foreground-muted">In</dt><dd>{c.checkIn}</dd></div>
                    <div><dt className="text-foreground-muted">Out</dt><dd>{c.checkOut}</dd></div>
                    <div><dt className="text-foreground-muted">Worked</dt><dd>{c.hours}</dd></div>
                  </dl>
                  {d.row.day ? <div className="mt-2 flex flex-wrap gap-1">{flagBadges(d.row.day)}</div> : null}
                </li>
              );
            })}
          </ul>

          <div className="flex items-center justify-between text-xs text-foreground-secondary">
            <span>
              {/* A range-scoped drill can list the same employee on more than one day, so this
                  counts rows ("days"), not distinct people — unlike the single-day view, where
                  one row is always one employee. */}
              {showDate
                ? `${view.length} day${view.length === 1 ? "" : "s"}`
                : `${view.length} employee${view.length === 1 ? "" : "s"}`}
            </span>
            {pageCount > 1 ? (
              <div className="flex items-center gap-2">
                <Button type="button" size="sm" variant="outline" disabled={current <= 1} onClick={() => setPage(current - 1)}>
                  Previous
                </Button>
                <span>
                  Page {current} of {pageCount}
                </span>
                <Button type="button" size="sm" variant="outline" disabled={current >= pageCount} onClick={() => setPage(current + 1)}>
                  Next
                </Button>
              </div>
            ) : null}
          </div>
        </>
      )}
    </div>
  );
}
