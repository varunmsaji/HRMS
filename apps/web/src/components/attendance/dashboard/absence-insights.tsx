import Link from "next/link";

import { Button } from "@/components/ui/button";
import {
  REPEAT_ABSENCE_THRESHOLD,
  employeeName,
  type EmployeeLite,
  type KpiSet,
  type RepeatAbsence,
} from "@/lib/attendance/dashboard";

interface AbsenceInsightsProps {
  kpi: KpiSet;
  focusLabel: string;
  rangeAbsentDays: number;
  rangeLeaveDays: number;
  repeat: RepeatAbsence[];
  employeesById: Map<string, EmployeeLite>;
  onDrillEmployee: (employeeId: string) => void;
}

/** Operational absence picture only — leave balances, policies and approvals stay in Leave. */
export function AbsenceInsights({ kpi, focusLabel, rangeAbsentDays, rangeLeaveDays, repeat, employeesById, onDrillEmployee }: AbsenceInsightsProps) {
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3">
        <div className="rounded-md border border-border p-3">
          <p className="text-xs text-foreground-muted">Absent on {focusLabel}</p>
          <p className="mt-1 text-lg font-semibold tabular-nums">{kpi.absent}</p>
        </div>
        <div className="rounded-md border border-border p-3">
          <p className="text-xs text-foreground-muted">On leave on {focusLabel}</p>
          <p className="mt-1 text-lg font-semibold tabular-nums">{kpi.leave}</p>
        </div>
        <div className="rounded-md border border-border p-3">
          <p className="text-xs text-foreground-muted">Absent days in range</p>
          <p className="mt-1 text-lg font-semibold tabular-nums">{rangeAbsentDays}</p>
        </div>
        <div className="rounded-md border border-border p-3">
          <p className="text-xs text-foreground-muted">Leave days in range</p>
          <p className="mt-1 text-lg font-semibold tabular-nums">{rangeLeaveDays}</p>
        </div>
      </div>
      <div>
        <h3 className="mb-2 text-sm font-medium text-foreground">
          Repeat absence ({REPEAT_ABSENCE_THRESHOLD}+ absent days in range)
        </h3>
        {repeat.length === 0 ? (
          <p className="text-sm text-foreground-secondary">No employee reaches {REPEAT_ABSENCE_THRESHOLD} absent days in this range.</p>
        ) : (
          <ul className="divide-y divide-border rounded-md border border-border">
            {repeat.slice(0, 5).map((r) => (
              <li key={r.employeeId} className="flex items-center justify-between gap-2 px-3 py-2 text-sm">
                <button type="button" className="truncate text-left font-medium text-foreground hover:underline" onClick={() => onDrillEmployee(r.employeeId)}>
                  {employeeName(employeesById.get(r.employeeId), r.employeeId)}
                </button>
                <span className="shrink-0 text-xs text-foreground-secondary">
                  {r.absentDays} absent · {r.leaveDays} leave
                </span>
              </li>
            ))}
          </ul>
        )}
      </div>
      <Button asChild size="sm" variant="outline">
        <Link href="/app/leave-applications">Open Leave →</Link>
      </Button>
    </div>
  );
}
