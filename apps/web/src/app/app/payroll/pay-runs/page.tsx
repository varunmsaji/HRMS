"use client";

import { Banknote } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { EmptyState } from "@/components/common/empty-state";
import { ErrorState } from "@/components/common/error-state";
import { FormField } from "@/components/common/form-field";
import { LoadingState } from "@/components/common/loading-state";
import { PageHeader } from "@/components/common/page-header";
import { useToast } from "@/components/common/toast";
import { PayRunStatusBadge } from "@/components/payroll/pay-run-status-badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/native-select";
import { apiClient } from "@/lib/api/client";
import { ApiError, describeApiError } from "@/lib/api/errors";
import { businessToday } from "@/lib/attendance/format";
import { useAuth } from "@/lib/auth/auth-context";
import { usePermissions } from "@/lib/auth/use-permissions";
import type { LegalEntity } from "@/lib/legal-entity/types";
import {
  formatInr,
  formatPayMonth,
  type PayrollSetting,
  type PayRun,
} from "@/lib/payroll/types";

/** The month before `today` as `YYYY-MM` — payroll runs in the first week of the next month
 * (decision 18). */
function previousMonth(today: string): string {
  const [year, month] = today.split("-").map(Number);
  const date = new Date(Date.UTC(year, month - 2, 1));
  return `${date.getUTCFullYear()}-${String(date.getUTCMonth() + 1).padStart(2, "0")}`;
}

/** Payroll Phase 5.2 — pay runs (`/v1/payroll/pay-runs`): one per company per calendar
 * month (decisions 14/18). */
