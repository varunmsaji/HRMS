"use client";

import Link from "next/link";

import { AttendancePeriodStatusBadge } from "@/components/attendance-period/attendance-period-status-badge";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import type { AttendancePeriod } from "@/lib/attendance-period/types";
import { formatShortDate, type AttentionItem } from "@/lib/attendance/dashboard";
import { periodProgress } from "@/lib/attendance/insights";
import { cn } from "@/lib/utils";

interface PayrollReadinessProps {
  period: AttendancePeriod;
  companyName: string;
  today: string;
  /** Items from Needs attention that must be cleared before payroll — critical and high only. */
  blockers: AttentionItem[];
  rangeLabel: string;
}

function countdown(daysLeft: number): { text: string; tone: "ok" | "soon" | "over" } {
  if (daysLeft < 0) return { text: `Ended ${-daysLeft} day${daysLeft === -1 ? "" : "s"} ago`, tone: "over" };
  if (daysLeft === 0) return { text: "Ends today", tone: "soon" };
  return { text: `${daysLeft} day${daysLeft === 1 ? "" : "s"} left`, tone: daysLeft <= 3 ? "soon" : "ok" };
}

/** Month-end at a glance: where the open period stands and what is still in the way of closing it. */
export function PayrollReadiness({ period, companyName, today, blockers, rangeLabel }: PayrollReadinessProps) {
  const progress = periodProgress(period, today);
  const clock = countdown(progress.daysLeft);
  const open = period.status === "OPEN";
  const total = blockers.reduce((acc, b) => acc + b.count, 0);
  const title = period.label ?? `${formatShortDate(period.period_start)} – ${formatShortDate(period.period_end)}`;

  return (
    <section aria-label="Payroll readiness" className="flex h-full flex-col gap-4 rounded-xl border border-border bg-surface p-5 shadow-elevation-1">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="text-2xs font-semibold uppercase tracking-wider text-foreground-muted">Payroll readiness</p>
          <p className="mt-1 truncate text-md font-semibold text-foreground">{title}</p>
          <p className="truncate text-xs text-foreground-muted">{companyName}</p>
        </div>
        <AttendancePeriodStatusBadge status={period.status} />
      </div>

      <div>
        <div className="flex items-baseline justify-between text-xs">
          <span
            className={cn(
              "font-medium",
              clock.tone === "over" && "text-danger",
              clock.tone === "soon" && "text-warning",
              clock.tone === "ok" && "text-foreground-secondary",
            )}
          >
            {clock.text}
          </span>
          <span className="tabular-nums text-foreground-muted">
            Day {progress.elapsedDays} of {progress.totalDays}
          </span>
        </div>
        <div
          role="progressbar"
          aria-label="Period progress"
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={Math.round(progress.percent)}
          className="mt-1.5 h-2 overflow-hidden rounded-full bg-muted"
        >
          <div
            className={cn("h-full animate-grow-x rounded-full", clock.tone === "over" ? "bg-danger" : clock.tone === "soon" ? "bg-warning" : "bg-primary")}
            style={{ width: `${progress.percent}%` }}
          />
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-1.5">
        {open && period.last_validation_status === "BLOCKED" ? <Badge variant="danger">Validation blocked</Badge> : null}
        {open && period.last_validation_status === "READY" ? <Badge variant="success">Ready to finalize</Badge> : null}
        {open && period.last_validation_status === null ? <Badge variant="outline">Not validated yet</Badge> : null}
        {period.reopened_at ? <Badge variant="warning">Reopened</Badge> : null}
      </div>

      <div className="flex-1">
        <p className="text-xs font-medium text-foreground-secondary">Still to clear before close</p>
        {blockers.length === 0 ? (
          <p className="mt-1 text-sm text-foreground-secondary">Nothing urgent in {rangeLabel}.</p>
        ) : (
          <ul className="mt-1.5 space-y-1">
            {blockers.slice(0, 4).map((item) => (
              <li key={item.key} className="flex items-center justify-between gap-2 text-sm">
                <span className="truncate text-foreground">{item.label}</span>
                <span className="tabular-nums font-medium text-foreground">{item.count}</span>
              </li>
            ))}
            {blockers.length > 4 ? (
              <li className="text-xs text-foreground-muted">
                +{blockers.length - 4} more · {total} items in total
              </li>
            ) : null}
          </ul>
        )}
        <p className="mt-2 text-[11px] text-foreground-muted">Counts cover {rangeLabel}, not the whole period.</p>
      </div>

      <Button asChild size="sm" variant="outline" className="self-start">
        <Link href={`/app/attendance-periods/${period.id}`}>Open period →</Link>
      </Button>
    </section>
  );
}
