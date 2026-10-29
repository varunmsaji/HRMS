"use client";

import { useCallback, useEffect, useState } from "react";

import { CompanyDate } from "@/components/common/company-date";
import { EmptyState } from "@/components/common/empty-state";
import { ErrorState } from "@/components/common/error-state";
import { FormField } from "@/components/common/form-field";
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
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/native-select";
import { apiClient } from "@/lib/api/client";
import { ApiError, describeApiError, getFieldError } from "@/lib/api/errors";
import { usePermissions } from "@/lib/auth/use-permissions";
import {
  PAY_BASIS_DESCRIPTIONS,
  PAY_BASIS_LABELS,
  PAY_BASIS_VALUES,
  type Employment,
  type PayBasis,
} from "@/lib/employee/types";
import {
  EMPTY_EMPLOYMENT_FORM_VALUES,
  EMPTY_TERMINATE_FORM_VALUES,
  buildEmploymentCorrectionPatch,
  buildEmploymentCreatePayload,
  validateEmploymentForm,
  validateTerminateForm,
  type EmploymentCorrectionValues,
  type EmploymentFormErrors,
  type EmploymentFormValues,
  type TerminateFormValues,
} from "@/lib/employee/validate-employment";
import type { LegalEntity } from "@/lib/legal-entity/types";

interface EmploymentPanelProps {
  employeeId: string;
}

