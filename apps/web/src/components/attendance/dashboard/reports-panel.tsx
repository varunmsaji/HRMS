"use client";

import { ArrowDown, ArrowUp, Download, Search } from "lucide-react";
import Link from "next/link";
import { useMemo, useState, type ReactNode } from "react";

import { SectionCard } from "@/components/attendance/dashboard/section-card";
import { usePeriodSummary, type Section } from "@/components/attendance/dashboard/use-dashboard-data";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/native-select";
import type { AttendancePeriod } from "@/lib/attendance-period/types";
import {
  BUCKET_LABELS,
  bucketOf,
  employeeName,
  formatShortDate,
  pickDefaultPeriod,
  type EmployeeLite,
} from "@/lib/attendance/dashboard";
import { useToast } from "@/components/common/toast";
import { apiClient } from "@/lib/api/client";
import { describeApiError } from "@/lib/api/errors";
import {
  EXPORT_FORMAT_LABELS,
  downloadCsv,
  exportFileName,
  exportWindowError,
  reportExportPath,
  saveDownloadedFile,
  toCsv,
  type CsvCell,
  type ExportFormat,
  type ServerReport,
} from "@/lib/attendance/export";
import { formatClockTime, formatMinutes } from "@/lib/attendance/format";
import type { AttendanceDay } from "@/lib/attendance/types";
import { overtimePending, overtimeTotals, REPORT_BASIS } from "@/lib/attendance/report-basis";
import { OVERTIME_DAY_CLASS_LABELS, OVERTIME_STATUS_LABELS, type OvertimeDayClass, type OvertimeRecord } from "@/lib/overtime/types";
import { cn } from "@/lib/utils";

const PAGE_SIZE = 15;

/** A table cell that opens the employee's own attendance, so a row leads to the person. */
function EmployeeLink({ id, children }: { id: string; children: ReactNode }) {
  return (
    <Link href={`/app/attendance/employee/${id}`} className="text-foreground hover:underline">
      {children}
    </Link>
  );
}

/** A table cell that opens one attendance day, with its timeline and why it was decided so. */
function DayLink({ id, label, children }: { id: string; label: string; children: ReactNode }) {
  return (
    <Link href={`/app/attendance/${id}`} aria-label={label} className="text-foreground hover:underline">
      {children}
    </Link>
  );
}

interface Column<T> {
  key: string;
  label: string;
  render: (row: T) => ReactNode;
  sort: (row: T) => string | number;
  /** What the CSV holds when it differs from `sort` (a "—" cell, a clock time, a null). */
  csv?: (row: T) => CsvCell;
  align?: "right";
}

interface ReportTableProps<T> {
  rows: T[];
  columns: Column<T>[];
  rowKey: (row: T) => string;
  searchText: (row: T) => string;
  empty: string;
  /** Names the file; the export holds every row the search leaves, not just the page. */
  exportName: string;
}

