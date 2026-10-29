"use client";

import { useEffect, useState } from "react";

import { LoadingState } from "@/components/common/loading-state";
import { Badge } from "@/components/ui/badge";
import { HorizontalScroll } from "@/components/ui/table";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { apiClient } from "@/lib/api/client";
import { describeApiError } from "@/lib/api/errors";
import { formatInr, type PayRunEmployeeDetail, type PayRunLine } from "@/lib/payroll/types";

const SECTIONS: { type: PayRunLine["line_type"]; label: string }[] = [
  { type: "EARNING", label: "Earnings" },
  { type: "DEDUCTION", label: "Deductions" },
  { type: "ROUNDING", label: "Rounding" },
  { type: "EMPLOYER_CONTRIBUTION", label: "Employer contributions (not paid to the employee)" },
];

/** One employee's pay in a run: every line with how it was reached (FR-PAY-024). */
export function PayRunEmployeeDialog({
  runId,
  employeeId,
  onOpenChange,
}: {
  runId: string;
  employeeId: string | null;
  onOpenChange: (open: boolean) => void;
}) {
  const [detail, setDetail] = useState<PayRunEmployeeDetail | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!employeeId) return;
    setDetail(null);
    setError(null);
    apiClient
      .get<PayRunEmployeeDetail>(`/payroll/pay-runs/${runId}/employees/${employeeId}`)
      .then(setDetail)
      .catch((err: unknown) => setError(describeApiError(err)));
  }, [runId, employeeId]);

  return (
    <Dialog open={employeeId !== null} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>{detail?.employee_name ?? "Employee pay"}</DialogTitle>
          <DialogDescription>
            {detail
              ? `${detail.employee_code ?? ""} · paid days ${detail.paid_days ?? "—"} · LOP ${
                  detail.lop_days ?? "—"
                }`
              : "How each amount was calculated."}
          </DialogDescription>
        </DialogHeader>
        {!detail && !error ? <LoadingState label="Loading pay…" /> : null}
        {error ? <p className="text-sm text-danger">{error}</p> : null}
        {detail ? (
          <div className="max-h-[65vh] space-y-4 overflow-y-auto">
            {detail.issues.length > 0 ? (
              <ul className="space-y-1">
                {detail.issues.map((issue) => (
                  <li key={`${issue.code}-${issue.message}`} className="flex gap-2 text-sm">
                    <Badge variant={issue.severity === "ERROR" ? "danger" : "warning"}>
                      {issue.severity === "ERROR" ? "Error" : "Warning"}
                    </Badge>
                    <span className="text-foreground">{issue.message}</span>
                  </li>
                ))}
              </ul>
            ) : null}
            {detail.lines.length === 0 ? (
              <p className="text-sm text-foreground-muted">Not computed yet.</p>
            ) : (
              <HorizontalScroll className="rounded-md border border-border">
                <table className="w-full text-sm">
                  <thead className="bg-surface-secondary text-xs uppercase tracking-wide text-foreground-muted">
                    <tr>
                      <th className="px-3 py-2 text-left font-medium">Component</th>
                      <th className="px-3 py-2 text-right font-medium">Full month</th>
                      <th className="px-3 py-2 text-right font-medium">This month</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-border">
                    {SECTIONS.map(({ type, label }) => {
                      const lines = detail.lines.filter((line) => line.line_type === type);
                      if (lines.length === 0) return null;
                      return [
                        <tr key={type} className="bg-surface-secondary">
                          <td colSpan={3} className="px-3 py-1.5 text-xs font-medium text-foreground-muted">
                            {label}
                          </td>
                        </tr>,
                        ...lines.map((line) => (
                          <tr key={line.component_code}>
                            <td className="px-3 py-2">
                              <div className="text-foreground">{line.component_name}</div>
                              {line.trace.formula ? (
                                <div className="text-xs text-foreground-muted">
                                  {line.trace.formula}
                                </div>
                              ) : null}
                            </td>
                            <td className="px-3 py-2 text-right tabular-nums text-foreground-secondary">
                              {line.full_monthly_minor !== null
                                ? formatInr(line.full_monthly_minor)
                                : "—"}
                            </td>
                            <td className="px-3 py-2 text-right tabular-nums">
                              {formatInr(line.amount_minor)}
                            </td>
                          </tr>
                        )),
                      ];
                    })}
                    <tr className="bg-surface-secondary font-medium">
                      <td className="px-3 py-2 text-foreground">Net pay</td>
                      <td />
                      <td className="px-3 py-2 text-right tabular-nums">
                        {formatInr(detail.net_minor)}
                      </td>
                    </tr>
                  </tbody>
                </table>
              </HorizontalScroll>
            )}
          </div>
        ) : null}
      </DialogContent>
    </Dialog>
  );
}
