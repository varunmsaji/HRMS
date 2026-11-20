"use client";

import { AlertTriangle, ArrowDown, ArrowUp, Search } from "lucide-react";
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

/** One thing HR can do about a mismatched row. A link (`href`) or a button (`onClick`). */
export interface RowFix {
  key: string;
  label: string;
  ariaLabel: string;
  onClick?: () => void;
  href?: string;
  primary?: boolean;
}

/** What is wrong with a row and how to settle it from here. */
export interface RowMismatch {
  reason: string;
  fixes: RowFix[];
}

type SortKey = "attention" | "name" | "checkin" | "hours";
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
  /** When set, rows with no punches (absent, or no record yet) can be ticked and marked present
   * together. The caller gates it on `ATTENDANCE.PUNCH_ON_BEHALF`. Single-day lists only: a range
   * drill can list one person on several days, so it never offers this. */
  onMarkMany?: (target: { employees: { id: string; label: string }[]; date: string }) => void;
  /** The date a row with no attendance record belongs to (the focus date). */
  fallbackDate?: string;
  /** What is wrong with a row and the actions that settle it; `null` for a fine row. When given,
   * mismatched rows say what is wrong and offer the fix in place, and the list can be narrowed to
   * just them. */
  mismatchFor?: (row: WhosInRow) => RowMismatch | null;
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

function flagBadges(day: AttendanceDay, hasMismatch = false) {
  return (
    <>
      {day.is_late ? <Badge variant="warning">Late {day.late_minutes > 0 ? `${day.late_minutes}m` : ""}</Badge> : null}
      {day.is_early_out ? (
        <Badge variant="warning">Early out {day.early_departure_minutes > 0 ? `${day.early_departure_minutes}m` : ""}</Badge>
      ) : null}
      {day.missing_punch && !hasMismatch ? <Badge variant="danger">Missing punch</Badge> : null}
    </>
  );
}

/** The employee list behind every drill-down: search, sort and paging over the rows the page
 * already holds. Desktop shows a table; small screens show the same rows as compact cards. */
/** A row HR can mark present in one step: nothing was punched, and the day is not leave, a
 * holiday or a weekly off (those are not absences to correct). */
function canMarkPresent(day: AttendanceDay | null): boolean {
  if (!day) return true;
  return day.attendance_status === "ABSENT" && !day.actual_first_in && !day.actual_last_out;
}

/** Lower sorts first: rows HR has to fix or chase come before rows that are simply fine. */
function attentionRank(day: AttendanceDay | null): number {
  if (!day) return 1; // no record yet: chase it
  if (day.attendance_status === "CONFIG_ERROR" || day.attendance_status === "INCOMPLETE" || day.missing_punch) return 0;
  if (day.attendance_status === "ABSENT") return 1;
  if (day.is_late || day.is_early_out || day.is_pending_approval) return 2;
  return 3;
}

