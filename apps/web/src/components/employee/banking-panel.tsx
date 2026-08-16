"use client";

import { useCallback, useEffect, useState } from "react";

import { BankForm } from "@/components/employee/bank-form";
import { ConcurrencyConflictBanner } from "@/components/employee/concurrency-conflict-banner";
import { EffectiveDateBadge } from "@/components/employee/effective-date-badge";
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
import type { Bank } from "@/lib/employee/types";
import {
  EMPTY_BANK_FORM_VALUES,
  PAYMENT_MODE_LABELS,
  buildBankCreatePayload,
  maskAccountNumber,
  validateBankForm,
  type BankFormErrors,
  type BankFormValues,
} from "@/lib/employee/validate-bank";
import type { PaymentMode } from "@/lib/employee/types";

interface BankingPanelProps {
  employeeId: string;
}

export function BankingPanel({ employeeId }: BankingPanelProps) {
  const { toast } = useToast();
  const { can } = usePermissions();

  const [items, setItems] = useState<Bank[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<ApiError | null>(null);

  const [createOpen, setCreateOpen] = useState(false);
  const [values, setValues] = useState<BankFormValues>(EMPTY_BANK_FORM_VALUES);
  const [errors, setErrors] = useState<BankFormErrors>({});
  const [saving, setSaving] = useState(false);
  const [staleMessage, setStaleMessage] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      // SELF-scoped per the locked RBAC decision — the backend, not this component, decides
      // whether the caller sees only their own row or the whole company's (`EMPLOYEE.VIEW_BANKING`).
      const data = await apiClient.get<Bank[]>(`/employees/${employeeId}/bank`);
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
    setValues(EMPTY_BANK_FORM_VALUES);
    setErrors({});
    setStaleMessage(null);
    setCreateOpen(true);
  }

  async function handleCreate() {
    const clientErrors = validateBankForm(values);
    if (Object.keys(clientErrors).length > 0) {
      setErrors(clientErrors);
      return;
    }

    setSaving(true);
    setErrors({});
    setStaleMessage(null);
    try {
      await apiClient.post<Bank>(
        `/employees/${employeeId}/bank`,
        buildBankCreatePayload(values),
        current ? { ifMatch: String(current.version) } : undefined,
      );
      setCreateOpen(false);
      toast({ title: "Bank details saved", variant: "success" });
      await load();
    } catch (err) {
      if (err instanceof ApiError) {
        if (err.status === 409 && err.code === "STALE_RESOURCE") {
          setStaleMessage("The current bank row was changed by someone else since you opened this form.");
          return;
        }
        if (err.status === 409 && err.code === "NO_ACTIVE_EMPLOYMENT") {
          toast({
            title: "Could not save bank details",
            description: "This employee has no active employment episode covering this date.",
            variant: "danger",
          });
          return;
        }
        if (err.status === 409 && err.code === "BANK_DATES_OVERLAP") {
          toast({
            title: "Could not save bank details",
            description: "This effective date overlaps an existing bank row.",
            variant: "danger",
          });
          return;
        }
        if (err.status === 422) {
          setErrors({
            effectiveFrom: getFieldError(err.details, "effective_from"),
            paymentMode: getFieldError(err.details, "payment_mode"),
          });
          return;
        }
        if (err.status === 403) {
          setCreateOpen(false);
          toast({ title: "You don't have permission to do that", variant: "danger" });
          return;
        }
      }
      toast({ title: "Could not save bank details", description: describeApiError(err), variant: "danger" });
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="space-y-6">
      <div className="rounded-md border border-info/30 bg-info-subtle p-3 text-xs text-foreground-secondary">
        Banking information is restricted and visible only to the employee themselves and holders
        of EMPLOYEE.VIEW_BANKING. Account numbers are always masked here.
      </div>

      {loading ? (
        <Card>
          <CardContent className="pt-6">
            <LoadingState label="Loading banking history…" />
          </CardContent>
        </Card>
      ) : null}

      {error && !loading ? (
        <Card>
          <CardContent className="pt-6">
            <ErrorState
              message={
                error.status === 403
                  ? "You do not have permission to view this employee's banking details."
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
                <h3 className="text-sm font-medium text-foreground">Current bank details</h3>
                {canUpdate ? (
                  <Button type="button" size="sm" onClick={openCreate}>
                    Record a revision
                  </Button>
                ) : null}
              </div>

              {current ? (
                <dl className="mt-4 grid grid-cols-1 gap-4 sm:grid-cols-2">
                  <div>
                    <dt className="text-xs font-medium uppercase tracking-wide text-foreground-muted">Account holder</dt>
                    <dd className="mt-0.5 text-sm text-foreground">{current.account_holder_name ?? "—"}</dd>
                  </div>
                  <div>
                    <dt className="text-xs font-medium uppercase tracking-wide text-foreground-muted">Account number</dt>
                    <dd className="mt-0.5 font-mono text-sm text-foreground">
                      {maskAccountNumber(current.account_number_enc)}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-xs font-medium uppercase tracking-wide text-foreground-muted">Bank</dt>
                    <dd className="mt-0.5 text-sm text-foreground">{current.bank_name ?? "—"}</dd>
                  </div>
                  <div>
                    <dt className="text-xs font-medium uppercase tracking-wide text-foreground-muted">IFSC</dt>
                    <dd className="mt-0.5 text-sm text-foreground">{current.ifsc ?? "—"}</dd>
                  </div>
                  <div>
                    <dt className="text-xs font-medium uppercase tracking-wide text-foreground-muted">Payment mode</dt>
                    <dd className="mt-0.5 text-sm text-foreground">
                      {current.payment_mode
                        ? PAYMENT_MODE_LABELS[current.payment_mode as PaymentMode] ?? current.payment_mode
                        : "—"}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-xs font-medium uppercase tracking-wide text-foreground-muted">Verification</dt>
                    <dd className="mt-0.5 text-sm">
                      <Badge variant={current.verification_status === "VERIFIED" ? "success" : "outline"}>
                        {current.verification_status}
                      </Badge>
                    </dd>
                  </div>
                </dl>
              ) : (
                <EmptyState
                  className="mt-4"
                  title="No bank details on record yet."
                  description="Add this employee's bank details for payroll disbursement. A missing row does not necessarily mean the employee has exited — bank details survive termination for final settlement."
                />
              )}
            </CardContent>
          </Card>

          {history.length > 0 ? (
            <Card>
              <CardContent className="pt-6">
                <h3 className="text-sm font-medium text-foreground">Banking history</h3>
                <ul className="mt-3 divide-y divide-border">
                  {[...history]
                    .sort((a, b) => b.effective_from.localeCompare(a.effective_from))
                    .map((item) => (
                      <li key={item.id} className="py-3 first:pt-0 last:pb-0">
                        <div className="flex items-center justify-between gap-4">
                          <p className="font-mono text-sm font-medium text-foreground">
                            {maskAccountNumber(item.account_number_enc)}
                          </p>
                          <EffectiveDateBadge effectiveTo={item.effective_to} />
                        </div>
                        <p className="mt-0.5 text-xs text-foreground-muted">
                          {item.effective_from} – {item.effective_to} · {item.bank_name ?? "—"}
                        </p>
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
            <DialogTitle>Record a bank details revision</DialogTitle>
          </DialogHeader>
          {staleMessage ? (
            <ConcurrencyConflictBanner
              message={staleMessage}
              onReload={() => void load()}
              onCancel={() => setStaleMessage(null)}
            />
          ) : null}
          <div className="max-h-[60vh] overflow-y-auto pr-1">
            <BankForm values={values} errors={errors} onChange={setValues} idPrefix="bank-" />
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
