"use client";

import { Scale } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { EmptyState } from "@/components/common/empty-state";
import { ErrorState } from "@/components/common/error-state";
import { LoadingState } from "@/components/common/loading-state";
import { PageHeader } from "@/components/common/page-header";
import { useToast } from "@/components/common/toast";
import { StatutoryRateDialog } from "@/components/payroll/statutory-rate-dialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { apiClient } from "@/lib/api/client";
import { ApiError, describeApiError } from "@/lib/api/errors";
import { usePermissions } from "@/lib/auth/use-permissions";
import {
  STATUTORY_SCHEME_LABELS,
  summariseStatutoryRate,
  type StatutoryRate,
} from "@/lib/payroll/types";

/** Payroll Phase 5.3 — the statutory rate master (`/v1/payroll/statutory-rates`, FR-PAY-005).
 * Every rate is data, effective-dated, and must be verified (compliance sign-off) before a pay
 * run that uses it can be approved. Defaults are pre-filled unverified. */
export default function StatutoryRatesPage() {
  const { toast } = useToast();
  const { can } = usePermissions();
  const canManage = can("PAYROLL.STATUTORY_MANAGE");

  const [rates, setRates] = useState<StatutoryRate[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<ApiError | null>(null);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editing, setEditing] = useState<StatutoryRate | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setRates(await apiClient.get<StatutoryRate[]>("/payroll/statutory-rates"));
    } catch (err) {
      setRates(null);
      setError(
        err instanceof ApiError
          ? err
          : new ApiError({ status: 0, code: "UNKNOWN_ERROR", message: "Something went wrong." }),
      );
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function verify(rate: StatutoryRate) {
    setBusyId(rate.id);
    try {
      await apiClient.post<StatutoryRate>(`/payroll/statutory-rates/${rate.id}/verify`, undefined, {
        ifMatch: String(rate.version),
      });
      toast({ title: "Rate verified", variant: "success" });
      await load();
    } catch (err) {
      toast({ title: "Could not verify", description: describeApiError(err), variant: "danger" });
    } finally {
      setBusyId(null);
    }
  }

  const unverifiedCurrent = rates?.filter((r) => r.effective_to === null && !r.verified) ?? [];

  return (
    <div className="space-y-6">
      <PageHeader
        title="Statutory Rates"
        description="PF, ESI, professional tax and labour welfare fund rates used by pay runs."
        actions={
          canManage ? (
            <Button
              type="button"
              onClick={() => {
                setEditing(null);
                setDialogOpen(true);
              }}
            >
              New rate
            </Button>
          ) : undefined
        }
      />

      {unverifiedCurrent.length > 0 ? (
        <div role="status" className="rounded-md border border-warning bg-warning-subtle p-3 text-sm text-foreground">
          {unverifiedCurrent.length} current rate(s) are not verified. Check each against the
          latest notification and verify it — a pay run that uses an unverified rate cannot be
          approved.
        </div>
      ) : null}

      <Card>
        <CardContent className="pt-6">
          {loading ? <LoadingState label="Loading statutory rates…" /> : null}
          {error && !loading ? (
            <ErrorState
              message={
                error.status === 403
                  ? "You do not have permission to manage statutory rates."
                  : error.message
              }
              onRetry={() => void load()}
            />
          ) : null}
          {!loading && !error && rates && rates.length === 0 ? (
            <EmptyState icon={Scale} title="No statutory rates yet." />
          ) : null}
          {!loading && !error && rates && rates.length > 0 ? (
            <div className="overflow-x-auto rounded-md border border-border">
              <table className="w-full text-sm">
                <thead className="bg-surface-secondary text-xs uppercase tracking-wide text-foreground-muted">
                  <tr>
                    <th className="px-3 py-2 text-left font-medium">Scheme</th>
                    <th className="px-3 py-2 text-left font-medium">In force</th>
                    <th className="px-3 py-2 text-left font-medium">Figures</th>
                    <th className="px-3 py-2 text-left font-medium">Status</th>
                    {canManage ? <th className="px-3 py-2 text-right font-medium">Action</th> : null}
                  </tr>
                </thead>
                <tbody className="divide-y divide-border">
                  {rates.map((rate) => (
                    <tr key={rate.id}>
                      <td className="px-3 py-2">
                        <div className="font-medium text-foreground">
                          {STATUTORY_SCHEME_LABELS[rate.scheme]}
                          {rate.state_code ? ` — ${rate.state_code}` : ""}
                        </div>
                        {rate.notes ? (
                          <div className="max-w-md text-xs text-foreground-muted">{rate.notes}</div>
                        ) : null}
                      </td>
                      <td className="px-3 py-2 text-foreground-secondary">
                        {rate.effective_from} → {rate.effective_to ?? "now"}
                      </td>
                      <td className="px-3 py-2 text-foreground-secondary">
                        {summariseStatutoryRate(rate)}
                      </td>
                      <td className="px-3 py-2">
                        <Badge variant={rate.verified ? "success" : "warning"}>
                          {rate.verified ? "Verified" : "Not verified"}
                        </Badge>
                      </td>
                      {canManage ? (
                        <td className="px-3 py-2 text-right">
                          <div className="flex justify-end gap-2">
                            <Button
                              type="button"
                              variant="outline"
                              size="sm"
                              onClick={() => {
                                setEditing(rate);
                                setDialogOpen(true);
                              }}
                            >
                              Edit
                            </Button>
                            {!rate.verified ? (
                              <Button
                                type="button"
                                size="sm"
                                disabled={busyId === rate.id}
                                onClick={() => void verify(rate)}
                              >
                                Verify
                              </Button>
                            ) : null}
                          </div>
                        </td>
                      ) : null}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : null}
        </CardContent>
      </Card>

      <StatutoryRateDialog
        open={dialogOpen}
        rate={editing}
        onOpenChange={setDialogOpen}
        onSaved={() => void load()}
      />
    </div>
  );
}
