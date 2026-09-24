"use client";

import { FileText } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { EmptyState } from "@/components/common/empty-state";
import { ErrorState } from "@/components/common/error-state";
import { LoadingState } from "@/components/common/loading-state";
import { PageHeader } from "@/components/common/page-header";
import { Card, CardContent } from "@/components/ui/card";
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
      <Card>
        <CardContent className="pt-6">
          {error ? <ErrorState message={error} onRetry={() => void load()} /> : null}
          {!payslips && !error ? <LoadingState label="Loading payslips…" /> : null}
          {payslips && payslips.length === 0 ? (
            <EmptyState icon={FileText} title="No payslips yet." />
          ) : null}
          {payslips && payslips.length > 0 ? (
            <ul className="divide-y divide-border rounded-md border border-border">
              {payslips.map((payslip) => (
                <li key={payslip.pay_run_id} className="flex items-center justify-between gap-3 px-3 py-2 text-sm">
                  <div>
                    <div className="font-medium text-foreground">{formatPayMonth(payslip.month)}</div>
                    <div className="text-xs text-foreground-muted">Paid on {payslip.pay_date}</div>
                  </div>
                  <div className="flex items-center gap-4">
                    <span className="tabular-nums">{formatInr(payslip.net_minor)}</span>
                    <Link
                      href={`/app/me/payslips/${payslip.pay_run_id}`}
                      className="font-medium text-primary hover:underline"
                    >
                      View
                    </Link>
                  </div>
                </li>
              ))}
            </ul>
          ) : null}
        </CardContent>
      </Card>
    </div>
  );
}
