"use client";

import { FileText } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { CompanyDate } from "@/components/common/company-date";
import { EmptyState } from "@/components/common/empty-state";
import { ErrorState } from "@/components/common/error-state";
import { LoadingState } from "@/components/common/loading-state";
import { PageHeader } from "@/components/common/page-header";
import {
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableHeader,
  TableRow,
  TableRowAction,
} from "@/components/ui/table";
import { apiClient } from "@/lib/api/client";
import { describeApiError } from "@/lib/api/errors";
import { formatInr, formatPayMonth, type PayslipSummary } from "@/lib/payroll/types";

/** Payroll Phase 5.4 — the signed-in employee's payslips from finalised pay runs
 * (`/v1/me/payslips`). */
export default function MyPayslipsPage() {
  const [payslips, setPayslips] = useState<PayslipSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      setPayslips(await apiClient.get<PayslipSummary[]>("/me/payslips"));
    } catch (err) {
      setError(describeApiError(err));
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <div className="space-y-6">
      <PageHeader title="My Payslips" description="Your payslips from finalised pay runs." />
      <TableContainer>
        {error ? (
          <div className="p-6">
            <ErrorState message={error} onRetry={() => void load()} />
          </div>
        ) : null}
        {!payslips && !error ? <LoadingState label="Loading payslips…" /> : null}
        {payslips && payslips.length === 0 ? (
          <div className="p-6">
            <EmptyState
              icon={FileText}
              title="No payslips yet."
              description="Payslips appear here automatically once a monthly pay run is finalised."
            />
          </div>
        ) : null}
        {payslips && payslips.length > 0 ? (
          <Table>
            <TableHeader>
              <TableRow className="hover:bg-transparent">
                <TableHead>Month</TableHead>
                <TableHead>Paid on</TableHead>
                <TableHead align="right">Net pay</TableHead>
                <TableHead align="right">Payslip</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {payslips.map((payslip) => (
                <TableRow key={payslip.pay_run_id}>
                  <TableCell className="font-medium text-foreground">
                    {formatPayMonth(payslip.month)}
                  </TableCell>
                  <TableCell className="tabular-nums text-foreground-secondary">
                    Paid on <CompanyDate value={payslip.pay_date} />
                  </TableCell>
                  <TableCell align="right" numeric className="font-semibold text-foreground">
                    {formatInr(payslip.net_minor)}
                  </TableCell>
                  <TableCell align="right">
                    <TableRowAction href={`/app/me/payslips/${payslip.pay_run_id}`}>View</TableRowAction>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        ) : null}
      </TableContainer>
    </div>
  );
}
