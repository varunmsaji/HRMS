"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { ErrorState } from "@/components/common/error-state";
import { LoadingState } from "@/components/common/loading-state";
import { PayslipView } from "@/components/payroll/payslip-view";
import { apiClient } from "@/lib/api/client";
import { describeApiError } from "@/lib/api/errors";
import type { Payslip } from "@/lib/payroll/types";

/** Payroll Phase 5.4 — HR view of one employee's payslip in a pay run (a preview until the run
 * is finalised). */
export default function PayRunPayslipPage() {
  const params = useParams<{ id: string; employeeId: string }>();
  const [payslip, setPayslip] = useState<Payslip | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      setPayslip(
        await apiClient.get<Payslip>(
          `/payroll/pay-runs/${params.id}/employees/${params.employeeId}/payslip`,
        ),
      );
    } catch (err) {
      setError(describeApiError(err));
    }
  }, [params.id, params.employeeId]);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <div className="space-y-4">
      <Link
        href={`/app/payroll/pay-runs/${params.id}`}
        className="text-sm text-primary hover:underline print:hidden"
      >
        ← Back to pay run
      </Link>
      {error ? <ErrorState message={error} onRetry={() => void load()} /> : null}
      {!payslip && !error ? <LoadingState label="Loading payslip…" /> : null}
      {payslip ? <PayslipView payslip={payslip} /> : null}
    </div>
  );
}
