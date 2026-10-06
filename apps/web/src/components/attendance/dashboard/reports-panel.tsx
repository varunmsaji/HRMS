"use client";

import { ArrowDown, ArrowUp, Search } from "lucide-react";
import Link from "next/link";
import { useMemo, useState, type ReactNode } from "react";

import { SectionCard } from "@/components/attendance/dashboard/section-card";
import { usePeriodSummary, type Section } from "@/components/attendance/dashboard/use-dashboard-data";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import type { AttendancePeriod } from "@/lib/attendance-period/types";
import {
  BUCKET_LABELS,
  bucketOf,
  employeeName,
  formatShortDate,
  pickDefaultPeriod,
  type EmployeeLite,
} from "@/lib/attendance/dashboard";
import { formatClockTime, formatMinutes } from "@/lib/attendance/format";
import type { AttendanceDay } from "@/lib/attendance/types";
import { OVERTIME_DAY_CLASS_LABELS, OVERTIME_STATUS_LABELS, type OvertimeDayClass, type OvertimeRecord } from "@/lib/overtime/types";
import { cn } from "@/lib/utils";

const PAGE_SIZE = 15;

interface Column<T> {
  key: string;
  label: string;
  render: (row: T) => ReactNode;
  sort: (row: T) => string | number;
  align?: "right";
}

interface ReportTableProps<T> {
  rows: T[];
  columns: Column<T>[];
  rowKey: (row: T) => string;
  searchText: (row: T) => string;
  empty: string;
}

