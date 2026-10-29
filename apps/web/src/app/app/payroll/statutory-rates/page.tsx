"use client";

import { Plus, Scale } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { CompanyDate } from "@/components/common/company-date";
import { EmptyState } from "@/components/common/empty-state";
import { ErrorState } from "@/components/common/error-state";
import { LoadingState } from "@/components/common/loading-state";
import { PageHeader } from "@/components/common/page-header";
import { useToast } from "@/components/common/toast";
import { StatutoryRateDialog } from "@/components/payroll/statutory-rate-dialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
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
        backHref="/app/settings"
        backLabel="Settings"
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
              <Plus className="h-4 w-4" aria-hidden="true" />
              New rate
            </Button>
          ) : undefined
        }
      />

      {unverifiedCurrent.length > 0 ? (
        <div
          role="status"
          className="rounded-lg border border-warning-border bg-warning-subtle px-4 py-3 text-sm text-foreground"
        >
          {unverifiedCurrent.length} current rate(s) are not verified. Check each against the
          latest notification and verify it — a pay run that uses an unverified rate cannot be
          approved.
        </div>
      ) : null}

      <TableContainer>
        {loading ? <LoadingState label="Loading statutory rates…" /> : null}
        {error && !loading ? (
          <div className="p-6">
            <ErrorState
              message={
                error.status === 403
                  ? "You do not have permission to manage statutory rates."
                  : error.message
              }
              onRetry={() => void load()}
            />
          </div>
        ) : null}
        {!loading && !error && rates && rates.length === 0 ? (
          <div className="p-6">
            <EmptyState icon={Scale} title="No statutory rates yet." />
          </div>
        ) : null}
        {!loading && !error && rates && rates.length > 0 ? (
          <Table>
            <TableHeader>
              <TableRow className="hover:bg-transparent">
                <TableHead>Scheme</TableHead>
                <TableHead>In force</TableHead>
                <TableHead>Figures</TableHead>
                <TableHead>Status</TableHead>
                {canManage ? <TableHead align="right">Action</TableHead> : null}
              </TableRow>
            </TableHeader>
            <TableBody>
              {rates.map((rate) => (
                <TableRow key={rate.id}>
                  <TableCell>
                    <div className="font-medium text-foreground">
                      {STATUTORY_SCHEME_LABELS[rate.scheme]}
                      {rate.state_code ? ` — ${rate.state_code}` : ""}
                    </div>
                    {rate.notes ? (
                      <div className="max-w-md text-xs text-foreground-muted">{rate.notes}</div>
                    ) : null}
                  </TableCell>
                  <TableCell className="tabular-nums text-foreground-secondary">
                    <CompanyDate value={rate.effective_from} /> →{" "}
                    {rate.effective_to ? <CompanyDate value={rate.effective_to} /> : "now"}
                  </TableCell>
                  <TableCell className="tabular-nums text-foreground-secondary">
                    {summariseStatutoryRate(rate)}
                  </TableCell>
                  <TableCell>
                    <Badge variant={rate.verified ? "success" : "warning"} dot>
                      {rate.verified ? "Verified" : "Not verified"}
                    </Badge>
                  </TableCell>
                  {canManage ? (
                    <TableCell align="right">
                      <div className="flex justify-end gap-2">
                        <Button
                          type="button"
                          variant="outline"
                          size="xs"
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
                            size="xs"
                            disabled={busyId === rate.id}
                            onClick={() => void verify(rate)}
                          >
                            Verify
                          </Button>
                        ) : null}
                      </div>
                    </TableCell>
                  ) : null}
                </TableRow>
              ))}
            </TableBody>
          </Table>
        ) : null}
      </TableContainer>

      <StatutoryRateDialog
        open={dialogOpen}
        rate={editing}
        onOpenChange={setDialogOpen}
        onSaved={() => void load()}
      />
    </div>
  );
}
