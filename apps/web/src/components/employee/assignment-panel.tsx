"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { AssignmentForm } from "@/components/employee/assignment-form";
import { ManagerChangeImpactDialog } from "@/components/employee/manager-change-impact-dialog";
import { ConcurrencyConflictBanner } from "@/components/employee/concurrency-conflict-banner";
import { EffectiveDateBadge } from "@/components/employee/effective-date-badge";
import { CompanyDate } from "@/components/common/company-date";
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
import { useEmployeeDirectory } from "@/lib/employee/use-employee-directory";
import { useEmployeeNames } from "@/lib/employee/use-employee-names";
import { ApiError, describeLifecycleError, getFieldError } from "@/lib/api/errors";
import { usePermissions } from "@/lib/auth/use-permissions";
import type { Branch } from "@/lib/branch/types";
import type { Department } from "@/lib/department/types";
import type { Designation } from "@/lib/designation/types";
import type {
  Assignment,
  AssignmentChangeType,
  Employee,
  ManagerChangeImpact,
} from "@/lib/employee/types";
import {
  buildAssignmentCreatePayload,
  emptyAssignmentFormValues,
  validateAssignmentForm,
  CHANGE_TYPE_LABELS,
  type AssignmentFormErrors,
  type AssignmentFormValues,
} from "@/lib/employee/validate-assignment";
import type { Grade } from "@/lib/grade/types";
import type { Shift } from "@/lib/shift/types";

interface AssignmentPanelProps {
  employeeId: string;
}

interface ReferenceData {
  branches: Branch[];
  departments: Department[];
  designations: Designation[];
  grades: Grade[];
  shifts: Shift[];
}