function ReportTable<T>({ rows, columns, rowKey, searchText, empty }: ReportTableProps<T>) {
  const [query, setQuery] = useState("");
  const [sort, setSort] = useState<{ key: string; dir: 1 | -1 }>({ key: columns[0].key, dir: 1 });
  const [page, setPage] = useState(1);

  const view = useMemo(() => {
    const q = query.trim().toLowerCase();
    const filtered = q ? rows.filter((row) => searchText(row).toLowerCase().includes(q)) : rows;
    const col = columns.find((c) => c.key === sort.key) ?? columns[0];
    return filtered.slice().sort((a, b) => {
      const av = col.sort(a);
      const bv = col.sort(b);
      return (av < bv ? -1 : av > bv ? 1 : 0) * sort.dir;
    });
  }, [rows, columns, query, sort, searchText]);

  const pages = Math.max(1, Math.ceil(view.length / PAGE_SIZE));
  const current = Math.min(page, pages);
  const slice = view.slice((current - 1) * PAGE_SIZE, current * PAGE_SIZE);

  return (
    <div className="space-y-3">
      <div className="relative max-w-xs">
        <Search className="pointer-events-none absolute left-2.5 top-2.5 h-4 w-4 text-foreground-muted" aria-hidden="true" />
        <Input
          type="search"
          aria-label="Search report"
          placeholder="Search"
          className="pl-8"
          value={query}
          onChange={(e) => {
            setQuery(e.target.value);
            setPage(1);
          }}
        />
      </div>
      {view.length === 0 ? (
        <p className="rounded-md border border-dashed border-border px-4 py-8 text-center text-sm text-foreground-secondary">{empty}</p>
      ) : (
        <>
          <div className="overflow-x-auto rounded-md border border-border">
            <table className="w-full text-sm">
              <thead className="bg-surface-secondary text-xs uppercase tracking-wide text-foreground-muted">
                <tr>
                  {columns.map((c) => (
                    <th
                      key={c.key}
                      scope="col"
                      aria-sort={sort.key === c.key ? (sort.dir === 1 ? "ascending" : "descending") : "none"}
                      className={cn("px-3 py-2 font-medium", c.align === "right" ? "text-right" : "text-left")}
                    >
                      <button
                        type="button"
                        className="inline-flex items-center gap-1 uppercase"
                        onClick={() => setSort((p) => (p.key === c.key ? { key: c.key, dir: p.dir === 1 ? -1 : 1 } : { key: c.key, dir: 1 }))}
                      >
                        {c.label}
                        {sort.key === c.key ? sort.dir === 1 ? <ArrowUp className="h-3 w-3" aria-hidden="true" /> : <ArrowDown className="h-3 w-3" aria-hidden="true" /> : null}
                      </button>
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {slice.map((row) => (
                  <tr key={rowKey(row)} className="hover:bg-accent">
                    {columns.map((c) => (
                      <td key={c.key} className={cn("px-3 py-2 text-foreground-secondary", c.align === "right" && "text-right tabular-nums")}>
                        {c.render(row)}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="flex items-center justify-between text-xs text-foreground-secondary">
            <span>{view.length} row{view.length === 1 ? "" : "s"}</span>
            {pages > 1 ? (
              <div className="flex items-center gap-2">
                <Button type="button" size="sm" variant="outline" disabled={current <= 1} onClick={() => setPage(current - 1)}>
                  Previous
                </Button>
                <span>Page {current} of {pages}</span>
                <Button type="button" size="sm" variant="outline" disabled={current >= pages} onClick={() => setPage(current + 1)}>
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

const REPORTS = [
  { key: "daily", label: "Daily attendance" },
  { key: "present_absent", label: "Present / absent" },
  { key: "late_early", label: "Late / early" },
  { key: "hours", label: "Work hours" },
  { key: "overtime", label: "Overtime" },
  { key: "payroll", label: "Payroll attendance" },
] as const;
type ReportKey = (typeof REPORTS)[number]["key"];

interface ReportsPanelProps {
  rows: AttendanceDay[];
  employeesById: Map<string, EmployeeLite>;
  overtime: Section<OvertimeRecord[]>;
  periods: Section<AttendancePeriod[]>;
  timezone: string;
  today: string;
  rangeLabel: string;
}

function PayrollReport({ periods, employeesById, today }: Pick<ReportsPanelProps, "periods" | "employeesById" | "today">) {
  const period = useMemo(() => pickDefaultPeriod(periods.data ?? [], today), [periods.data, today]);
  const summary = usePeriodSummary(period?.id ?? null);
  if (!period) return <p className="text-sm text-foreground-secondary">No attendance period to report on yet.</p>;
  if (summary.status === "loading" || summary.status === "idle") return <p role="status" className="text-sm text-foreground-secondary">Loading period summary…</p>;
  if (summary.status === "error") {
    return (
      <p role="alert" className="text-sm text-foreground-secondary">
        {summary.error?.status === 403 ? "You do not have permission to view the period summary." : "The period summary failed to load."}{" "}
        {summary.error?.status === 403 ? null : <button type="button" className="underline" onClick={summary.retry}>Try again</button>}
      </p>
    );
  }
  const rows = summary.data ?? [];
  const num = (v: string | null) => (v === null ? -1 : Number(v));
  return (
    <div className="space-y-2">
      <p className="text-xs text-foreground-muted">
        {period.label ?? `${formatShortDate(period.period_start)} – ${formatShortDate(period.period_end)}`} ·{" "}
        <Link href={`/app/attendance-periods/${period.id}`} className="underline">Open period</Link>
      </p>
      <ReportTable
        rows={rows}
        rowKey={(r) => r.employee_id}
        searchText={(r) => employeeName(employeesById.get(r.employee_id), r.employee_id)}
        empty="No employees in this period summary."
        columns={[
          { key: "name", label: "Employee", render: (r) => employeeName(employeesById.get(r.employee_id), r.employee_id), sort: (r) => employeeName(employeesById.get(r.employee_id), r.employee_id).toLowerCase() },
          { key: "payable", label: "Payable", align: "right", render: (r) => r.payable_days ?? "—", sort: (r) => num(r.payable_days) },
          { key: "paid", label: "Paid", align: "right", render: (r) => r.paid_days ?? "—", sort: (r) => num(r.paid_days) },
          { key: "present", label: "Present", align: "right", render: (r) => r.present_days, sort: (r) => Number(r.present_days) },
          { key: "absent", label: "Absent", align: "right", render: (r) => r.absent_days, sort: (r) => Number(r.absent_days) },
          { key: "leave", label: "Leave", align: "right", render: (r) => r.leave_days, sort: (r) => Number(r.leave_days) },
          { key: "lop", label: "LOP", align: "right", render: (r) => r.lop_days, sort: (r) => Number(r.lop_days) },
          { key: "ot", label: "OT", align: "right", render: (r) => formatMinutes(r.ot_minutes_normal + r.ot_minutes_weekly_off + r.ot_minutes_holiday + r.ot_minutes_night), sort: (r) => r.ot_minutes_normal + r.ot_minutes_weekly_off + r.ot_minutes_holiday + r.ot_minutes_night },
        ]}
      />
    </div>
  );
}

/** Read-only reports over data the existing endpoints already return. They carry search, sort and
 * paging; there is deliberately no export, because the backend has no export endpoint yet. */
export function ReportsPanel(props: ReportsPanelProps) {
  const { rows, employeesById, overtime, timezone, rangeLabel } = props;
  const [report, setReport] = useState<ReportKey>("daily");
  const name = (id: string) => employeeName(employeesById.get(id), id);

  const perEmployee = useMemo(() => {
    const map = new Map<string, { id: string; present: number; absent: number; leave: number; half: number; worked: number; scheduled: number; days: number }>();
    for (const day of rows) {
      const e = map.get(day.employee_id) ?? { id: day.employee_id, present: 0, absent: 0, leave: 0, half: 0, worked: 0, scheduled: 0, days: 0 };
      const bucket = bucketOf(day);
      if (bucket === "PRESENT" || bucket === "REMOTE" || bucket === "ON_DUTY") e.present += 1;
      if (bucket === "ABSENT") e.absent += 1;
      if (bucket === "LEAVE") e.leave += 1;
      if (bucket === "HALF_DAY") e.half += 1;
      if (day.actual_first_in) {
        e.days += 1;
        e.worked += day.worked_minutes;
        e.scheduled += day.scheduled_minutes ?? 0;
      }
      map.set(day.employee_id, e);
    }
    return Array.from(map.values());
  }, [rows]);

  let body: ReactNode;
  if (report === "daily") {
    body = (
      <ReportTable
        rows={rows}
        rowKey={(d) => d.id}
        searchText={(d) => `${name(d.employee_id)} ${BUCKET_LABELS[bucketOf(d)]}`}
        empty="No attendance days in this range."
        columns={[
          { key: "date", label: "Date", render: (d) => formatShortDate(d.attendance_date), sort: (d) => d.attendance_date },
          { key: "name", label: "Employee", render: (d) => name(d.employee_id), sort: (d) => name(d.employee_id).toLowerCase() },
          { key: "status", label: "Status", render: (d) => BUCKET_LABELS[bucketOf(d)], sort: (d) => BUCKET_LABELS[bucketOf(d)] },
          { key: "in", label: "In", render: (d) => formatClockTime(d.actual_first_in, timezone), sort: (d) => d.actual_first_in ?? "" },
          { key: "out", label: "Out", render: (d) => formatClockTime(d.actual_last_out, timezone), sort: (d) => d.actual_last_out ?? "" },
          { key: "worked", label: "Worked", align: "right", render: (d) => formatMinutes(d.worked_minutes), sort: (d) => d.worked_minutes },
        ]}
      />
    );
  } else if (report === "present_absent") {
    body = (
      <ReportTable
        rows={perEmployee}
        rowKey={(e) => e.id}
        searchText={(e) => name(e.id)}
        empty="No attendance days in this range."
        columns={[
          { key: "name", label: "Employee", render: (e) => name(e.id), sort: (e) => name(e.id).toLowerCase() },
          { key: "present", label: "Present", align: "right", render: (e) => e.present, sort: (e) => e.present },
          { key: "half", label: "Half day", align: "right", render: (e) => e.half, sort: (e) => e.half },
          { key: "absent", label: "Absent", align: "right", render: (e) => e.absent, sort: (e) => e.absent },
          { key: "leave", label: "Leave", align: "right", render: (e) => e.leave, sort: (e) => e.leave },
        ]}
      />
    );
  } else if (report === "late_early") {
    body = (
      <ReportTable
        rows={rows.filter((d) => d.is_late || d.is_early_out)}
        rowKey={(d) => d.id}
        searchText={(d) => name(d.employee_id)}
        empty="No late arrivals or early departures in this range."
        columns={[
          { key: "date", label: "Date", render: (d) => formatShortDate(d.attendance_date), sort: (d) => d.attendance_date },
          { key: "name", label: "Employee", render: (d) => name(d.employee_id), sort: (d) => name(d.employee_id).toLowerCase() },
          { key: "late", label: "Late (min)", align: "right", render: (d) => (d.is_late ? d.late_minutes : "—"), sort: (d) => (d.is_late ? d.late_minutes : -1) },
          { key: "early", label: "Early out (min)", align: "right", render: (d) => (d.is_early_out ? d.early_departure_minutes : "—"), sort: (d) => (d.is_early_out ? d.early_departure_minutes : -1) },
        ]}
      />
    );
  } else if (report === "hours") {
    body = (
      <ReportTable
        rows={perEmployee.filter((e) => e.days > 0)}
        rowKey={(e) => e.id}
        searchText={(e) => name(e.id)}
        empty="No worked hours in this range."
        columns={[
          { key: "name", label: "Employee", render: (e) => name(e.id), sort: (e) => name(e.id).toLowerCase() },
          { key: "days", label: "Days", align: "right", render: (e) => e.days, sort: (e) => e.days },
          { key: "worked", label: "Worked", align: "right", render: (e) => formatMinutes(e.worked), sort: (e) => e.worked },
          { key: "avg", label: "Average", align: "right", render: (e) => formatMinutes(Math.round(e.worked / e.days)), sort: (e) => e.worked / e.days },
          { key: "scheduled", label: "Scheduled", align: "right", render: (e) => formatMinutes(e.scheduled), sort: (e) => e.scheduled },
        ]}
      />
    );
  } else if (report === "overtime") {
    body =
      overtime.status === "error" ? (
        <p role="alert" className="text-sm text-foreground-secondary">
          {overtime.error?.status === 403 ? "You do not have permission to view overtime." : "Overtime records failed to load."}
        </p>
      ) : overtime.status !== "ready" ? (
        <p role="status" className="text-sm text-foreground-secondary">Loading overtime…</p>
      ) : (
        <ReportTable
          rows={overtime.data ?? []}
          rowKey={(r) => r.id}
          searchText={(r) => name(r.employee_id)}
          empty="No overtime recorded for this range."
          columns={[
            { key: "date", label: "Date", render: (r) => formatShortDate(r.attendance_date), sort: (r) => r.attendance_date },
            { key: "name", label: "Employee", render: (r) => name(r.employee_id), sort: (r) => name(r.employee_id).toLowerCase() },
            { key: "class", label: "Day class", render: (r) => (r.day_class ? OVERTIME_DAY_CLASS_LABELS[r.day_class as OvertimeDayClass] ?? r.day_class : "—"), sort: (r) => r.day_class ?? "" },
            { key: "detected", label: "Detected", align: "right", render: (r) => formatMinutes(r.minutes_detected), sort: (r) => r.minutes_detected },
            { key: "approved", label: "Approved", align: "right", render: (r) => formatMinutes(r.minutes_approved), sort: (r) => r.minutes_approved },
            { key: "status", label: "Status", render: (r) => OVERTIME_STATUS_LABELS[r.status], sort: (r) => r.status },
          ]}
        />
      );
  } else {
    body = <PayrollReport periods={props.periods} employeesById={employeesById} today={props.today} />;
  }

  return (
    <SectionCard
      id="att-reports"
      title="Reports"
      description={`${rangeLabel}. Read-only views of existing attendance data.`}
      status="ready"
    >
      <div role="tablist" aria-label="Reports" className="flex flex-wrap gap-1.5">
        {REPORTS.map((r) => (
          <button
            key={r.key}
            type="button"
            role="tab"
            aria-selected={report === r.key}
            onClick={() => setReport(r.key)}
            className={cn(
              "rounded-md border px-3 py-1.5 text-sm",
              report === r.key ? "border-primary bg-primary-subtle text-primary" : "border-border text-foreground-secondary hover:bg-muted",
            )}
          >
            {r.label}
          </button>
        ))}
      </div>
      <div role="tabpanel">{body}</div>
      <p className="text-xs text-foreground-muted">
        Export (CSV / Excel / PDF) is not available yet — the backend has no attendance export endpoint.
      </p>
    </SectionCard>
  );
}