export function WhosInPanel({
  rows,
  employeesById,
  shiftNames,
  timezone,
  showDate = false,
  directory,
  onMarkMany,
  fallbackDate,
  mismatchFor,
}: WhosInPanelProps) {
  const [query, setQuery] = useState("");
  const [sort, setSort] = useState<{ key: SortKey; dir: 1 | -1 }>({ key: "attention", dir: 1 });
  const [selected, setSelected] = useState<Set<string>>(() => new Set());
  const [onlyMismatches, setOnlyMismatches] = useState(false);
  const [page, setPage] = useState(1);
  // A new `rows` array means the drill-down, range or filters changed. Count those changes so the
  // list can fade in fresh instead of snapping (adjusting state during render, not in an effect).
  const [seenRows, setSeenRows] = useState(rows);
  const [generation, setGeneration] = useState(0);
  if (seenRows !== rows) {
    setSeenRows(rows);
    setGeneration((g) => g + 1);
    setSelected(new Set());
  }

  const mismatchCount = useMemo(() => (mismatchFor ? rows.filter((row) => mismatchFor(row) !== null).length : 0), [rows, mismatchFor]);
  const narrowToMismatches = onlyMismatches && mismatchCount > 0;

  const view = useMemo(() => {
    const q = query.trim().toLowerCase();
    const decorated = rows
      .filter((row) => !narrowToMismatches || (mismatchFor?.(row) ?? null) !== null)
      .map((row) => {
        const employee = employeesById.get(row.employeeId);
        return { row, employee, name: employeeName(employee, row.employeeId) };
      });
    const filtered = q
      ? decorated.filter(
          (d) => d.name.toLowerCase().includes(q) || (d.employee?.employee_code ?? "").toLowerCase().includes(q),
        )
      : decorated;
    const value = (d: (typeof decorated)[number]): string | number => {
      if (sort.key === "attention") return attentionRank(d.row.day);
      if (sort.key === "name") return d.name.toLowerCase();
      if (sort.key === "checkin") return d.row.day?.actual_first_in ?? "";
      return d.row.day?.worked_minutes ?? -1;
    };
    return filtered.slice().sort((a, b) => {
      const av = value(a);
      const bv = value(b);
      const order = (av < bv ? -1 : av > bv ? 1 : 0) * sort.dir;
      // Ties (most of a day's rows share a rank) read alphabetically, whichever way it is sorted.
      return order !== 0 || sort.key === "name" ? order : a.name.toLowerCase().localeCompare(b.name.toLowerCase());
    });
  }, [rows, employeesById, query, sort, narrowToMismatches, mismatchFor]);

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

  // Rows HR can tick: only on a single-day list, and only ones with nothing punched.
  const markable = useMemo(
    () => (onMarkMany && !showDate ? view.filter((d) => canMarkPresent(d.row.day)) : []),
    [onMarkMany, showDate, view],
  );
  const bulkDate = fallbackDate ?? markable.find((d) => d.row.day)?.row.day?.attendance_date;
  const selectable = markable.length > 0 && Boolean(bulkDate);
  const markableIds = new Set(markable.map((d) => d.row.id));
  const pickedCount = markable.filter((d) => selected.has(d.row.id)).length;
  const allPicked = selectable && pickedCount === markable.length;

  function togglePick(id: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (!next.delete(id)) next.add(id);
      return next;
    });
  }
  const selectAll = () => setSelected(new Set(markable.map((d) => d.row.id)));
  const clearPicks = () => setSelected(new Set());
  function markPicked() {
    if (!onMarkMany || !bulkDate) return;
    onMarkMany({
      employees: markable.filter((d) => selected.has(d.row.id)).map((d) => ({ id: d.row.employeeId, label: d.name })),
      date: bulkDate,
    });
  }
  const pickBox = (d: (typeof slice)[number]) =>
    selectable && markableIds.has(d.row.id) ? (
      <input
        type="checkbox"
        className="h-4 w-4 rounded border-border accent-primary"
        aria-label={`Select ${d.name}`}
        checked={selected.has(d.row.id)}
        onChange={() => togglePick(d.row.id)}
      />
    ) : null;

  const fixBlock = (d: (typeof slice)[number]) => {
    const m = mismatchFor?.(d.row);
    if (!m) return null;
    return (
      <div className="mt-1.5 space-y-1.5">
        <p className="flex items-start gap-1 text-xs text-warning">
          <AlertTriangle className="mt-0.5 h-3 w-3 shrink-0" aria-hidden="true" />
          <span>{m.reason}</span>
        </p>
        <div className="flex flex-wrap items-center gap-1.5">
          {m.fixes.map((fix) =>
            fix.href ? (
              <Button key={fix.key} asChild size="xs" variant={fix.primary ? "default" : "outline"}>
                <Link href={fix.href} aria-label={fix.ariaLabel}>
                  {fix.label}
                </Link>
              </Button>
            ) : (
              <Button key={fix.key} type="button" size="xs" variant={fix.primary ? "default" : "outline"} aria-label={fix.ariaLabel} onClick={fix.onClick}>
                {fix.label}
              </Button>
            ),
          )}
        </div>
      </div>
    );
  };

  return (
    <div className="space-y-3">
      {mismatchCount > 0 ? (
        <div className="flex flex-wrap items-center gap-3 rounded-md border border-warning-border bg-warning-subtle px-3 py-2 text-sm">
          <AlertTriangle className="h-4 w-4 shrink-0 text-warning" aria-hidden="true" />
          <span className="text-foreground">
            <span className="font-semibold tabular-nums">{mismatchCount}</span> {mismatchCount === 1 ? "day doesn't" : "days don't"} add up and need fixing.
          </span>
          <Button type="button" size="sm" variant="outline" aria-pressed={narrowToMismatches} onClick={() => setOnlyMismatches((on) => !on)}>
            {narrowToMismatches ? "Show everyone" : "Show only these"}
          </Button>
        </div>
      ) : null}

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

      {selectable ? (
        <div className="flex flex-wrap items-center gap-3 rounded-md bg-surface-secondary px-3 py-2 text-sm">
          {pickedCount > 0 ? (
            <>
              <span className="text-foreground">
                <span className="font-semibold tabular-nums">{pickedCount}</span> selected
              </span>
              <Button type="button" size="sm" onClick={markPicked}>
                Mark {pickedCount} present
              </Button>
              <Button type="button" size="sm" variant="ghost" onClick={clearPicks}>
                Clear
              </Button>
            </>
          ) : (
            <>
              <span className="text-foreground-secondary">
                {markable.length} {markable.length === 1 ? "employee has" : "employees have"} nothing punched.
              </span>
              <Button type="button" size="sm" variant="outline" onClick={selectAll}>
                Select {markable.length === 1 ? "them" : `all ${markable.length}`}
              </Button>
            </>
          )}
        </div>
      ) : null}

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
                  {selectable ? (
                    <th scope="col" className="w-8 px-3 py-2">
                      <input
                        type="checkbox"
                        className="h-4 w-4 rounded border-border accent-primary"
                        aria-label={`Select all ${markable.length} that can be marked present`}
                        checked={allPicked}
                        ref={(el) => {
                          if (el) el.indeterminate = pickedCount > 0 && !allPicked;
                        }}
                        onChange={() => (allPicked ? clearPicks() : selectAll())}
                      />
                    </th>
                  ) : null}
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
                  <th scope="col" aria-sort={ariaSort("attention")} className="px-3 py-2 text-left font-medium">
                    <button type="button" className="inline-flex items-center gap-1 uppercase" onClick={() => toggleSort("attention")}>
                      Status {sortIcon("attention")}
                    </button>
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {slice.map((d) => {
                  const c = cells(d);
                  return (
                    <tr key={d.row.id} className="hover:bg-accent">
                      {selectable ? <td className="w-8 px-3 py-2">{pickBox(d)}</td> : null}
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
                              <AttendanceStatusBadge status={d.row.day.attendance_status} display={d.row.day.display} />
                              {flagBadges(d.row.day, Boolean(mismatchFor?.(d.row)))}
                            </div>
                            {/* "Working" / "Not checked in" would repeat or contradict the reason shown below. */}
                            {c.presence !== "—" && !mismatchFor?.(d.row) ? <p className="text-xs text-foreground-muted">{c.presence}</p> : null}
                          </div>
                        ) : (
                          <Badge variant="outline" className="whitespace-nowrap">No record</Badge>
                        )}
                        {fixBlock(d)}
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
                    {pickBox(d)}
                    <Avatar name={d.name} />
                    <div className="min-w-0 flex-1">
                      <Link href={`/app/attendance/employee/${d.row.employeeId}`} className="block truncate font-medium text-foreground">
                        {d.name}
                      </Link>
                      <p className="text-xs text-foreground-muted">{d.employee?.employee_code ?? "—"}</p>
                    </div>
                    {d.row.day ? <AttendanceStatusBadge status={d.row.day.attendance_status} display={d.row.day.display} /> : <Badge variant="outline" className="whitespace-nowrap">No record</Badge>}
                  </div>
                  <dl className="mt-2 grid grid-cols-3 gap-2 text-xs">
                    {showDate ? <div><dt className="text-foreground-muted">Date</dt><dd>{c.date}</dd></div> : null}
                    <div><dt className="text-foreground-muted">In</dt><dd>{c.checkIn}</dd></div>
                    <div><dt className="text-foreground-muted">Out</dt><dd>{c.checkOut}</dd></div>
                    <div><dt className="text-foreground-muted">Worked</dt><dd>{c.hours}</dd></div>
                  </dl>
                  {d.row.day ? <div className="mt-2 flex flex-wrap gap-1">{flagBadges(d.row.day, Boolean(mismatchFor?.(d.row)))}</div> : null}
                  {fixBlock(d)}
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
