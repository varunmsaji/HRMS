"use client";

import { useCallback, useEffect, useState } from "react";

import { ConcurrencyConflictBanner } from "@/components/employee/concurrency-conflict-banner";
import { EffectiveDateBadge } from "@/components/employee/effective-date-badge";
import { StatutoryForm } from "@/components/employee/statutory-form";
import { EmptyState } from "@/components/common/empty-state";
import { ErrorState } from "@/components/common/error-state";
import { LoadingState } from "@/components/common/loading-state";
import { useToast } from "@/components/common/toast";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { apiClient } from "@/lib/api/client";
import { ApiError, describeApiError, getFieldError } from "@/lib/api/errors";
import { usePermissions } from "@/lib/auth/use-permissions";
import type { Statutory } from "@/lib/employee/types";
import {
  EMPTY_STATUTORY_FORM_VALUES,
  buildStatutoryCreatePayload,
  validateStatutoryForm,
  type StatutoryFormErrors,
  type StatutoryFormValues,
} from "@/lib/employee/validate-statutory";

interface StatutoryPanelProps {
  employeeId: string;
}

export function StatutoryPanel({ employeeId }: StatutoryPanelProps) {
  const { toast } = useToast();
  const { can } = usePermissions();

  const [items, setItems] = useState<Statutory[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<ApiError | null>(null);

  const [createOpen, setCreateOpen] = useState(false);
  const [values, setValues] = useState<StatutoryFormValues>(EMPTY_STATUTORY_FORM_VALUES);
  const [errors, setErrors] = useState<StatutoryFormErrors>({});
  const [saving, setSaving] = useState(false);
  const [staleMessage, setStaleMessage] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await apiClient.get<Statutory[]>(`/employees/${employeeId}/statutory`);
      setItems(data);
    } catch (err) {
      setItems(null);
      setError(
        err instanceof ApiError
          ? err
          : new ApiError({ status: 0, code: "UNKNOWN_ERROR", message: "Something went wrong." }),
      );
    } finally {
      setLoading(false);
    }
  }, [employeeId]);

  useEffect(() => {
    void load();
  }, [load]);

  const current = items?.find((item) => item.effective_to === null) ?? null;
  const history = items?.filter((item) => item.effective_to !== null) ?? [];
  const canUpdate = can("EMPLOYEE.UPDATE_SENSITIVE");

  function openCreate() {
    setValues(EMPTY_STATUTORY_FORM_VALUES);
    setErrors({});
    setStaleMessage(null);
    setCreateOpen(true);
  }

  async function handleCreate() {
    const clientErrors = validateStatutoryForm(values);
    if (Object.keys(clientErrors).length > 0) {
      setErrors(clientErrors);
      return;
    }

    setSaving(true);
    setErrors({});
    setStaleMessage(null);
    try {
      await apiClient.post<Statutory>(
        `/employees/${employeeId}/statutory`,
        buildStatutoryCreatePayload(values),
        current ? { ifMatch: String(current.version) } : undefined,
      );
      setCreateOpen(false);
      toast({ title: "Statutory revision saved", variant: "success" });
      await load();
    } catch (err) {
      if (err instanceof ApiError) {
        if (err.status === 409 && err.code === "STALE_RESOURCE") {
          setStaleMessage("The current statutory row was changed by someone else since you opened this form.");
          return;
        }
        if (err.status === 409 && err.code === "TAX_REGIME_SWITCH_NOT_ALLOWED") {
          toast({
            title: "Could not save statutory revision",
            description: "Tax regime can only be switched once per financial year.",
            variant: "danger",
          });
          return;
        }
        if (err.status === 409 && err.code === "NO_ACTIVE_EMPLOYMENT") {
          toast({
            title: "Could not save statutory revision",
            description: "This employee has no active employment episode covering this date.",
            variant: "danger",
          });
          return;
        }
        if (err.status === 409 && err.code === "STATUTORY_DATES_OVERLAP") {
          toast({
            title: "Could not save statutory revision",
            description: "This effective date overlaps an existing statutory row.",
            variant: "danger",
          });
          return;
        }
        if (err.status === 422) {
          setErrors({
            effectiveFrom: getFieldError(err.details, "effective_from"),
            taxRegime: getFieldError(err.details, "tax_regime"),
            revisionReason: getFieldError(err.details, "revision_reason"),
          });
          return;
        }
        if (err.status === 403) {
          setCreateOpen(false);
          toast({ title: "You don't have permission to do that", variant: "danger" });
          return;
        }
      }
      toast({ title: "Could not save statutory revision", description: describeApiError(err), variant: "danger" });
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="space-y-6">
      <div className="rounded-md border border-info/30 bg-info-subtle p-3 text-xs text-foreground-secondary">
        Statutory information is restricted — visible only to holders of EMPLOYEE.VIEW_STATUTORY.
      </div>

      {loading ? (
        <Card>
          <CardContent className="pt-6">
            <LoadingState label="Loading statutory history…" />
          </CardContent>
        </Card>
      ) : null}

      {error && !loading ? (
        <Card>
          <CardContent className="pt-6">
            <ErrorState
              message={
                error.status === 403
                  ? "You do not have permission to view this employee's statutory information."
                  : error.message
              }
              onRetry={() => void load()}
            />
          </CardContent>
        </Card>
      ) : null}

      {!loading && !error && items ? (
        <>
          <Card>
            <CardContent className="pt-6">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <h3 className="text-sm font-medium text-foreground">Current statutory details</h3>
                {canUpdate ? (
                  <Button type="button" size="sm" onClick={openCreate}>
                    Record a revision
                  </Button>
                ) : null}
              </div>

              {current ? (
                <dl className="mt-4 grid grid-cols-1 gap-4 sm:grid-cols-2">
                  <div>
                    <dt className="text-xs font-medium uppercase tracking-wide text-foreground-muted">Tax regime</dt>
                    <dd className="mt-0.5 text-sm text-foreground">{current.tax_regime ?? "—"}</dd>
                  </div>
                  <div>
                    <dt className="text-xs font-medium uppercase tracking-wide text-foreground-muted">PF</dt>
                    <dd className="mt-0.5 text-sm text-foreground">
                      {current.is_pf_applicable ? `Applicable${current.pf_number ? ` · ${current.pf_number}` : ""}` : "Not applicable"}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-xs font-medium uppercase tracking-wide text-foreground-muted">ESI</dt>
                    <dd className="mt-0.5 text-sm text-foreground">
                      {current.is_esi_applicable ? `Applicable${current.esi_ip_number ? ` · ${current.esi_ip_number}` : ""}` : "Not applicable"}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-xs font-medium uppercase tracking-wide text-foreground-muted">LWF</dt>
                    <dd className="mt-0.5 text-sm text-foreground">{current.is_lwf_applicable ? "Applicable" : "Not applicable"}</dd>
                  </div>
                  <div>
                    <dt className="text-xs font-medium uppercase tracking-wide text-foreground-muted">Director / Intl. worker</dt>
                    <dd className="mt-0.5 flex gap-2 text-sm text-foreground">
                      {current.is_director ? <Badge variant="outline">Director</Badge> : null}
                      {current.is_international_worker ? <Badge variant="outline">International worker</Badge> : null}
                      {!current.is_director && !current.is_international_worker ? "—" : null}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-xs font-medium uppercase tracking-wide text-foreground-muted">Effective from</dt>
                    <dd className="mt-0.5 text-sm text-foreground">{current.effective_from}</dd>
                  </div>
                </dl>
              ) : (
                <EmptyState
                  className="mt-4"
                  title="No statutory information on record yet."
                  description="Record this employee's PF/ESI/LWF/tax regime details."
                />
              )}
            </CardContent>
          </Card>

          {history.length > 0 ? (
            <Card>
              <CardContent className="pt-6">
                <h3 className="text-sm font-medium text-foreground">Statutory history</h3>
                <ul className="mt-3 divide-y divide-border">
                  {[...history]
                    .sort((a, b) => b.effective_from.localeCompare(a.effective_from))
                    .map((item) => (
                      <li key={item.id} className="py-3 first:pt-0 last:pb-0">
                        <div className="flex items-center justify-between gap-4">
                          <p className="text-sm font-medium text-foreground">Tax regime: {item.tax_regime ?? "—"}</p>
                          <EffectiveDateBadge effectiveTo={item.effective_to} />
                        </div>
                        <p className="mt-0.5 text-xs text-foreground-muted">
                          {item.effective_from} – {item.effective_to}
                        </p>
                        {item.revision_reason ? (
                          <p className="mt-1 text-xs text-foreground-muted">{item.revision_reason}</p>
                        ) : null}
                      </li>
                    ))}
                </ul>
              </CardContent>
            </Card>
          ) : null}
        </>
      ) : null}

      <Dialog open={createOpen} onOpenChange={(open) => (!saving ? setCreateOpen(open) : null)}>
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle>Record a statutory revision</DialogTitle>
          </DialogHeader>
          {staleMessage ? (
            <ConcurrencyConflictBanner
              message={staleMessage}
              onReload={() => void load()}
              onCancel={() => setStaleMessage(null)}
            />
          ) : null}
          <div className="max-h-[60vh] overflow-y-auto pr-1">
            <StatutoryForm values={values} errors={errors} onChange={setValues} idPrefix="statutory-" />
          </div>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => setCreateOpen(false)} disabled={saving}>
              Cancel
            </Button>
            <Button type="button" onClick={() => void handleCreate()} disabled={saving}>
              {saving ? "Saving…" : "Save revision"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