export function AssignmentPanel({ employeeId }: AssignmentPanelProps) {
  const { toast } = useToast();
  const { can } = usePermissions();

  const [assignments, setAssignments] = useState<Assignment[] | null>(null);
  const [refs, setRefs] = useState<ReferenceData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<ApiError | null>(null);

  const [createOpen, setCreateOpen] = useState(false);
  const directory = useEmployeeDirectory({ enabled: createOpen });
  const [values, setValues] = useState<AssignmentFormValues>(emptyAssignmentFormValues());
  const [errors, setErrors] = useState<AssignmentFormErrors>({});
  const [saving, setSaving] = useState(false);
  const [staleMessage, setStaleMessage] = useState<string | null>(null);
  const [impactReview, setImpactReview] = useState<{ impact: ManagerChangeImpact; stale: boolean } | null>(null);
  const submittingRef = useRef(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [assignmentData, branches, departments, designations, grades, shifts] = await Promise.all([
        apiClient.get<Assignment[]>(`/employees/${employeeId}/assignments`),
        apiClient.get<Branch[]>("/branches").catch(() => []),
        apiClient.get<Department[]>("/departments").catch(() => []),
        apiClient.get<Designation[]>("/designations").catch(() => []),
        apiClient.get<Grade[]>("/grades").catch(() => []),
        apiClient.get<Shift[]>("/shifts").catch(() => []),
      ]);

      setAssignments(assignmentData);
      setRefs({ branches, departments, designations, grades, shifts });
    } catch (err) {
      setAssignments(null);
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

  const current = assignments?.find((item) => item.effective_to === null) ?? null;
  const history = assignments?.filter((item) => item.effective_to !== null) ?? [];

  function nameIn<T extends { id: string; name?: string; title?: string }>(
    list: T[] | undefined,
    id: string | null,
  ): string {
    if (!id) return "—";
    const item = list?.find((entry) => entry.id === id);
    return item?.name ?? item?.title ?? "Unknown";
  }

  const managerIds = (assignments ?? [])
    .map((item) => item.reporting_manager_id)
    .filter((id): id is string => Boolean(id));
  const employeeName = useEmployeeNames(managerIds, directory.employees);

  function managerName(id: string | null): string {
    if (!id) return "—";
    return employeeName(id);
  }

  const canTransfer = can("EMPLOYEE.TRANSFER");
  const canPromote = can("EMPLOYEE.PROMOTE");
  const allowedChangeTypes: AssignmentChangeType[] = [
    ...(canTransfer ? (["INITIAL", "TRANSFER", "MANAGER_CHANGE", "SHIFT_CHANGE"] as AssignmentChangeType[]) : []),
    ...(canPromote ? (["PROMOTION"] as AssignmentChangeType[]) : []),
  ];

  function openCreate() {
    setValues(emptyAssignmentFormValues(current ? "" : "INITIAL"));
    setErrors({});
    setStaleMessage(null);
    setCreateOpen(true);
  }

  /** Save button: when a reporting-manager change is really being attempted, preview its impact
   * first and only post straight away when nothing pending is affected. */
  async function handleCreate() {
    if (submittingRef.current) return;
    const clientErrors = validateAssignmentForm(values, Boolean(current));
    if (Object.keys(clientErrors).length > 0) {
      setErrors(clientErrors);
      return;
    }

    const changingManager =
      current !== null && values.reportingManagerId !== "" && values.reportingManagerId !== current.reporting_manager_id;
    if (!changingManager) {
      await submitChange();
      return;
    }

    submittingRef.current = true;
    setSaving(true);
    setErrors({});
    setStaleMessage(null);
    try {
      const query = new URLSearchParams({
        reporting_manager_id: values.reportingManagerId,
        effective_from: values.effectiveFrom,
      });
      const impact = await apiClient.get<ManagerChangeImpact>(
        `/employees/${employeeId}/manager-change-impact?${query.toString()}`,
      );
      if (impact.requires_confirmation) {
        setImpactReview({ impact, stale: false });
        return;
      }
    } catch (err) {
      toast({ title: "Could not check pending requests", description: describeLifecycleError(err), variant: "danger" });
      return;
    } finally {
      submittingRef.current = false;
      setSaving(false);
    }
    await submitChange();
  }

  async function confirmManagerChange() {
    if (!impactReview) return;
    await submitChange(impactReview.impact.impact_token);
  }

  async function submitChange(impactToken?: string) {
    if (submittingRef.current) return;
    submittingRef.current = true;
    setSaving(true);
    setErrors({});
    setStaleMessage(null);
    try {
      await apiClient.post<Assignment>(
        `/employees/${employeeId}/assignments`,
        buildAssignmentCreatePayload(values, impactToken),
        current ? { ifMatch: String(current.version) } : undefined,
      );
      setImpactReview(null);
      setCreateOpen(false);
      toast({ title: "Assignment change saved", variant: "success" });
      await load();
    } catch (err) {
      if (err instanceof ApiError) {
        if (err.status === 409 && err.code === "MANAGER_CHANGE_REQUIRES_CONFIRMATION") {
          // Pending requests appeared or changed since the user last saw the figures. Show the
          // new ones and make them confirm again - the old token is never reused.
          const context = err.details.find((d) => d.code === "MANAGER_CHANGE_REQUIRES_CONFIRMATION")
            ?.context as { impact?: Omit<ManagerChangeImpact, "requires_confirmation" | "impact_token">; impact_token?: string } | undefined;
          if (context?.impact && context.impact_token) {
            setImpactReview({
              impact: { ...context.impact, requires_confirmation: true, impact_token: context.impact_token },
              stale: impactToken !== undefined,
            });
            return;
          }
        }
        if (err.status === 409 && err.code === "STALE_RESOURCE") {
          setImpactReview(null);
          setStaleMessage("The current assignment was changed by someone else since you opened this form.");
          return;
        }
        if (err.status === 409 && err.code === "NO_ACTIVE_EMPLOYMENT") {
          setImpactReview(null);
          toast({
            title: "Could not save assignment",
            description: "This employee has no active employment episode covering this date.",
            variant: "danger",
          });
          return;
        }
        if (err.status === 409 && err.code === "ASSIGNMENT_DATES_OVERLAP") {
          setImpactReview(null);
          toast({
            title: "Could not save assignment",
            description: "This effective date overlaps an existing assignment row.",
            variant: "danger",
          });
          return;
        }
        if (err.status === 422) {
          setImpactReview(null);
          setErrors({
            effectiveFrom: getFieldError(err.details, "effective_from"),
            changeType: getFieldError(err.details, "change_type"),
            shiftId: getFieldError(err.details, "shift_id"),
            branchId: getFieldError(err.details, "branch_id"),
            departmentId: getFieldError(err.details, "department_id"),
            designationId: getFieldError(err.details, "designation_id"),
            gradeId: getFieldError(err.details, "grade_id"),
            reportingManagerId: getFieldError(err.details, "reporting_manager_id"),
          });
          toast({ title: "Could not save assignment", description: describeLifecycleError(err), variant: "danger" });
          return;
        }
        if (err.status === 403) {
          setImpactReview(null);
          setCreateOpen(false);
          toast({ title: "You don't have permission to do that", variant: "danger" });
          return;
        }
      }
      setImpactReview(null);
      toast({ title: "Could not save assignment", description: describeLifecycleError(err), variant: "danger" });
    } finally {
      submittingRef.current = false;
      setSaving(false);
    }
  }

  return (
    <div className="space-y-6">
      {loading ? (
        <Card>
          <CardContent className="pt-6">
            <LoadingState label="Loading assignment history…" />
          </CardContent>
        </Card>
      ) : null}

      {error && !loading ? (
        <Card>
          <CardContent className="pt-6">
            <ErrorState
              message={
                error.status === 403
                  ? "You do not have permission to view this employee's assignment."
                  : error.message
              }
              onRetry={() => void load()}
            />
          </CardContent>
        </Card>
      ) : null}

      {!loading && !error && assignments ? (
        <>
          <Card>
            <CardContent className="pt-6">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <h3 className="text-sm font-medium text-foreground">Current assignment</h3>
                {allowedChangeTypes.length > 0 ? (
                  <Button type="button" size="sm" onClick={openCreate}>
                    Record a change
                  </Button>
                ) : null}
              </div>

              {current ? (
                <dl className="mt-4 grid grid-cols-1 gap-4 sm:grid-cols-2">
                  <div>
                    <dt className="text-xs font-medium uppercase tracking-wide text-foreground-muted">Branch</dt>
                    <dd className="mt-0.5 text-sm text-foreground">{nameIn(refs?.branches, current.branch_id)}</dd>
                  </div>
                  <div>
                    <dt className="text-xs font-medium uppercase tracking-wide text-foreground-muted">Department</dt>
                    <dd className="mt-0.5 text-sm text-foreground">{nameIn(refs?.departments, current.department_id)}</dd>
                  </div>
                  <div>
                    <dt className="text-xs font-medium uppercase tracking-wide text-foreground-muted">Designation</dt>
                    <dd className="mt-0.5 text-sm text-foreground">{nameIn(refs?.designations, current.designation_id)}</dd>
                  </div>
                  <div>
                    <dt className="text-xs font-medium uppercase tracking-wide text-foreground-muted">Grade</dt>
                    <dd className="mt-0.5 text-sm text-foreground">{nameIn(refs?.grades, current.grade_id)}</dd>
                  </div>
                  <div>
                    <dt className="text-xs font-medium uppercase tracking-wide text-foreground-muted">
                      Reporting manager
                    </dt>
                    <dd className="mt-0.5 text-sm text-foreground">{managerName(current.reporting_manager_id)}</dd>
                  </div>
                  <div>
                    <dt className="text-xs font-medium uppercase tracking-wide text-foreground-muted">Shift</dt>
                    <dd className="mt-0.5 text-sm text-foreground">{nameIn(refs?.shifts, current.shift_id)}</dd>
                  </div>
                  <div>
                    <dt className="text-xs font-medium uppercase tracking-wide text-foreground-muted">
                      Work location
                    </dt>
                    <dd className="mt-0.5 text-sm text-foreground">{current.work_location_type ?? "—"}</dd>
                  </div>
                  <div>
                    <dt className="text-xs font-medium uppercase tracking-wide text-foreground-muted">
                      Effective from
                    </dt>
                    <dd className="mt-0.5 text-sm text-foreground">
                      <CompanyDate value={current.effective_from} />
                    </dd>
                  </div>
                </dl>
              ) : (
                <EmptyState
                  className="mt-4"
                  title="No assignment on record yet."
                  description="Record this employee's first placement — branch, department, and designation are required."
                />
              )}
            </CardContent>
          </Card>

          {history.length > 0 ? (
            <Card>
              <CardContent className="pt-6">
                <h3 className="text-sm font-medium text-foreground">Assignment history</h3>
                <ul className="mt-3 divide-y divide-border">
                  {[...history]
                    .sort((a, b) => b.effective_from.localeCompare(a.effective_from))
                    .map((item) => (
                      <li key={item.id} className="py-3 first:pt-0 last:pb-0">
                        <div className="flex items-center justify-between gap-4">
                          <p className="text-sm font-medium text-foreground">
                            {item.change_type ? CHANGE_TYPE_LABELS[item.change_type as AssignmentChangeType] ?? item.change_type : "—"}
                          </p>
                          <EffectiveDateBadge effectiveTo={item.effective_to} />
                        </div>
                        <p className="mt-0.5 text-xs text-foreground-muted">
                          <CompanyDate value={item.effective_from} /> –{" "}
                          <CompanyDate value={item.effective_to} /> · {nameIn(refs?.departments, item.department_id)}
                          {" · "}
                          {nameIn(refs?.designations, item.designation_id)}
                        </p>
                        {item.change_reason ? (
                          <p className="mt-1 text-xs text-foreground-muted">{item.change_reason}</p>
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
            <DialogTitle>Record an assignment change</DialogTitle>
          </DialogHeader>
          {staleMessage ? (
            <ConcurrencyConflictBanner
              message={staleMessage}
              onReload={() => void load()}
              onCancel={() => setStaleMessage(null)}
            />
          ) : null}
          <div className="max-h-[60vh] overflow-y-auto pr-1">
            <AssignmentForm
              values={values}
              errors={errors}
              onChange={setValues}
              branches={refs?.branches ?? []}
              departments={refs?.departments ?? []}
              designations={refs?.designations ?? []}
              grades={refs?.grades ?? []}
              shifts={refs?.shifts ?? []}
              directory={directory}
              currentEmployeeId={employeeId}
              allowedChangeTypes={allowedChangeTypes}
              idPrefix="assignment-"
            />
          </div>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => setCreateOpen(false)} disabled={saving}>
              Cancel
            </Button>
            <Button type="button" onClick={() => void handleCreate()} disabled={saving}>
              {saving ? "Saving…" : "Save change"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <ManagerChangeImpactDialog
        open={impactReview !== null}
        impact={impactReview?.impact ?? null}
        stale={impactReview?.stale ?? false}
        submitting={saving}
        onCancel={() => setImpactReview(null)}
        onConfirm={() => void confirmManagerChange()}
      />
    </div>
  );
}
