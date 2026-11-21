import { AlertTriangle } from "lucide-react";

import { formatMinutes } from "@/lib/attendance/format";
import type { AttendanceDayExplanation } from "@/lib/attendance/types";

/** "Why this result": the API's own explanation of the day, shown as written. Nothing here is
 * worked out on the page, so every screen that shows it says the same thing. */
export function DayExplanationCard({ explanation }: { explanation: AttendanceDayExplanation }) {
  const { reason, facts, pay, overtime, action } = explanation;
  return (
    <section aria-label="Why this result" className="rounded-2xl border border-border bg-surface p-6 shadow-elevation-1">
      <h2 className="text-base font-semibold text-foreground">Why this result</h2>
      <p className="mt-2 text-sm text-foreground">{reason}</p>

      {facts.length > 0 ? (
        <dl className="mt-4 grid grid-cols-2 gap-x-4 gap-y-3 sm:grid-cols-3">
          {facts.map((f) => (
            <div key={f.key}>
              <dt className="text-xs text-foreground-muted">{f.label}</dt>
              <dd className="text-sm font-medium tabular-nums text-foreground">{f.value}</dd>
            </div>
          ))}
        </dl>
      ) : null}

      <p className="mt-4 text-sm text-foreground-secondary">
        <span className="font-medium text-foreground">Pay: </span>
        {pay.label}
      </p>
      {overtime ? (
        <p className="mt-1 text-sm text-foreground-secondary">
          <span className="font-medium text-foreground">Overtime: </span>
          {formatMinutes(overtime.found_min)} found, {formatMinutes(overtime.approved_min)} approved
          {overtime.pending_min > 0 ? `, ${formatMinutes(overtime.pending_min)} waiting for approval` : ""}
        </p>
      ) : null}

      {action ? (
        <div role="note" className="mt-4 flex items-start gap-2 rounded-lg border border-warning-border bg-warning-subtle p-3 text-sm text-foreground">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
          <p>
            {action.deadline ? `Fix by ${action.deadline}. ` : ""}
            {action.consequence}.
          </p>
        </div>
      ) : null}
    </section>
  );
}
