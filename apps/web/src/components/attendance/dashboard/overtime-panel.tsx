import Link from "next/link";

import { ColumnChart } from "@/components/attendance/dashboard/charts";
import { Button } from "@/components/ui/button";
import type { OvertimeSummary } from "@/lib/attendance/dashboard";
import { formatMinutes } from "@/lib/attendance/format";
import { OVERTIME_DAY_CLASS_LABELS, type OvertimeDayClass } from "@/lib/overtime/types";

function dayClassLabel(dayClass: string): string {
  return dayClass in OVERTIME_DAY_CLASS_LABELS
    ? OVERTIME_DAY_CLASS_LABELS[dayClass as OvertimeDayClass]
    : "Unclassified";
}

/** Overtime as the backend detected and approved it (`OvertimeRecord`) — no OT arithmetic here
 * beyond summing the records' own minutes. */
export function OvertimePanel({ summary }: { summary: OvertimeSummary }) {
  const maxClass = Math.max(1, ...summary.byDayClass.map((c) => c.minutes));
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-3">
        {[
          ["Total detected", formatMinutes(summary.totalDetectedMinutes), `${formatMinutes(summary.totalApprovedMinutes)} approved`],
          ["Employees with OT", String(summary.employees), summary.avgDetectedPerEmployee !== null ? `${formatMinutes(summary.avgDetectedPerEmployee)} average each` : ""],
          ["Pending approval", String(summary.pendingCount), summary.pendingCount > 0 ? `${formatMinutes(summary.pendingMinutes)} waiting` : "None waiting"],
          ["Approved", String(summary.approvedCount), "Incl. auto-approved"],
          ["Rejected", String(summary.rejectedCount), ""],
        ].map(([label, value, hint]) => (
          <div key={label} className="rounded-md border border-border p-3">
            <p className="text-xs text-foreground-muted">{label}</p>
            <p className="mt-1 text-lg font-semibold tabular-nums text-foreground">{value}</p>
            {hint ? <p className="mt-0.5 text-xs text-foreground-secondary">{hint}</p> : null}
          </div>
        ))}
      </div>
      {summary.byDayClass.length > 0 ? (
        <div>
          <h3 className="mb-2 text-sm font-medium text-foreground">By day class</h3>
          <ul className="space-y-1.5">
            {summary.byDayClass.map((c) => (
              <li key={c.dayClass} className="flex items-center gap-3 text-sm">
                <span className="w-24 shrink-0 text-foreground-secondary">{dayClassLabel(c.dayClass)}</span>
                <span className="h-2 flex-1 overflow-hidden rounded-full bg-muted">
                  <span className="block h-full rounded-full bg-info" style={{ width: `${(c.minutes / maxClass) * 100}%` }} />
                </span>
                <span className="w-16 text-right tabular-nums text-foreground">{formatMinutes(c.minutes)}</span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
      <div>
        <h3 className="mb-2 text-sm font-medium text-foreground">Overtime trend</h3>
        <ColumnChart
          ariaLabel="Detected overtime hours per day"
          valueLabel="Overtime"
          format={(m) => `${(m / 60).toFixed(1)}h`}
          data={summary.trend.map((t) => ({ key: t.date, label: t.label, value: t.minutes }))}
        />
      </div>
      <Button asChild size="sm" variant="outline">
        <Link href="/app/overtime">Open overtime records →</Link>
      </Button>
    </div>
  );
}
