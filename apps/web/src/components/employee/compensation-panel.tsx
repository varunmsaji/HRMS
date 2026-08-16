"use client";

import { useCallback, useEffect, useState } from "react";

import { CompensationForm } from "@/components/employee/compensation-form";
import { ConcurrencyConflictBanner } from "@/components/employee/concurrency-conflict-banner";
import { EffectiveDateBadge } from "@/components/employee/effective-date-badge";
import { EmptyState } from "@/components/common/empty-state";
import { ErrorState } from "@/components/common/error-state";
import { LoadingState } from "@/components/common/loading-state";
import { useToast } from "@/components/common/toast";
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
import type { Compensation } from "@/lib/employee/types";
import {
  EMPTY_COMPENSATION_FORM_VALUES,
  buildCompensationCreatePayload,
  minorToUnits,
  validateCompensationForm,
  REVISION_TYPE_LABELS,
  type CompensationFormErrors,
  type CompensationFormValues,
} from "@/lib/employee/validate-compensation";
import type { RevisionType } from "@/lib/employee/types";

interface CompensationPanelProps {
  employeeId: string;
}

function formatCtc(minor: number, currency: string): string {
  return `${currency} ${minorToUnits(minor)}`;
}

export function CompensationPanel({ employeeId }: CompensationPanelProps) {
  const { toast } = useToast();
  const { can } = usePermissions();

  const [items, setItems] = useState<Compensation[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<ApiError | null>(null);

  const [createOpen, setCreateOpen] = useState(false);
  const [values, setValues] = useState<CompensationFormValues>(EMPTY_COMPENSATION_FORM_VALUES);
  const [errors, setErrors] = useState<CompensationFormErrors>({});
  const [saving, setSaving] = useState(false);
  const [staleMessage, setStaleMessage] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await apiClient.get<Compensation[]>(`/employees/${employeeId}/compensation`);
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
  const canUpdate = can("EMPLOYEE.UPDATE_COMPENSATION");

  function openCreate() {
    setValues({ ...EMPTY_COMPENSATION_FORM_VALUES, currency: current?.currency ?? "INR" });
    setErrors({});
    setStaleMessage(null);
    setCreateOpen(true);
  }

  async function handleCreate() {
    const clientErrors = validateCompensationForm(values);
    if (Object.keys(clientErrors).length > 0) {
      setErrors(clientErrors);
      return;
    }

    setSaving(true);
    setErrors({});
    setStaleMessage(null);
    try {
      await apiClient.post<Compensation>(
        `/employees/${employeeId}/compensation`,
        buildCompensationCreatePayload(values),
        current ? { ifMatch: String(current.version) } : undefined,
      );
      setCreateOpen(false);
      toast({ title: "Compensation revision saved", variant: "success" });
      await load();
    } catch (err) {
      if (err instanceof ApiError) {
        if (err.status === 409 && err.code === "STALE_RESOURCE") {
          setStaleMessage("The current compensation row was changed by someone else since you opened this form.");
          return;
        }
        if (err.status === 409 && err.code === "NO_ACTIVE_EMPLOYMENT") {
          toast({
            title: "Could not save compensation",
            description: "This employee has no active employment episode covering this date.",
            variant: "danger",
          });
          return;
        }
        if (err.status === 409 && err.code === "COMPENSATION_DATES_OVERLAP") {
          toast({
            title: "Could not save compensation",
            description: "This effective date overlaps an existing compensation row.",
            variant: "danger",
          });
          return;
        }
        if (err.status === 422) {
          setErrors({
            effectiveFrom: getFieldError(err.details, "effective_from"),
            annualCtc: getFieldError(err.details, "annual_ctc_minor"),
            currency: getFieldError(err.details, "currency"),
            revisionType: getFieldError(err.details, "revision_type"),
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
      toast({ title: "Could not save compensation", description: describeApiError(err), variant: "danger" });
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="space-y-6">
      {loading ? (
        <Card>
          <CardContent className="pt-6">
            <LoadingState label="Loading compensation history…" />
          </CardContent>
        </Card>
      ) : null}

      {error && !loading ? (
        <Card>
          <CardContent className="pt-6">
            <ErrorState
              message={
                error.status === 403
                  ? "You do not have permission to view this employee's compensation."
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
                <h3 className="text-sm font-medium text-foreground">Current compensation</h3>
                {canUpdate ? (
                  <Button type="button" size="sm" onClick={openCreate}>
                    Record a revision
                  </Button>
                ) : null}
              </div>

              {current ? (
                <dl className="mt-4 grid grid-cols-1 gap-4 sm:grid-cols-2">
                  <div>
                    <dt className="text-xs font-medium uppercase tracking-wide text-foreground-muted">Annual CTC</dt>
                    <dd className="mt-0.5 text-sm text-foreground">{formatCtc(current.annual_ctc_minor, current.currency)}</dd>
                  </div>
                  <div>
                    <dt className="text-xs font-medium uppercase tracking-wide text-foreground-muted">Revision type</dt>
                    <dd className="mt-0.5 text-sm text-foreground">
                      {REVISION_TYPE_LABELS[current.revision_type as RevisionType] ?? current.revision_type}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-xs font-medium uppercase tracking-wide text-foreground-muted">Effective from</dt>
                    <dd className="mt-0.5 text-sm text-foreground">{current.effective_from}</dd>
                  </div>
                  <div>
                    <dt className="text-xs font-medium uppercase tracking-wide text-foreground-muted">Reason</dt>
                    <dd className="mt-0.5 text-sm text-foreground">{current.revision_reason ?? "—"}</dd>
                  </div>
                </dl>
              ) : (
                <EmptyState
                  className="mt-4"
                  title="No compensation on record yet."
                  description="Record this employee's joining CTC to start their compensation history."
                />
              )}
            </CardContent>
          </Card>

          {history.length > 0 ? (
            <Card>
              <CardContent className="pt-6">
                <h3 className="text-sm font-medium text-foreground">Compensation history</h3>
                <ul className="mt-3 divide-y divide-border">
                  {[...history]
                    .sort((a, b) => b.effective_from.localeCompare(a.effective_from))
                    .map((item) => (
                      <li key={item.id} className="py-3 first:pt-0 last:pb-0">
                        <div className="flex items-center justify-between gap-4">
                          <p className="text-sm font-medium text-foreground">{formatCtc(item.annual_ctc_minor, item.currency)}</p>
                          <EffectiveDateBadge effectiveTo={item.effective_to} />
                        </div>
                        <p className="mt-0.5 text-xs text-foreground-muted">
                          {item.effective_from} – {item.effective_to} ·{" "}
                          {REVISION_TYPE_LABELS[item.revision_type as RevisionType] ?? item.revision_type}
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
        <DialogContent className="max-w-lg">
          <DialogHeader>
            <DialogTitle>Record a compensation revision</DialogTitle>
          </DialogHeader>
          {staleMessage ? (
            <ConcurrencyConflictBanner
              message={staleMessage}
              onReload={() => void load()}
              onCancel={() => setStaleMessage(null)}
            />
          ) : null}
          <CompensationForm values={values} errors={errors} onChange={setValues} idPrefix="compensation-" />
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
