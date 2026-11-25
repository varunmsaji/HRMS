"use client";

import Link from "next/link";

import { Badge } from "@/components/ui/badge";
import { employeeName, formatShortDate, type EmployeeLite } from "@/lib/attendance/dashboard";
import { PATTERN_KIND_LABELS, describePattern, type PatternAlerts } from "@/lib/attendance/patterns";

interface PatternAlertsPanelProps {
  data: PatternAlerts;
  employeesById: Map<string, EmployeeLite>;
}

/** People whose attendance shows a repeating pattern. An alert is a prompt to look, not a finding
 * about the person: each one names the days behind it and opens the person's own month. */
export function PatternAlertsPanel({ data, employeesById }: PatternAlertsPanelProps) {
  return (
    <ul className="divide-y divide-border rounded-lg border border-border">
      {data.alerts.map((alert) => {
        const name = employeeName(employeesById.get(alert.employee_id), alert.employee_id);
        return (
          <li key={`${alert.employee_id}-${alert.kind}-${alert.weekday ?? ""}`} className="flex flex-wrap items-center gap-x-3 gap-y-1 px-3 py-2 text-sm">
            <Link href={`/app/attendance/employee/${alert.employee_id}`} className="min-w-0 font-medium text-foreground hover:underline">
              {name}
            </Link>
            <Badge variant="warning">{PATTERN_KIND_LABELS[alert.kind]}</Badge>
            <span className="text-foreground-secondary">{describePattern(alert, data.thresholds)}</span>
            <span className="basis-full text-xs text-foreground-muted">
              {alert.dates.map((d) => formatShortDate(d)).join(", ")}
              {alert.count > alert.dates.length ? ` and ${alert.count - alert.dates.length} earlier` : ""}
            </span>
          </li>
        );
      })}
    </ul>
  );
}
