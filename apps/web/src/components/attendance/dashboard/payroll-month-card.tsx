"use client";

import { useApiResource } from "@/hooks/use-api-resource";
import { Badge } from "@/components/ui/badge";
import { formatMinutes } from "@/lib/attendance/format";
import {
  approvedOvertimeMinutes,
  formatPayrollDays,
  monthSummaryPath,
  type MonthSummaryResponse,
} from "@/lib/attendance/month-summary";

/** The month as payroll will count it, from the backend. Shown beside the day counts, which are
 * whole days by status, so a half-day leave reads as half leave and half present here. */
export function PayrollMonthCard({ employeeId, month }: { employeeId: string; month: string }) {
  const { data, loading, error } = useApiResource<MonthSummaryResponse>(monthSummaryPath(month, [employeeId]));
  if (loading) return <p className="text-sm text-foreground-muted">Loading payroll days…</p>;
  if (error) return <p className="text-sm text-foreground-muted">Payroll days couldn&apos;t be loaded.</p>;
  const row = data?.summaries.find((s) => s.employee_id === employeeId);
  if (!row) return <p className="text-sm text-foreground-muted">No payroll days yet for this month.</p>;

  const items: Array<[string, string]> = [
    ["Paid days", formatPayrollDays(row.paid_days)],
    ["Loss of pay", formatPayrollDays(row.lop_days)],
    ["Leave", formatPayrollDays(row.leave_days)],
    ["Present", formatPayrollDays(row.present_days)],
    ["Half days", formatPayrollDays(row.half_days)],
    ["Holidays and weekly offs", formatPayrollDays(String(Number(row.holiday_days) + Number(row.weekly_off_days)))],
  ];
  const overtime = approvedOvertimeMinutes(row);
  return (
    <section aria-labelledby="payroll-month-heading" className="space-y-2">
      <div className="flex flex-wrap items-center gap-2">
        <h3 id="payroll-month-heading" className="text-sm font-semibold text-foreground">
          How payroll counts this month
        </h3>
        <Badge variant={row.frozen ? "success" : "secondary"}>
          {row.frozen ? "Final, month closed" : "So far, can change until the month closes"}
        </Badge>
      </div>
      <dl className="grid grid-cols-2 gap-3 sm:grid-cols-3 xl:grid-cols-6">
        {items.map(([label, value]) => (
          <div key={label} className="rounded-lg border border-border bg-surface px-3 py-2">
            <dt className="text-xs text-foreground-muted">{label}</dt>
            <dd className="text-lg font-semibold text-foreground">{value}</dd>
          </div>
        ))}
      </dl>
      {overtime > 0 ? (
        <p className="text-xs text-foreground-muted">Approved overtime: {formatMinutes(overtime)}</p>
      ) : null}
    </section>
  );
}
