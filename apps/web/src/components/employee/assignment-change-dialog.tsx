"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { AssignmentForm } from "@/components/employee/assignment-form";
import { ConcurrencyConflictBanner } from "@/components/employee/concurrency-conflict-banner";
import { ManagerChangeImpactDialog } from "@/components/employee/manager-change-impact-dialog";
import { ErrorState } from "@/components/common/error-state";
import { LoadingState } from "@/components/common/loading-state";
import { useToast } from "@/components/common/toast";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { apiClient } from "@/lib/api/client";
import { ApiError, describeApiError, describeLifecycleError, getFieldError } from "@/lib/api/errors";
import { usePermissions } from "@/lib/auth/use-permissions";
import type { Branch } from "@/lib/branch/types";
import type { Department } from "@/lib/department/types";
import type { Designation } from "@/lib/designation/types";
import type { Assignment, AssignmentChangeType, ManagerChangeImpact } from "@/lib/employee/types";
import { useEmployeeDirectory } from "@/lib/employee/use-employee-directory";
import {
  buildAssignmentCreatePayload,
  emptyAssignmentFormValues,
  validateAssignmentForm,
  type AssignmentFormErrors,
  type AssignmentFormValues,
} from "@/lib/employee/validate-assignment";
import type { Grade } from "@/lib/grade/types";
import type { Shift } from "@/lib/shift/types";
import { reportedFallback } from "@/lib/observability/report-client-error";

interface ReferenceData {
  branches: Branch[];
  departments: Department[];
  designations: Designation[];
  grades: Grade[];
  shifts: Shift[];
}

interface AssignmentChangeDialogProps {
  employeeId: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Called after a change was saved, so the caller can refresh what it shows. */
  onSaved: () => void;
  /** Pre-selects the change type (for example `SHIFT_CHANGE` from the shift's edit button). It is
   * ignored when the user may not record that type, and for an employee with no assignment yet,
   * whose first placement is always `INITIAL`. */
  initialChangeType?: AssignmentChangeType | "";
}

/** Records a change to an employee's assignment (shift, branch, department, designation, grade,
 * reporting manager, work location), exactly as the Assignment section does, from wherever the
 * employee is shown. It loads the current assignment and the pick-lists itself each time it opens,
 * so what it saves is checked against the latest row. */
export function AssignmentChangeDialog({
  employeeId,
  open,
  onOpenChange,
  onSaved,
  initialChangeType = "",
}: AssignmentChangeDialogProps) {
  const { toast } = useToast();
  const { can } = usePermissions();

  const [assignments, setAssignments] = useState<Assignment[] | null>(null);
  const [refs, setRefs] = useState<ReferenceData | null>(null);
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState<ApiError | null>(null);

  const directory = useEmployeeDirectory({ enabled: open });
  const [values, setValues] = useState<AssignmentFormValues>(emptyAssignmentFormValues());
  const [errors, setErrors] = useState<AssignmentFormErrors>({});
  const [saving, setSaving] = useState(false);
  const [staleMessage, setStaleMessage] = useState<string | null>(null);
  const [impactReview, setImpactReview] = useState<{ impact: ManagerChangeImpact; stale: boolean } | null>(null);
  const submittingRef = useRef(false);

  const current = assignments?.find((item) => item.effective_to === null) ?? null;

  const canTransfer = can("EMPLOYEE.TRANSFER");
  const canPromote = can("EMPLOYEE.PROMOTE");
  const allowedChangeTypes: AssignmentChangeType[] = [
    ...(canTransfer ? (["INITIAL", "TRANSFER", "MANAGER_CHANGE", "SHIFT_CHANGE"] as AssignmentChangeType[]) : []),
    ...(canPromote ? (["PROMOTION"] as AssignmentChangeType[]) : []),
  ];

  /** Fetches the current assignment and the pick-lists. Returns the current row, if any. */
  const load = useCallback(async (): Promise<Assignment | null | undefined> => {
    setLoading(true);
    setLoadError(null);
    try {
      const [assignmentData, branches, departments, designations, grades, shifts] = await Promise.all([
        apiClient.get<Assignment[]>(`/employees/${employeeId}/assignments`),
        apiClient.get<Branch[]>("/branches").catch(reportedFallback([])),
        apiClient.get<Department[]>("/departments").catch(reportedFallback([])),
        apiClient.get<Designation[]>("/designations").catch(reportedFallback([])),
        apiClient.get<Grade[]>("/grades").catch(reportedFallback([])),
        apiClient.get<Shift[]>("/shifts").catch(reportedFallback([])),
      ]);
      setAssignments(assignmentData);
      setRefs({ branches, departments, designations, grades, shifts });
      return assignmentData.find((item) => item.effective_to === null) ?? null;
    } catch (err) {
      setAssignments(null);
      setLoadError(
        err instanceof ApiError
          ? err
          : new ApiError({ status: 0, code: "UNKNOWN_ERROR", message: "Something went wrong." }),
      );
      return undefined;
    } finally {
      setLoading(false);
    }
  }, [employeeId]);

  // Every time the dialog opens: start from a clean form for the latest assignment.
  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    setErrors({});
    setStaleMessage(null);
    setImpactReview(null);
    void load().then((row) => {
      if (cancelled || row === undefined) return;
      const preselect =
        row === null ? "INITIAL" : allowedChangeTypes.includes(initialChangeType as AssignmentChangeType) ? initialChangeType : "";
      setValues(emptyAssignmentFormValues(preselect));
    });
    return () => {
      cancelled = true;
    };
    // The allowed types derive from permissions that do not change while the dialog is open.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, load, initialChangeType]);

  /** Save button: when a reporting-manager change is really being attempted, preview its impact
   * first and only post straight away when nothing pending is affected. */
  async function handleSave() {
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
      onOpenChange(false);
      toast({ title: "Assignment change saved", variant: "success" });
      onSaved();
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
          onOpenChange(false);
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

  const ready = !loading && !loadError && assignments !== null && refs !== null;

  return (
    <>
      <Dialog open={open} onOpenChange={(next) => (!saving ? onOpenChange(next) : null)}>
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle>Record an assignment change</DialogTitle>
            <DialogDescription>
              Shift, branch, department, designation, grade, reporting manager and work location. Set only what
              changes; the rest carries forward from the effective date.
            </DialogDescription>
          </DialogHeader>
          {staleMessage ? (
            <ConcurrencyConflictBanner
              message={staleMessage}
              onReload={() => void load()}
              onCancel={() => setStaleMessage(null)}
            />
          ) : null}
          {loading ? <LoadingState label="Loading the current assignment…" /> : null}
          {loadError && !loading ? (
            <ErrorState
              message={
                loadError.status === 403
                  ? "You do not have permission to view or change this employee's assignment."
                  : describeApiError(loadError)
              }
              onRetry={() => void load()}
            />
          ) : null}
          {ready ? (
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
          ) : null}
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)} disabled={saving}>
              Cancel
            </Button>
            <Button type="button" onClick={() => void handleSave()} disabled={saving || !ready}>
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
    </>
  );
}