function ReportTable<T>({ rows, columns, rowKey, searchText, empty, exportName }: ReportTableProps<T>) {
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

  const exportCsv = () =>
    downloadCsv(
      exportName,
      toCsv(
        columns.map((c) => c.label),
        view.map((row) => columns.map((c) => (c.csv ? c.csv(row) : c.sort(row)))),
      ),
    );

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
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
      <Button type="button" size="sm" variant="outline" disabled={view.length === 0} onClick={exportCsv}>
        <Download className="mr-1.5 h-4 w-4" aria-hidden="true" />
        Export CSV
      </Button>
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

function OvertimeTotalsLine({ records }: { records: OvertimeRecord[] }) {
  if (records.length === 0) return null;
  const t = overtimeTotals(records);
  return (
    <p className="text-sm text-foreground">
      <span className="font-medium">Found</span> {formatMinutes(t.found)} · <span className="font-medium">Approved</span>{" "}
      {formatMinutes(t.approved)} · <span className="font-medium">Pending</span> {formatMinutes(t.pending)}
    </p>
  );
}

const SERVER_REPORTS: Partial<Record<ReportKey, ServerReport>> = {
  daily: "daily",
  present_absent: "present-absent",
  late_early: "late-early",
  hours: "hours",
  overtime: "overtime",
};

/** Exports a report for any period up to a year from the server, in place of the on-screen rows:
 * the page loads at most a quarter, and the file holds only the employees the caller may see. */
function PeriodExport({
  report,
  label,
  query,
  today,
}: {
  report: ServerReport;
  label: string;
  query: Record<string, string>;
  today: string;
}) {
  const { toast } = useToast();
  const [from, setFrom] = useState(query.date_from);
  const [to, setTo] = useState(query.date_to);
  const [format, setFormat] = useState<ExportFormat>("csv");
  const [busy, setBusy] = useState(false);
  const problem = exportWindowError(from, to, today);

  async function download() {
    setBusy(true);
    try {
      const file = await apiClient.download(reportExportPath(report, { ...query, date_from: from, date_to: to }, format));
      saveDownloadedFile(file, `${report}_${from}_${to}.${format}`);
    } catch (err) {
      toast({ title: "Could not export the report", description: describeApiError(err), variant: "danger" });
    } finally {
      setBusy(false);
    }
  }

  return (
    <div role="group" aria-label={`Export ${label} for a period`} className="flex flex-wrap items-end gap-2 rounded-md border border-border bg-surface-secondary/40 p-3">
      <div className="space-y-1">
        <label htmlFor="att-export-from" className="text-xs text-foreground-muted">From</label>
        <Input id="att-export-from" type="date" max={today} value={from} onChange={(e) => setFrom(e.target.value)} className="w-40" />
      </div>
      <div className="space-y-1">
        <label htmlFor="att-export-to" className="text-xs text-foreground-muted">To</label>
        <Input id="att-export-to" type="date" max={today} value={to} onChange={(e) => setTo(e.target.value)} className="w-40" />
      </div>
      <div className="space-y-1">
        <label htmlFor="att-export-format" className="text-xs text-foreground-muted">Format</label>
        <NativeSelect id="att-export-format" className="w-28" value={format} onChange={(e) => setFormat(e.target.value as ExportFormat)}>
          {(Object.keys(EXPORT_FORMAT_LABELS) as ExportFormat[]).map((f) => (
            <option key={f} value={f}>
              {EXPORT_FORMAT_LABELS[f]}
            </option>
          ))}
        </NativeSelect>
      </div>
      <Button type="button" size="sm" variant="outline" disabled={busy || problem !== null} onClick={download}>
        <Download className="mr-1.5 h-4 w-4" aria-hidden="true" />
        {busy ? "Preparing…" : "Export period"}
      </Button>
      <p className={cn("basis-full text-xs", problem ? "text-danger" : "text-foreground-muted")} role={problem ? "alert" : undefined}>
        {problem ?? "Up to a year, with the filters above, for the employees you can see. PDF holds up to 5,000 rows."}
      </p>
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
  /** The dashboard's window and population filters, as the API reads them. */
  exportQuery: Record<string, string>;
  /** Payroll attendance is the period close: HR only, so a manager is not offered it. */
  showPayroll: boolean;
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
        exportName={exportFileName("payroll-attendance", period.label ?? `${period.period_start}-${period.period_end}`)}
        columns={[
          { key: "name", label: "Employee", render: (r) => <EmployeeLink id={r.employee_id}>{employeeName(employeesById.get(r.employee_id), r.employee_id)}</EmployeeLink>, sort: (r) => employeeName(employeesById.get(r.employee_id), r.employee_id).toLowerCase(), csv: (r) => employeeName(employeesById.get(r.employee_id), r.employee_id) },
          { key: "payable", label: "Payable", align: "right", render: (r) => r.payable_days ?? "—", sort: (r) => num(r.payable_days), csv: (r) => r.payable_days },
          { key: "paid", label: "Paid", align: "right", render: (r) => r.paid_days ?? "—", sort: (r) => num(r.paid_days), csv: (r) => r.paid_days },
          { key: "present", label: "Present", align: "right", render: (r) => r.present_days, sort: (r) => Number(r.present_days) },
          { key: "absent", label: "Absent", align: "right", render: (r) => r.absent_days, sort: (r) => Number(r.absent_days) },
          { key: "leave", label: "Leave", align: "right", render: (r) => r.leave_days, sort: (r) => Number(r.leave_days) },
          { key: "lop", label: "LOP", align: "right", render: (r) => r.lop_days, sort: (r) => Number(r.lop_days) },
          { key: "ot", label: "OT (min)", align: "right", render: (r) => formatMinutes(r.ot_minutes_normal + r.ot_minutes_weekly_off + r.ot_minutes_holiday + r.ot_minutes_night), sort: (r) => r.ot_minutes_normal + r.ot_minutes_weekly_off + r.ot_minutes_holiday + r.ot_minutes_night, csv: (r) => r.ot_minutes_normal + r.ot_minutes_weekly_off + r.ot_minutes_holiday + r.ot_minutes_night },
        ]}
      />
    </div>
  );
}

/** Reports over data the existing endpoints already return. They carry search, sort, paging and a
 * CSV export of every row the search leaves. The export is built in the browser from the rows on
 * screen, so it covers the range the page loaded and no more. */
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
        exportName={exportFileName("daily-attendance", rangeLabel)}
        columns={[
          { key: "date", label: "Date", render: (d) => <DayLink id={d.id} label={`Open ${name(d.employee_id)} on ${formatShortDate(d.attendance_date)}`}>{formatShortDate(d.attendance_date)}</DayLink>, sort: (d) => d.attendance_date },
          { key: "name", label: "Employee", render: (d) => <EmployeeLink id={d.employee_id}>{name(d.employee_id)}</EmployeeLink>, sort: (d) => name(d.employee_id).toLowerCase(), csv: (d) => name(d.employee_id) },
          { key: "status", label: "Status", render: (d) => BUCKET_LABELS[bucketOf(d)], sort: (d) => BUCKET_LABELS[bucketOf(d)] },
          { key: "in", label: "In", render: (d) => formatClockTime(d.actual_first_in, timezone), sort: (d) => d.actual_first_in ?? "", csv: (d) => formatClockTime(d.actual_first_in, timezone) },
          { key: "out", label: "Out", render: (d) => formatClockTime(d.actual_last_out, timezone), sort: (d) => d.actual_last_out ?? "", csv: (d) => formatClockTime(d.actual_last_out, timezone) },
          { key: "worked", label: "Worked (min)", align: "right", render: (d) => formatMinutes(d.worked_minutes), sort: (d) => d.worked_minutes },
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
        exportName={exportFileName("present-absent", rangeLabel)}
        columns={[
          { key: "name", label: "Employee", render: (e) => <EmployeeLink id={e.id}>{name(e.id)}</EmployeeLink>, sort: (e) => name(e.id).toLowerCase(), csv: (e) => name(e.id) },
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
        exportName={exportFileName("late-early", rangeLabel)}
        columns={[
          { key: "date", label: "Date", render: (d) => <DayLink id={d.id} label={`Open ${name(d.employee_id)} on ${formatShortDate(d.attendance_date)}`}>{formatShortDate(d.attendance_date)}</DayLink>, sort: (d) => d.attendance_date },
          { key: "name", label: "Employee", render: (d) => <EmployeeLink id={d.employee_id}>{name(d.employee_id)}</EmployeeLink>, sort: (d) => name(d.employee_id).toLowerCase(), csv: (d) => name(d.employee_id) },
          { key: "late", label: "Late (min)", align: "right", render: (d) => (d.is_late ? d.late_minutes : "—"), sort: (d) => (d.is_late ? d.late_minutes : -1), csv: (d) => (d.is_late ? d.late_minutes : "") },
          { key: "early", label: "Early out (min)", align: "right", render: (d) => (d.is_early_out ? d.early_departure_minutes : "—"), sort: (d) => (d.is_early_out ? d.early_departure_minutes : -1), csv: (d) => (d.is_early_out ? d.early_departure_minutes : "") },
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
        exportName={exportFileName("work-hours", rangeLabel)}
        columns={[
          { key: "name", label: "Employee", render: (e) => <EmployeeLink id={e.id}>{name(e.id)}</EmployeeLink>, sort: (e) => name(e.id).toLowerCase(), csv: (e) => name(e.id) },
          { key: "days", label: "Days", align: "right", render: (e) => e.days, sort: (e) => e.days },
          { key: "worked", label: "Worked (min)", align: "right", render: (e) => formatMinutes(e.worked), sort: (e) => e.worked },
          { key: "avg", label: "Average (min)", align: "right", render: (e) => formatMinutes(Math.round(e.worked / e.days)), sort: (e) => e.worked / e.days, csv: (e) => Math.round(e.worked / e.days) },
          { key: "scheduled", label: "Scheduled (min)", align: "right", render: (e) => formatMinutes(e.scheduled), sort: (e) => e.scheduled },
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
        <div className="space-y-2">
          <OvertimeTotalsLine records={overtime.data ?? []} />
        <ReportTable
          rows={overtime.data ?? []}
          rowKey={(r) => r.id}
          searchText={(r) => name(r.employee_id)}
          empty="No overtime recorded for this range."
          exportName={exportFileName("overtime", rangeLabel)}
          columns={[
            { key: "date", label: "Date", render: (r) => <DayLink id={r.attendance_day_id} label={`Open ${name(r.employee_id)} on ${formatShortDate(r.attendance_date)}`}>{formatShortDate(r.attendance_date)}</DayLink>, sort: (r) => r.attendance_date },
            { key: "name", label: "Employee", render: (r) => <EmployeeLink id={r.employee_id}>{name(r.employee_id)}</EmployeeLink>, sort: (r) => name(r.employee_id).toLowerCase(), csv: (r) => name(r.employee_id) },
            { key: "class", label: "Day class", render: (r) => (r.day_class ? OVERTIME_DAY_CLASS_LABELS[r.day_class as OvertimeDayClass] ?? r.day_class : "—"), sort: (r) => r.day_class ?? "", csv: (r) => (r.day_class ? OVERTIME_DAY_CLASS_LABELS[r.day_class as OvertimeDayClass] ?? r.day_class : "") },
            { key: "detected", label: "Detected (min)", align: "right", render: (r) => formatMinutes(r.minutes_detected), sort: (r) => r.minutes_detected },
            { key: "approved", label: "Approved (min)", align: "right", render: (r) => formatMinutes(r.minutes_approved), sort: (r) => r.minutes_approved },
            { key: "pending", label: "Pending (min)", align: "right", render: (r) => (overtimePending(r) > 0 ? formatMinutes(overtimePending(r)) : "—"), sort: (r) => overtimePending(r) },
            { key: "status", label: "Status", render: (r) => OVERTIME_STATUS_LABELS[r.status], sort: (r) => r.status },
          ]}
        />
        </div>
      );
  } else {
    body = <PayrollReport periods={props.periods} employeesById={employeesById} today={props.today} />;
  }

  return (
    <SectionCard
      id="att-reports"
      title="Reports"
      description={`${rangeLabel}. Search, sort and export existing attendance data. Names and dates open the person or the day.`}
      status="ready"
    >
      <div role="tablist" aria-label="Reports" className="flex flex-wrap gap-1.5">
        {REPORTS.filter((r) => r.key !== "payroll" || props.showPayroll).map((r) => (
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
      <p className="text-xs text-foreground-secondary">{REPORT_BASIS[report]}</p>
      {SERVER_REPORTS[report] ? (
        <PeriodExport
          // A new report or a new range starts from the page's range again.
          key={`${report}-${props.exportQuery.date_from}-${props.exportQuery.date_to}`}
          report={SERVER_REPORTS[report]}
          label={REPORTS.find((r) => r.key === report)?.label ?? "report"}
          query={props.exportQuery}
          today={props.today}
        />
      ) : null}
      <div role="tabpanel">{body}</div>
    </SectionCard>
  );
}
