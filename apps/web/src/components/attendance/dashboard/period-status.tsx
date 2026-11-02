"use client";

import Link from "next/link";
import {
  AlarmClock,
  Ban,
  BriefcaseBusiness,
  CalendarCheck,
  CalendarOff,
  CircleAlert,
  CircleCheck,
  CircleX,
  Clock,
  Hourglass,
  Palmtree,
  PartyPopper,
  UserRoundX,
  Wallet,
  type LucideIcon,
} from "lucide-react";
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
  /** Company picker — periods are the only data that is legal-entity scoped, so the filter lives here. */
  entities?: { id: string; name: string }[];
  legalEntityId?: string;
  onEntityChange?: (legalEntityId: string) => void;
}

/** Attendance periods are legal-entity scoped; this only surfaces their state and links to the
 * existing period detail page — no period action is exposed from the dashboard. The backend
 * records a validation verdict (READY/BLOCKED) but exposes the blocker breakdown only through the
 * period's own validate action, so counts live on the detail page. */
export function PeriodStatus({ periods, entityNames, today, entities = [], legalEntityId = "", onEntityChange }: PeriodStatusProps) {
  const list = (periods.data ?? []).slice().sort((a, b) => b.period_start.localeCompare(a.period_start)).slice(0, 6);
  return (
    <SectionCard
      id="att-periods"
      title="Attendance periods"
      description="Payroll-facing cycles, one per company."
      status={periods.status}
      error={periods.error}
      onRetry={periods.retry}
      empty={list.length === 0 ? { title: "No attendance periods yet.", description: "Periods are opened per company." } : null}
      actions={
        <div className="flex items-center gap-2">
          {entities.length > 0 && onEntityChange ? (
            <NativeSelect
              aria-label="Company (periods)"
              value={legalEntityId}
              onChange={(e) => onEntityChange(e.target.value)}
              className="h-8 w-44 text-xs"
            >
              <option value="">All companies</option>
              {entities.map((entity) => (
                <option key={entity.id} value={entity.id}>
                  {entity.name}
                </option>
              ))}
            </NativeSelect>
          ) : null}
          <Button asChild size="sm" variant="outline">
            <Link href="/app/attendance-periods">All periods →</Link>
          </Button>
        </div>
      }
    >
      <ul className="divide-y divide-border rounded-md border border-border">
        {list.map((period) => (
          <li key={period.id}>
            <Link href={`/app/attendance-periods/${period.id}`} className="flex flex-wrap items-center gap-x-3 gap-y-1 px-3 py-2.5 hover:bg-accent">
              <div className="min-w-0 flex-1">
                <p className="text-sm font-medium text-foreground">{periodTitle(period)}</p>
                <p className="text-xs text-foreground-muted">
                  {entityNames.get(period.legal_entity_id) ?? "Company"} · {formatShortDate(period.period_start)} – {formatShortDate(period.period_end)}
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

type StatTone = "success" | "danger" | "warning" | "info" | "muted";

/** Icon + colour per stat. `fill` marks day-counts, which get a liquid level against the largest day-count. */
const STAT_STYLE: Record<string, { icon: LucideIcon; tone: StatTone; fill: boolean }> = {
  "Payable days": { icon: Wallet, tone: "info", fill: true },
  "Paid days": { icon: CircleCheck, tone: "success", fill: true },
  Present: { icon: CalendarCheck, tone: "success", fill: true },
  "Half days": { icon: Hourglass, tone: "warning", fill: true },
  Absent: { icon: CircleX, tone: "danger", fill: true },
  Leave: { icon: Palmtree, tone: "info", fill: true },
  Holidays: { icon: PartyPopper, tone: "info", fill: true },
  "Weekly offs": { icon: CalendarOff, tone: "muted", fill: true },
  "On duty": { icon: BriefcaseBusiness, tone: "info", fill: true },
  Incomplete: { icon: CircleAlert, tone: "warning", fill: true },
  LOP: { icon: Ban, tone: "danger", fill: true },
  "Not employed": { icon: UserRoundX, tone: "muted", fill: true },
  Overtime: { icon: Clock, tone: "info", fill: false },
  "Late count": { icon: AlarmClock, tone: "warning", fill: false },
};

const TONE_VAR: Record<StatTone, string> = {
  success: "var(--color-success)",
  danger: "var(--color-danger)",
  warning: "var(--color-warning)",
  info: "var(--color-info)",
  muted: "var(--color-foreground-muted, #64748b)",
};

function StatTile({ label, value, level }: { label: string; value: string; level: number }) {
  const style = STAT_STYLE[label];
  const Icon = style?.icon ?? CircleCheck;
  const color = TONE_VAR[style?.tone ?? "muted"];
  return (
    <div className="relative overflow-hidden rounded-xl border p-3" style={{ borderColor: `color-mix(in srgb, ${color} 28%, transparent)`, backgroundColor: `color-mix(in srgb, ${color} 5%, transparent)` }}>
      {level > 0 ? (
        <div aria-hidden className="liquid-fill pointer-events-none absolute inset-x-0 bottom-0" style={{ height: `${Math.round(level * 100)}%`, color }}>
          <svg className="liquid-wave" viewBox="0 0 120 8" preserveAspectRatio="none">
            <path d="M0 4 Q15 0 30 4 T60 4 T90 4 T120 4 V8 H0 Z" fill="currentColor" />
          </svg>
          <div className="h-full" style={{ backgroundColor: "currentColor", marginTop: -1 }} />
        </div>
      ) : null}
      <Icon aria-hidden className="relative h-4 w-4" style={{ color }} />
      <dt className="relative mt-1 text-xs text-foreground-secondary">{label}</dt>
      <dd className="relative mt-1 text-lg font-semibold tabular-nums text-foreground">{value}</dd>
    </div>
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
  const maxDays = Math.max(0, ...stats.filter(([label]) => STAT_STYLE[label]?.fill).map(([, v]) => Number(v) || 0));

  return (
    <SectionCard
      id="att-monthly"
      title="Monthly attendance summary"
      description="Employee-days across the period, as Payroll will read them."
      status={status}
      error={periods.status === "error" ? periods.error : summary.error}
      onRetry={periods.status === "error" ? periods.retry : summary.retry}
      empty={periodId === null ? { title: "No attendance period to summarise.", description: "Open a period for a company first." } : null}
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
              <StatTile key={label} label={label} value={value} level={STAT_STYLE[label]?.fill && maxDays > 0 ? Math.min(1, Math.max(0, (Number(value) || 0) / maxDays)) * 0.9 : 0} />
            ))}
          </dl>
        </>
      ) : null}
    </SectionCard>
  );
}
