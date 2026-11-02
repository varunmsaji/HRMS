"use client";

import Link from "next/link";

import { Button } from "@/components/ui/button";
import { employeeName, formatPct, type EmployeeLite } from "@/lib/attendance/dashboard";
import {
  worstWeekday,
  type FrequentLate,
  type PunctualitySummary,
  type WeekdayStat,
} from "@/lib/attendance/insights";
import { cn } from "@/lib/utils";

function Stat({ label, value, hint, tone }: { label: string; value: string; hint?: string; tone?: "good" | "warn" }) {
  return (
    <div className="rounded-lg border border-border bg-surface-secondary/40 p-3">
      <p className="text-xs text-foreground-muted">{label}</p>
      <p
        className={cn(
          "mt-1 text-xl font-semibold tabular-nums",
          tone === "good" && "text-success",
          tone === "warn" && "text-warning",
          !tone && "text-foreground",
        )}
      >
        {value}
      </p>
      {hint ? <p className="mt-0.5 text-[11px] text-foreground-secondary">{hint}</p> : null}
    </div>
  );
}

interface PunctualityPanelProps {
  summary: PunctualitySummary;
  frequent: FrequentLate[];
  employeesById: Map<string, EmployeeLite>;
  onViewLate: () => void;
}

/** How punctual the workforce is over the selected range: the on-time rate, how late "late"
 * usually is, and who is late again and again. */
export function PunctualityPanel({ summary, frequent, employeesById, onViewLate }: PunctualityPanelProps) {
  if (summary.checkedIn === 0) {
    return (
      <p className="rounded-md border border-dashed border-border px-4 py-8 text-center text-sm text-foreground-secondary">
        Nobody has checked in during this range, so there is no punctuality to report.
      </p>
    );
  }
  const maxBand = Math.max(1, ...summary.bands.map((b) => b.count));
  return (
    <div className="space-y-5">
      <div className="grid grid-cols-3 gap-3">
        <Stat
          label="On time"
          value={formatPct(summary.onTimeRate)}
          hint={`${summary.onTime} of ${summary.checkedIn} check-ins`}
          tone={summary.late === 0 ? "good" : undefined}
        />
        <Stat label="Late arrivals" value={String(summary.late)} hint={formatPct(summary.lateRate) + " of check-ins"} tone={summary.late > 0 ? "warn" : undefined} />
        <Stat
          label="Average lateness"
          value={summary.avgLateMinutes === null ? "—" : `${Math.round(summary.avgLateMinutes)} min`}
          hint="On late days only"
        />
      </div>

      {summary.late > 0 ? (
        <div>
          <p className="mb-2 text-xs font-medium text-foreground-secondary">How late</p>
          <ul className="space-y-1.5">
            {summary.bands.map((band, bandIndex) => (
              <li key={band.key} className="grid grid-cols-[6.5rem_minmax(0,1fr)_2rem] items-center gap-3 text-xs">
                <span className="text-foreground-secondary">{band.label}</span>
                <span className="h-2 overflow-hidden rounded-full bg-muted" aria-hidden="true">
                  <span
                    className="block h-full origin-left animate-grow-x rounded-full bg-warning"
                    style={{ width: `${(band.count / maxBand) * 100}%`, animationDelay: `${bandIndex * 70}ms` }}
                  />
                </span>
                <span className="text-right tabular-nums font-medium text-foreground">{band.count}</span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      <div>
        <div className="mb-2 flex items-center justify-between gap-2">
          <p className="text-xs font-medium text-foreground-secondary">Late more than once</p>
          {summary.late > 0 ? (
            <Button type="button" size="sm" variant="ghost" onClick={onViewLate}>
              View all late arrivals →
            </Button>
          ) : null}
        </div>
        {frequent.length === 0 ? (
          <p className="text-sm text-foreground-secondary">
            {summary.late === 0 ? "Everyone who checked in was on time." : "Nobody has been late more than once in this range."}
          </p>
        ) : (
          <ul className="divide-y divide-border rounded-lg border border-border">
            {frequent.map((entry, index) => (
              <li key={entry.employeeId} className="flex items-center gap-3 px-3 py-2 text-sm">
                <span className="w-4 text-xs tabular-nums text-foreground-muted">{index + 1}</span>
                <Link
                  href={`/app/attendance/employee/${entry.employeeId}`}
                  className="min-w-0 flex-1 truncate font-medium text-foreground hover:underline"
                >
                  {employeeName(employeesById.get(entry.employeeId), entry.employeeId)}
                </Link>
                <span className="tabular-nums text-foreground-secondary">{entry.lateDays} days</span>
                <span className="w-16 text-right text-xs tabular-nums text-foreground-muted">{entry.totalLateMinutes} min</span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

/** Absence rate for each weekday, so a "Monday problem" or a long-weekend pattern is visible. */
export function WeekdayPanel({ stats }: { stats: WeekdayStat[] }) {
  const worst = worstWeekday(stats);
  const max = Math.max(1, ...stats.map((s) => s.rate ?? 0));
  if (stats.every((s) => s.expected === 0)) {
    return (
      <p className="rounded-md border border-dashed border-border px-4 py-8 text-center text-sm text-foreground-secondary">
        No expected working days in this range.
      </p>
    );
  }
  return (
    <div className="space-y-4">
      <p className="text-sm text-foreground-secondary">
        {worst
          ? `${worst.label}s have the highest absence — ${formatPct(worst.rate)} of expected days.`
          : "No weekday stands out: absence is spread evenly, or there is none in this range."}
      </p>
      <div role="img" aria-label="Absence rate by weekday" className="flex h-36 items-end gap-2">
        {stats.map((stat) => {
          const isWorst = worst?.index === stat.index;
          return (
            <div
              key={stat.index}
              className="flex h-full min-w-0 flex-1 flex-col items-center justify-end gap-1"
              title={stat.rate === null ? `${stat.label}: no expected days` : `${stat.label}: ${formatPct(stat.rate)} absent (${stat.absent} of ${stat.expected})`}
            >
              <span className={cn("text-[11px] tabular-nums", isWorst ? "font-semibold text-danger" : "text-foreground-muted")}>
                {stat.rate === null ? "—" : `${Math.round(stat.rate)}%`}
              </span>
              <div className="flex w-full flex-1 items-end">
                <div
                  className={cn(
                    "w-full animate-grow-y rounded-t-md",
                    stat.rate === null ? "bg-muted" : isWorst ? "bg-danger" : "bg-primary/70",
                  )}
                  style={{
                    height: stat.rate === null ? "4px" : `${Math.max(4, ((stat.rate ?? 0) / max) * 100)}%`,
                    animationDelay: `${stat.index * 50}ms`,
                  }}
                />
              </div>
              <span className={cn("text-xs", isWorst ? "font-semibold text-foreground" : "text-foreground-secondary")}>{stat.label}</span>
            </div>
          );
        })}
      </div>
      <table className="sr-only">
        <caption>Absence rate by weekday</caption>
        <tbody>
          {stats.map((stat) => (
            <tr key={stat.index}>
              <th scope="row">{stat.label}</th>
              <td>{stat.rate === null ? "No expected days" : `${formatPct(stat.rate)} (${stat.absent} of ${stat.expected})`}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