export function EmploymentPanel({ employeeId }: EmploymentPanelProps) {
  const { toast } = useToast();
  const { can } = usePermissions();

  const [employments, setEmployments] = useState<Employment[] | null>(null);
  const [legalEntities, setLegalEntities] = useState<LegalEntity[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<ApiError | null>(null);

  const [hireOpen, setHireOpen] = useState(false);
  const [hireValues, setHireValues] = useState<EmploymentFormValues>(EMPTY_EMPLOYMENT_FORM_VALUES);
  const [hireErrors, setHireErrors] = useState<EmploymentFormErrors>({});
  const [hiring, setHiring] = useState(false);

  const [terminateOpen, setTerminateOpen] = useState(false);
  const [terminateValues, setTerminateValues] = useState<TerminateFormValues>(EMPTY_TERMINATE_FORM_VALUES);
  const [terminateErrors, setTerminateErrors] = useState<Partial<Record<"lastWorkingDay", string>>>({});
  const [terminating, setTerminating] = useState(false);

  const [editOpen, setEditOpen] = useState(false);
  const [editValues, setEditValues] = useState<EmploymentCorrectionValues>({
    legalEntityId: "",
    probationEndDate: "",
    payBasis: "MONTHLY",
  });
  const [editErrors, setEditErrors] = useState<EmploymentFormErrors>({});
  const [editing, setEditing] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [employmentData, legalEntityData] = await Promise.all([
        apiClient.get<Employment[]>(`/employees/${employeeId}/employments`),
        apiClient.get<LegalEntity[]>("/legal-entities").catch(() => []),
      ]);
      setEmployments(employmentData);
      setLegalEntities(legalEntityData);
    } catch (err) {
      setEmployments(null);
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

  const current = employments?.find((item) => item.status === "ACTIVE") ?? null;
  const history = employments?.filter((item) => item.status !== "ACTIVE") ?? [];
  const isRehire = Boolean(employments && employments.length > 0 && !current);

  function legalEntityName(id: string): string {
    return legalEntities.find((entity) => entity.id === id)?.name ?? "Unknown company";
  }

  function openHire() {
    setHireValues(EMPTY_EMPLOYMENT_FORM_VALUES);
    setHireErrors({});
    setHireOpen(true);
  }

  async function handleHire() {
    const clientErrors = validateEmploymentForm(hireValues);
    if (Object.keys(clientErrors).length > 0) {
      setHireErrors(clientErrors);
      return;
    }

    setHiring(true);
    setHireErrors({});
    try {
      await apiClient.post<Employment>(
        `/employees/${employeeId}/employments`,
        buildEmploymentCreatePayload(hireValues),
      );
      setHireOpen(false);
      toast({ title: isRehire ? "Employee rehired" : "Employment created", variant: "success" });
      await load();
    } catch (err) {
      if (err instanceof ApiError) {
        if (err.status === 422) {
          setHireErrors({
            legalEntityId: getFieldError(err.details, "legal_entity_id"),
            joiningDate: getFieldError(err.details, "joining_date"),
          });
          return;
        }
        if (err.status === 403) {
          setHireOpen(false);
          toast({ title: "You don't have permission to do that", variant: "danger" });
          return;
        }
        if (err.status === 409 && err.code === "EMPLOYMENT_DATES_OVERLAP") {
          toast({
            title: "Could not create employment",
            description: "This employee already has an active employment episode.",
            variant: "danger",
          });
          return;
        }
      }
      toast({ title: "Could not create employment", description: describeApiError(err), variant: "danger" });
    } finally {
      setHiring(false);
    }
  }

  function openTerminate() {
    setTerminateValues(EMPTY_TERMINATE_FORM_VALUES);
    setTerminateErrors({});
    setTerminateOpen(true);
  }

  async function handleTerminate() {
    if (!current) return;
    const clientErrors = validateTerminateForm(terminateValues);
    if (Object.keys(clientErrors).length > 0) {
      setTerminateErrors(clientErrors);
      return;
    }

    setTerminating(true);
    setTerminateErrors({});
    try {
      await apiClient.post<Employment>(
        `/employees/${employeeId}/employments/${current.id}/terminate`,
        { last_working_day: terminateValues.lastWorkingDay },
        { ifMatch: String(current.version) },
      );
      setTerminateOpen(false);
      toast({ title: "Employee terminated", variant: "success" });
      await load();
    } catch (err) {
      if (err instanceof ApiError) {
        if (err.status === 422) {
          setTerminateErrors({ lastWorkingDay: getFieldError(err.details, "last_working_day") });
          return;
        }
        if (err.status === 403) {
          setTerminateOpen(false);
          toast({ title: "You don't have permission to do that", variant: "danger" });
          return;
        }
        if (err.status === 409 && err.code === "STALE_RESOURCE") {
          toast({
            title: "Could not terminate employment",
            description: "This employment record was changed by someone else. Reload and try again.",
            variant: "danger",
          });
          setTerminateOpen(false);
          void load();
          return;
        }
      }
      toast({ title: "Could not terminate employment", description: describeApiError(err), variant: "danger" });
    } finally {
      setTerminating(false);
    }
  }

  function openEdit() {
    if (!current) return;
    setEditValues({
      legalEntityId: current.legal_entity_id,
      probationEndDate: current.probation_end_date ?? "",
      payBasis: current.pay_basis,
    });
    setEditErrors({});
    setEditOpen(true);
  }

  async function handleEdit() {
    if (!current) return;
    const patch = buildEmploymentCorrectionPatch(editValues, current);
    if (Object.keys(patch).length === 0) {
      setEditOpen(false);
      return;
    }

    setEditing(true);
    setEditErrors({});
    try {
      await apiClient.patch<Employment>(`/employees/${employeeId}/employments/${current.id}`, patch, {
        ifMatch: String(current.version),
      });
      setEditOpen(false);
      toast({ title: "Employment updated", variant: "success" });
      await load();
    } catch (err) {
      if (err instanceof ApiError) {
        if (err.status === 422) {
          setEditErrors({
            legalEntityId: getFieldError(err.details, "legal_entity_id"),
            probationEndDate: getFieldError(err.details, "probation_end_date"),
          });
          return;
        }
        if (err.status === 403) {
          setEditOpen(false);
          toast({ title: "You don't have permission to do that", variant: "danger" });
          return;
        }
        if (err.status === 409 && err.code === "STALE_RESOURCE") {
          toast({
            title: "Could not update employment",
            description: "This employment record was changed by someone else. Reload and try again.",
            variant: "danger",
          });
          setEditOpen(false);
          void load();
          return;
        }
      }
      toast({ title: "Could not update employment", description: describeApiError(err), variant: "danger" });
    } finally {
      setEditing(false);
    }
  }

  const canCreate = can("EMPLOYEE.CREATE");
  const canUpdate = can("EMPLOYEE.UPDATE");
  const canTerminate = can("EMPLOYEE.TERMINATE");

  return (
    <div className="space-y-6">
      {loading ? (
        <Card>
          <CardContent className="pt-6">
            <LoadingState label="Loading employment history…" />
          </CardContent>
        </Card>
      ) : null}

      {error && !loading ? (
        <Card>
          <CardContent className="pt-6">
            <ErrorState
              message={
                error.status === 403
                  ? "You do not have permission to view this employee's employment."
                  : error.message
              }
              onRetry={() => void load()}
            />
          </CardContent>
        </Card>
      ) : null}

      {!loading && !error && employments ? (
        <>
          <Card>
            <CardContent className="pt-6">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <h3 className="text-sm font-medium text-foreground">Current employment</h3>
                <div className="flex gap-2">
                  {canCreate && (!employments.length || isRehire) ? (
                    <Button type="button" size="sm" onClick={openHire}>
                      {isRehire ? "Rehire" : "Create first employment"}
                    </Button>
                  ) : null}
                  {canUpdate && current ? (
                    <Button type="button" size="sm" variant="outline" onClick={openEdit}>
                      Edit
                    </Button>
                  ) : null}
                  {canTerminate && current ? (
                    <Button type="button" size="sm" variant="destructive" onClick={openTerminate}>
                      Terminate
                    </Button>
                  ) : null}
                </div>
              </div>

              {current ? (
                <dl className="mt-4 grid grid-cols-1 gap-4 sm:grid-cols-2">
                  <div>
                    <dt className="text-xs font-medium uppercase tracking-wide text-foreground-muted">
                      Company
                    </dt>
                    <dd className="mt-0.5 text-sm text-foreground">{legalEntityName(current.legal_entity_id)}</dd>
                  </div>
                  <div>
                    <dt className="text-xs font-medium uppercase tracking-wide text-foreground-muted">
                      Joining date
                    </dt>
                    <dd className="mt-0.5 text-sm text-foreground">
                      <CompanyDate value={current.joining_date} />
                    </dd>
                  </div>
                  <div>
                    <dt className="text-xs font-medium uppercase tracking-wide text-foreground-muted">
                      Probation end date
                    </dt>
                    <dd className="mt-0.5 text-sm text-foreground">
                      {current.probation_end_date ? (
                        <CompanyDate value={current.probation_end_date} />
                      ) : (
                        "Not configured"
                      )}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-xs font-medium uppercase tracking-wide text-foreground-muted">
                      Pay basis
                    </dt>
                    <dd className="mt-0.5 text-sm text-foreground">{PAY_BASIS_LABELS[current.pay_basis]}</dd>
                  </div>
                  <div>
                    <dt className="text-xs font-medium uppercase tracking-wide text-foreground-muted">Status</dt>
                    <dd className="mt-0.5 text-sm">
                      <Badge variant="success">Active</Badge>
                    </dd>
                  </div>
                </dl>
              ) : (
                <EmptyState
                  className="mt-4"
                  title={isRehire ? "This employee is not currently employed." : "No employment on record yet."}
                  description={
                    isRehire
                      ? "Their previous employment episode has ended. Rehire them to start a new one."
                      : "Create the first employment episode to record when this employee joined."
                  }
                />
              )}
            </CardContent>
          </Card>

          {history.length > 0 ? (
            <Card>
              <CardContent className="pt-6">
                <h3 className="text-sm font-medium text-foreground">Employment history</h3>
                <ul className="mt-3 divide-y divide-border">
                  {[...history]
                    .sort((a, b) => b.joining_date.localeCompare(a.joining_date))
                    .map((item) => (
                      <li key={item.id} className="flex items-center justify-between gap-4 py-3 first:pt-0 last:pb-0">
                        <div>
                          <p className="text-sm font-medium text-foreground">{legalEntityName(item.legal_entity_id)}</p>
                          <p className="mt-0.5 text-xs text-foreground-muted">
                            <CompanyDate value={item.joining_date} /> –{" "}
                            {item.last_working_day ? (
                              <CompanyDate value={item.last_working_day} />
                            ) : (
                              "—"
                            )}
                          </p>
                        </div>
                        <Badge variant="outline">Terminated</Badge>
                      </li>
                    ))}
                </ul>
              </CardContent>
            </Card>
          ) : null}
        </>
      ) : null}

      <Dialog open={hireOpen} onOpenChange={(open) => (!hiring ? setHireOpen(open) : null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{isRehire ? "Rehire employee" : "Create first employment"}</DialogTitle>
          </DialogHeader>
          {isRehire ? (
            <p className="text-sm text-foreground-muted">
              The employee&apos;s identity and history are retained — this starts a new employment episode.
            </p>
          ) : null}
          <div className="grid grid-cols-1 gap-4">
            <FormField id="hire-legal-entity" label="Company" required error={hireErrors.legalEntityId}>
              <NativeSelect
                value={hireValues.legalEntityId}
                onChange={(e) => setHireValues({ ...hireValues, legalEntityId: e.target.value })}
              >
                <option value="">Select a company</option>
                {legalEntities.map((entity) => (
                  <option key={entity.id} value={entity.id}>
                    {entity.name}
                  </option>
                ))}
              </NativeSelect>
            </FormField>
            <FormField id="hire-joining-date" label="Joining date" required error={hireErrors.joiningDate}>
              <Input
                type="date"
                value={hireValues.joiningDate}
                onChange={(e) => setHireValues({ ...hireValues, joiningDate: e.target.value })}
              />
            </FormField>
            <FormField
              id="hire-pay-basis"
              label="Pay basis"
              required
              description={PAY_BASIS_DESCRIPTIONS[hireValues.payBasis]}
            >
              <NativeSelect
                value={hireValues.payBasis}
                onChange={(e) => setHireValues({ ...hireValues, payBasis: e.target.value as PayBasis })}
              >
                {PAY_BASIS_VALUES.map((value) => (
                  <option key={value} value={value}>
                    {PAY_BASIS_LABELS[value]}
                  </option>
                ))}
              </NativeSelect>
            </FormField>
            <FormField
              id="hire-probation-end-date"
              label="Probation end date"
              description="Optional — purely informational, doesn't gate anything."
              error={hireErrors.probationEndDate}
            >
              <Input
                type="date"
                value={hireValues.probationEndDate}
                onChange={(e) => setHireValues({ ...hireValues, probationEndDate: e.target.value })}
              />
            </FormField>
          </div>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => setHireOpen(false)} disabled={hiring}>
              Cancel
            </Button>
            <Button type="button" onClick={() => void handleHire()} disabled={hiring}>
              {hiring ? "Saving…" : isRehire ? "Rehire" : "Create employment"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={editOpen} onOpenChange={(open) => (!editing ? setEditOpen(open) : null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Edit employment</DialogTitle>
          </DialogHeader>
          <p className="text-sm text-foreground-muted">
            Joining date is a historical fact and can&apos;t be changed here. Company, probation end date and
            pay basis are correctable.
          </p>
          <div className="grid grid-cols-1 gap-4">
            <FormField id="edit-legal-entity" label="Company" required error={editErrors.legalEntityId}>
              <NativeSelect
                value={editValues.legalEntityId}
                onChange={(e) => setEditValues({ ...editValues, legalEntityId: e.target.value })}
              >
                <option value="">Select a company</option>
                {legalEntities.map((entity) => (
                  <option key={entity.id} value={entity.id}>
                    {entity.name}
                  </option>
                ))}
              </NativeSelect>
            </FormField>
            <FormField
              id="edit-pay-basis"
              label="Pay basis"
              required
              description={PAY_BASIS_DESCRIPTIONS[editValues.payBasis]}
            >
              <NativeSelect
                value={editValues.payBasis}
                onChange={(e) => setEditValues({ ...editValues, payBasis: e.target.value as PayBasis })}
              >
                {PAY_BASIS_VALUES.map((value) => (
                  <option key={value} value={value}>
                    {PAY_BASIS_LABELS[value]}
                  </option>
                ))}
              </NativeSelect>
            </FormField>
            <FormField
              id="edit-probation-end-date"
              label="Probation end date"
              description="Optional — purely informational, doesn't gate anything."
              error={editErrors.probationEndDate}
            >
              <Input
                type="date"
                value={editValues.probationEndDate}
                onChange={(e) => setEditValues({ ...editValues, probationEndDate: e.target.value })}
              />
            </FormField>
          </div>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => setEditOpen(false)} disabled={editing}>
              Cancel
            </Button>
            <Button type="button" onClick={() => void handleEdit()} disabled={editing}>
              {editing ? "Saving…" : "Save changes"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={terminateOpen} onOpenChange={(open) => (!terminating ? setTerminateOpen(open) : null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Terminate employment</DialogTitle>
          </DialogHeader>
          <p className="text-sm text-foreground-muted">
            This ends the employee&apos;s current employment episode. This action cannot be reversed — a new
            employment episode (rehire) can be created later if they return.
          </p>
          <FormField id="terminate-lwd" label="Last working day" required error={terminateErrors.lastWorkingDay}>
            <Input
              type="date"
              value={terminateValues.lastWorkingDay}
              onChange={(e) => setTerminateValues({ lastWorkingDay: e.target.value })}
            />
          </FormField>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => setTerminateOpen(false)} disabled={terminating}>
              Cancel
            </Button>
            <Button type="button" variant="destructive" onClick={() => void handleTerminate()} disabled={terminating}>
              {terminating ? "Terminating…" : "Terminate employment"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
