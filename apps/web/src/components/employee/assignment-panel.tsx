"use client";

import { useCallback, useEffect, useState } from "react";

import { AssignmentChangeDialog } from "@/components/employee/assignment-change-dialog";
import { EffectiveDateBadge } from "@/components/employee/effective-date-badge";
import { CompanyDate } from "@/components/common/company-date";
import { EmptyState } from "@/components/common/empty-state";
import { ErrorState } from "@/components/common/error-state";
import { LoadingState } from "@/components/common/loading-state";
import { useToast } from "@/components/common/toast";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { apiClient } from "@/lib/api/client";
import { useEmployeeDirectory } from "@/lib/employee/use-employee-directory";
import { useEmployeeNames } from "@/lib/employee/use-employee-names";
import { ApiError, describeApiError } from "@/lib/api/errors";
import { usePermissions } from "@/lib/auth/use-permissions";
import type { Branch } from "@/lib/branch/types";
import type { Department } from "@/lib/department/types";
import type { Designation } from "@/lib/designation/types";
import type { Assignment, AssignmentChangeType } from "@/lib/employee/types";
import { CHANGE_TYPE_LABELS } from "@/lib/employee/validate-assignment";
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
    setCreateOpen(true);
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
                  : describeApiError(error)
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

      <AssignmentChangeDialog
        employeeId={employeeId}
        open={createOpen}
        onOpenChange={setCreateOpen}
        onSaved={() => void load()}
      />
    </div>
  );
}
