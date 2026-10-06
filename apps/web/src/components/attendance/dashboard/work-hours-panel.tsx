import { ColumnChart } from "@/components/attendance/dashboard/charts";
import type { DailyHours, WorkHoursSummary } from "@/lib/attendance/dashboard";
import { formatMinutes } from "@/lib/attendance/format";

interface WorkHoursPanelProps {
  summary: WorkHoursSummary;
  daily: DailyHours[];
}

function Stat({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="rounded-md border border-border p-3">
      <p className="text-xs text-foreground-muted">{label}</p>
      <p className="mt-1 text-lg font-semibold tabular-nums text-foreground">{value}</p>
      {hint ? <p className="mt-0.5 text-xs text-foreground-secondary">{hint}</p> : null}
    </div>
  );
}

const hoursFmt = (minutes: number) => `${(minutes / 60).toFixed(1)}h`;

/** Hours as the backend calculated them (`worked_minutes`, `scheduled_minutes`, `ot_minutes_*`).
 * Expected vs actual compares like for like: days the employee attended, scheduled vs worked. */
export function WorkHoursPanel({ summary, daily }: WorkHoursPanelProps) {
  const deviation = summary.deviationMinutes;
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-3">
        <Stat label="Total worked" value={formatMinutes(summary.totalMinutes)} hint={`${summary.checkedInDays} checked-in day${summary.checkedInDays === 1 ? "" : "s"}`} />
        <Stat label="Average per day" value={formatMinutes(summary.avgMinutes)} hint="Per checked-in day" />
        <Stat label="Expected" value={formatMinutes(summary.expectedMinutes)} hint="Scheduled, days attended" />
        <Stat
          label="Deviation"
          value={`${deviation > 0 ? "+" : ""}${formatMinutes(deviation)}`}
          hint={deviation < 0 ? "Below schedule" : deviation > 0 ? "Above schedule" : "On schedule"}
        />
        <Stat label="Under-time" value={formatMinutes(summary.underTimeMinutes)} hint="Complete days short of schedule" />
        <Stat
          label="Overtime"
          value={formatMinutes(summary.otDetectedMinutes)}
          hint={`${formatMinutes(summary.otApprovedMinutes)} approved`}
        />
      </div>
      <div>
        <h3 className="mb-2 text-sm font-medium text-foreground">Expected vs actual hours</h3>
        <ColumnChart
          ariaLabel="Worked hours against scheduled hours per day"
          valueLabel="Worked"
          referenceLabel="Scheduled"
          format={hoursFmt}
          data={daily.map((d) => ({
            key: d.date,
            label: d.label,
            value: d.workedMinutes,
            reference: d.scheduledMinutes,
          }))}
        />
      </div>
    </div>
  );
}