export default function PayRunsPage() {
  const router = useRouter();
  const { toast } = useToast();
  const { user } = useAuth();
  const { can } = usePermissions();
  const canProcess = can("PAYROLL.RUN_PROCESS");
  const canSetup = can("PAYROLL.SETUP_MANAGE");

  const [runs, setRuns] = useState<PayRun[] | null>(null);
  const [legalEntities, setLegalEntities] = useState<LegalEntity[]>([]);
  const [entityFilter, setEntityFilter] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<ApiError | null>(null);

  const [createOpen, setCreateOpen] = useState(false);
  const [entityId, setEntityId] = useState("");
  const [month, setMonth] = useState(() =>
    previousMonth(businessToday(user?.company_timezone ?? "Asia/Kolkata")),
  );
  const [createError, setCreateError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const [settings, setSettings] = useState<PayrollSetting | null>(null);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [threshold, setThreshold] = useState("");
  const [settingsError, setSettingsError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [data, entities] = await Promise.all([
        apiClient.get<PayRun[]>("/payroll/pay-runs"),
        apiClient.get<LegalEntity[]>("/legal-entities").catch(() => [] as LegalEntity[]),
      ]);
      setRuns(data);
      setLegalEntities(entities);
    } catch (err) {
      setRuns(null);
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

  const entityName = (id: string) => legalEntities.find((e) => e.id === id)?.name ?? "—";
  const activeEntities = legalEntities.filter((e) => e.is_active);
  const visibleRuns = runs?.filter((run) => !entityFilter || run.legal_entity_id === entityFilter);

  async function handleCreate() {
    setSaving(true);
    setCreateError(null);
    try {
      const created = await apiClient.post<PayRun>("/payroll/pay-runs", {
        legal_entity_id: entityId,
        month,
      });
      setCreateOpen(false);
      router.push(`/app/payroll/pay-runs/${created.id}`);
    } catch (err) {
      setCreateError(describeApiError(err));
    } finally {
      setSaving(false);
    }
  }

  async function openSettings() {
    setSettingsError(null);
    try {
      const current = await apiClient.get<PayrollSetting>("/payroll/settings");
      setSettings(current);
      setThreshold(current.variance_threshold_percent);
      setSettingsOpen(true);
    } catch (err) {
      toast({ title: "Could not load settings", description: describeApiError(err), variant: "danger" });
    }
  }

  async function saveSettings() {
    if (!settings) return;
    setSaving(true);
    setSettingsError(null);
    try {
      const updated = await apiClient.put<PayrollSetting>(
        "/payroll/settings",
        { variance_threshold_percent: threshold.trim() },
        { ifMatch: String(settings.version) },
      );
      setSettings(updated);
      setSettingsOpen(false);
      toast({ title: "Payroll settings saved", variant: "success" });
    } catch (err) {
      setSettingsError(describeApiError(err));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Pay Runs"
        description="Monthly payroll for each company, from the closed attendance period."
        actions={
          <div className="flex flex-wrap gap-2">
            {canSetup ? (
              <Button type="button" variant="outline" onClick={() => void openSettings()}>
                Settings
              </Button>
            ) : null}
            {canProcess ? (
              <Button
                type="button"
                onClick={() => {
                  setEntityId(activeEntities[0]?.id ?? "");
                  setCreateError(null);
                  setCreateOpen(true);
                }}
              >
                New pay run
              </Button>
            ) : null}
          </div>
        }
      />

      <Card>
        <CardContent className="pt-6">
          {legalEntities.length > 1 ? (
            <div className="mb-4 max-w-xs">
              <NativeSelect
                aria-label="Filter by company"
                value={entityFilter}
                onChange={(e) => setEntityFilter(e.target.value)}
              >
                <option value="">All companies</option>
                {legalEntities.map((entity) => (
                  <option key={entity.id} value={entity.id}>
                    {entity.name}
                  </option>
                ))}
              </NativeSelect>
            </div>
          ) : null}
          {loading ? <LoadingState label="Loading pay runs…" /> : null}
          {error && !loading ? (
            <ErrorState
              message={
                error.status === 403 ? "You do not have permission to view pay runs." : error.message
              }
              onRetry={() => void load()}
            />
          ) : null}
          {!loading && !error && runs && runs.length === 0 ? (
            <EmptyState
              icon={Banknote}
              title="No pay runs yet."
              description="Close the month's attendance period for a company, then create its pay run."
            />
          ) : null}
          {!loading && !error && visibleRuns && visibleRuns.length > 0 ? (
            <div className="overflow-x-auto rounded-md border border-border">
              <table className="w-full text-sm">
                <thead className="bg-surface-secondary text-xs uppercase tracking-wide text-foreground-muted">
                  <tr>
                    <th className="px-3 py-2 text-left font-medium">Month</th>
                    <th className="px-3 py-2 text-left font-medium">Company</th>
                    <th className="px-3 py-2 text-left font-medium">Status</th>
                    <th className="px-3 py-2 text-right font-medium">Employees</th>
                    <th className="px-3 py-2 text-right font-medium">Net pay</th>
                    <th className="px-3 py-2 text-left font-medium">Pay date</th>
                    <th className="px-3 py-2 text-right font-medium">Detail</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border">
                  {visibleRuns.map((run) => (
                    <tr key={run.id} className="hover:bg-accent">
                      <td className="px-3 py-2 font-medium text-foreground">
                        {formatPayMonth(run.month)}
                      </td>
                      <td className="px-3 py-2 text-foreground-secondary">
                        {entityName(run.legal_entity_id)}
                      </td>
                      <td className="px-3 py-2">
                        <PayRunStatusBadge status={run.status} />
                      </td>
                      <td className="px-3 py-2 text-right tabular-nums">{run.employee_count}</td>
                      <td className="px-3 py-2 text-right tabular-nums">
                        {run.status === "DRAFT" || run.status === "INPUTS_LOCKED"
                          ? "—"
                          : formatInr(run.net_minor)}
                      </td>
                      <td className="px-3 py-2 text-foreground-secondary">{run.pay_date}</td>
                      <td className="px-3 py-2 text-right">
                        <Link
                          href={`/app/payroll/pay-runs/${run.id}`}
                          className="text-sm font-medium text-primary hover:underline"
                        >
                          View
                        </Link>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : null}
        </CardContent>
      </Card>

      <Dialog open={createOpen} onOpenChange={(next) => !saving && setCreateOpen(next)}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle>New pay run</DialogTitle>
            <DialogDescription>
              One pay run per company per month. Its inputs can be locked once that
              month&apos;s attendance period is closed.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4">
            <FormField id="pay-run-entity" label="Company" required>
              <NativeSelect value={entityId} onChange={(e) => setEntityId(e.target.value)}>
                {activeEntities.map((entity) => (
                  <option key={entity.id} value={entity.id}>
                    {entity.name}
                  </option>
                ))}
              </NativeSelect>
            </FormField>
            <FormField id="pay-run-month" label="Month" required>
              <Input type="month" value={month} onChange={(e) => setMonth(e.target.value)} />
            </FormField>
            {createError ? (
              <p role="alert" className="text-sm text-danger">
                {createError}
              </p>
            ) : null}
          </div>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => setCreateOpen(false)} disabled={saving}>
              Cancel
            </Button>
            <Button
              type="button"
              onClick={() => void handleCreate()}
              disabled={saving || !entityId || !/^\d{4}-\d{2}$/.test(month)}
            >
              {saving ? "Creating…" : "Create pay run"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={settingsOpen} onOpenChange={(next) => !saving && setSettingsOpen(next)}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle>Payroll settings</DialogTitle>
            <DialogDescription>
              An employee whose net pay changes by more than this against the previous finalised
              run is flagged, and needs a reason before the run can be approved.
            </DialogDescription>
          </DialogHeader>
          <FormField
            id="variance-threshold"
            label="Variance threshold (%)"
            required
            error={settingsError ?? undefined}
          >
            <Input
              inputMode="decimal"
              value={threshold}
              onChange={(e) => setThreshold(e.target.value)}
            />
          </FormField>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => setSettingsOpen(false)} disabled={saving}>
              Cancel
            </Button>
            <Button
              type="button"
              onClick={() => void saveSettings()}
              disabled={saving || !/^\d+(\.\d{1,2})?$/.test(threshold.trim())}
            >
              {saving ? "Saving…" : "Save"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
