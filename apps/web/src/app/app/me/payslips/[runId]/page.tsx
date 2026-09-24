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

/** Payroll Phase 5.4 — one of the signed-in employee's own payslips. */
export default function MyPayslipPage() {
  const params = useParams<{ runId: string }>();
  const [payslip, setPayslip] = useState<Payslip | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      setPayslip(await apiClient.get<Payslip>(`/me/payslips/${params.runId}`));
    } catch (err) {
      setError(describeApiError(err));
    }
  }, [params.runId]);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <div className="space-y-4">
      <Link href="/app/me/payslips" className="text-sm text-primary hover:underline print:hidden">
        ← All payslips
      </Link>
      {error ? <ErrorState message={error} onRetry={() => void load()} /> : null}
      {!payslip && !error ? <LoadingState label="Loading payslip…" /> : null}
      {payslip ? <PayslipView payslip={payslip} /> : null}
    </div>
  );
}
