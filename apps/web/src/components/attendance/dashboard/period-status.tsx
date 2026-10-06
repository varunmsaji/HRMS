"use client";

import Link from "next/link";
import { useMemo, useState } from "react";

import { AttendancePeriodStatusBadge } from "@/components/attendance-period/attendance-period-status-badge";
import { SectionCard } from "@/components/attendance/dashboard/section-card";
import { usePeriodSummary, type Section } from "@/components/attendance/dashboard/use-dashboard-data";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { NativeSelect } from "@/components/ui/native-select";
import type { AttendancePeriod } from "@/lib/attendance-period/types";
import { formatMinutes } from "@/lib/attendance/format";
import { formatShortDate, pickDefaultPeriod, sumPeriodSummary } from "@/lib/attendance/dashboard";

function periodTitle(period: AttendancePeriod): string {
  return period.label ?? `${formatShortDate(period.period_start)} – ${formatShortDate(period.period_end)}`;
}

interface PeriodStatusProps {
  periods: Section<AttendancePeriod[]>;
  entityNames: Map<string, string>;
  today: string;
}

/** Attendance periods are legal-entity scoped; this only surfaces their state and links to the
 * existing period detail page — no period action is exposed from the dashboard. The backend
 * records a validation verdict (READY/BLOCKED) but exposes the blocker breakdown only through the
 * period's own validate action, so counts live on the detail page. */
export function PeriodStatus({ periods, entityNames, today }: PeriodStatusProps) {
  const list = (periods.data ?? []).slice().sort((a, b) => b.period_start.localeCompare(a.period_start)).slice(0, 6);
  return (
    <SectionCard
      id="att-periods"
      title="Attendance periods"
      description="Payroll-facing cycles, one per legal entity."
      status={periods.status}
      error={periods.error}
      onRetry={periods.retry}
      empty={list.length === 0 ? { title: "No attendance periods yet.", description: "Periods are opened per legal entity." } : null}
      actions={
        <Button asChild size="sm" variant="outline">
          <Link href="/app/attendance-periods">All periods →</Link>
        </Button>
      }
    >
      <ul className="divide-y divide-border rounded-md border border-border">
        {list.map((period) => (
          <li key={period.id}>
            <Link href={`/app/attendance-periods/${period.id}`} className="flex flex-wrap items-center gap-x-3 gap-y-1 px-3 py-2.5 hover:bg-accent">
              <div className="min-w-0 flex-1">
                <p className="text-sm font-medium text-foreground">{periodTitle(period)}</p>
                <p className="text-xs text-foreground-muted">
                  {entityNames.get(period.legal_entity_id) ?? "Legal entity"} · {formatShortDate(period.period_start)} – {formatShortDate(period.period_end)}
                </p>
              </div>
              <AttendancePeriodStatusBadge status={period.status} />
              {period.status === "OPEN" && period.last_validation_status === "BLOCKED" ? (
                <Badge variant="danger">Validation blocked</Badge>
              ) : null}
              {period.status === "OPEN" && period.last_validation_status === "READY" ? (
                <Badge variant="success">Ready to finalize</Badge>
              ) : null}
              {period.status === "OPEN" && period.last_validation_status === null ? (
                <Badge variant="outline">Not validated</Badge>
              ) : null}
              {period.reopened_at ? <Badge variant="warning">Reopened</Badge> : null}
            </Link>
          </li>
        ))}
      </ul>
      <p className="text-xs text-foreground-muted">As of {formatShortDate(today)}.</p>
    </SectionCard>
  );
}

function fmtDays(value: number | null): string {
  return value === null ? "—" : Number.isInteger(value) ? String(value) : value.toFixed(1);
}

/** Totals of the backend's own period summary (live preview while OPEN, frozen snapshot once
 * CLOSED) — these are the numbers Payroll reads. */
export function MonthlySummary({ periods, today }: { periods: Section<AttendancePeriod[]>; today: string }) {
  const list = useMemo(() => (periods.data ?? []).slice().sort((a, b) => b.period_start.localeCompare(a.period_start)), [periods.data]);
  const defaultPeriod = useMemo(() => pickDefaultPeriod(list, today), [list, today]);
  const [chosen, setChosen] = useState<string>("");
  const periodId = chosen || defaultPeriod?.id || null;
  const summary = usePeriodSummary(periods.status === "ready" ? periodId : null);
  const totals = useMemo(() => (summary.data ? sumPeriodSummary(summary.data) : null), [summary.data]);

  const status = periods.status !== "ready" ? periods.status : periodId === null ? "ready" : summary.status;
  const stats: [string, string][] = totals
    ? [
        ["Payable days", fmtDays(totals.payableDays)],
        ["Paid days", fmtDays(totals.paidDays)],
        ["Present", fmtDays(totals.presentDays)],
        ["Half days", fmtDays(totals.halfDays)],
        ["Absent", fmtDays(totals.absentDays)],
        ["Leave", fmtDays(totals.leaveDays)],
        ["Holidays", fmtDays(totals.holidayDays)],
        ["Weekly offs", fmtDays(totals.weeklyOffDays)],
        ["On duty", fmtDays(totals.onDutyDays)],
        ["Incomplete", fmtDays(totals.incompleteDays)],
        ["LOP", fmtDays(totals.lopDays)],
        ["Not employed", fmtDays(totals.notEmployedDays)],
        ["Overtime", formatMinutes(totals.otMinutes)],
        ["Late count", String(totals.lateCount)],
      ]
    : [];

  return (
    <SectionCard
      id="att-monthly"
      title="Monthly attendance summary"
      description="Employee-days across the period, as Payroll will read them."
      status={status}
      error={periods.status === "error" ? periods.error : summary.error}
      onRetry={periods.status === "error" ? periods.retry : summary.retry}
      empty={periodId === null ? { title: "No attendance period to summarise.", description: "Open a period for a legal entity first." } : null}
      actions={
        list.length > 1 ? (
          <>
            <label htmlFor="att-summary-period" className="sr-only">
              Period
            </label>
            <NativeSelect id="att-summary-period" className="w-56" value={periodId ?? ""} onChange={(e) => setChosen(e.target.value)}>
              {list.map((p) => (
                <option key={p.id} value={p.id}>
                  {periodTitle(p)}
                </option>
              ))}
            </NativeSelect>
          </>
        ) : null
      }
    >
      {totals ? (
        <>
          <div className="flex flex-wrap items-center gap-2 text-xs text-foreground-secondary">
            <Badge variant={totals.frozen ? "outline" : "info"}>{totals.frozen ? "Frozen snapshot" : "Live preview"}</Badge>
            <span>{totals.employees} employee{totals.employees === 1 ? "" : "s"}</span>
          </div>
          <dl className="grid grid-cols-2 gap-3 sm:grid-cols-4 lg:grid-cols-7">
            {stats.map(([label, value]) => (
              <div key={label} className="rounded-md border border-border p-3">
                <dt className="text-xs text-foreground-muted">{label}</dt>
                <dd className="mt-1 text-lg font-semibold tabular-nums text-foreground">{value}</dd>
              </div>
            ))}
          </dl>
        </>
      ) : null}
    </SectionCard>
  );
}
