"use client";

import { useEffect, useState } from "react";

import { ErrorState } from "@/components/common/error-state";
import { LoadingState } from "@/components/common/loading-state";
import { Card, CardContent } from "@/components/ui/card";
import { apiClient } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import type { Assignment, Employee, Employment } from "@/lib/employee/types";
import type { Branch } from "@/lib/branch/types";
import type { Department } from "@/lib/department/types";
import type { Designation } from "@/lib/designation/types";
import type { Shift } from "@/lib/shift/types";
import type { LegalEntity } from "@/lib/legal-entity/types";

function DetailField({ label, value }: { label: string; value: string | null | undefined }) {
  const display = value && value.trim() ? value : "Not configured";
  return (
    <div>
      <dt className="text-xs font-medium uppercase tracking-wide text-foreground-muted">{label}</dt>
      <dd className={`mt-0.5 text-sm ${value && value.trim() ? "text-foreground" : "text-foreground-muted"}`}>
        {display}
      </dd>
    </div>
  );
}

interface CurrentWorkData {
  employment: Employment | null;
  assignment: Assignment | null;
  branches: Branch[];
  departments: Department[];
  designations: Designation[];
  shifts: Shift[];
  legalEntities: LegalEntity[];
  manager: Employee | null;
}

export function EmployeeOverview({ employee }: { employee: Employee }) {
  const [data, setData] = useState<CurrentWorkData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<ApiError | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function load() {
      setLoading(true);
      setError(null);
      try {
        const [employments, assignments, branches, departments, designations, shifts, legalEntities] =
          await Promise.all([
            apiClient.get<Employment[]>(`/employees/${employee.id}/employments`),
            apiClient.get<Assignment[]>(`/employees/${employee.id}/assignments`),
            apiClient.get<Branch[]>("/branches").catch(() => []),
            apiClient.get<Department[]>("/departments").catch(() => []),
            apiClient.get<Designation[]>("/designations").catch(() => []),
            apiClient.get<Shift[]>("/shifts").catch(() => []),
            apiClient.get<LegalEntity[]>("/legal-entities").catch(() => []),
          ]);

        const currentEmployment = employments.find((item) => item.status === "ACTIVE") ?? null;
        const currentAssignment = assignments.find((item) => item.effective_to === null) ?? null;

        let manager: Employee | null = null;
        if (currentAssignment?.reporting_manager_id) {
          try {
            manager = await apiClient.get<Employee>(`/employees/${currentAssignment.reporting_manager_id}`);
          } catch {
            manager = null;
          }
        }

        if (!cancelled) {
          setData({
            employment: currentEmployment,
            assignment: currentAssignment,
            branches,
            departments,
            designations,
            shifts,
            legalEntities,
            manager,
          });
        }
      } catch (err) {
        if (!cancelled) {
          setError(
            err instanceof ApiError
              ? err
              : new ApiError({ status: 0, code: "UNKNOWN_ERROR", message: "Something went wrong." }),
          );
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    void load();
    return () => {
      cancelled = true;
    };
  }, [employee.id]);

  function nameOf<T extends { id: string; name?: string; title?: string }>(
    list: T[],
    id: string | null,
  ): string | null {
    if (!id) return null;
    const item = list.find((entry) => entry.id === id);
    if (!item) return "Unknown";
    return item.name ?? item.title ?? "Unknown";
  }

  function managerName(): string | null {
    if (!data?.manager) return null;
    return (
      data.manager.display_name?.trim() ||
      [data.manager.first_name, data.manager.last_name].filter(Boolean).join(" ") ||
      data.manager.employee_code
    );
  }

  return (
    <div className="space-y-6">
      <Card>
        <CardContent className="space-y-6 pt-6">
          <section>
            <h3 className="text-sm font-medium text-foreground">Identity</h3>
            <dl className="mt-3 grid grid-cols-1 gap-4 sm:grid-cols-2">
              <DetailField label="Employee code" value={employee.employee_code} />
              <DetailField
                label="Name"
                value={
                  employee.display_name?.trim() ||
                  [employee.first_name, employee.middle_name, employee.last_name].filter(Boolean).join(" ")
                }
              />
              <DetailField label="Date of birth" value={employee.date_of_birth} />
              <DetailField label="Gender" value={employee.gender} />
              <DetailField label="Marital status" value={employee.marital_status} />
              <DetailField label="Blood group" value={employee.blood_group} />
              <DetailField label="Nationality" value={employee.nationality} />
            </dl>
          </section>
          <section>
            <h3 className="text-sm font-medium text-foreground">Personal contact</h3>
            <dl className="mt-3 grid grid-cols-1 gap-4 sm:grid-cols-2">
              <DetailField label="Personal email" value={employee.personal_email} />
              <DetailField label="Personal mobile" value={employee.personal_mobile} />
            </dl>
          </section>
        </CardContent>
      </Card>

      <Card>
        <CardContent className="pt-6">
          <h3 className="text-sm font-medium text-foreground">Current work information</h3>

          {loading ? <LoadingState label="Loading work information…" /> : null}
          {error && !loading ? (
            <ErrorState
              message={
                error.status === 403
                  ? "You do not have permission to view this employee's work information."
                  : error.message
              }
            />
          ) : null}

          {!loading && !error && data ? (
            <dl className="mt-3 grid grid-cols-1 gap-4 sm:grid-cols-2">
              <DetailField
                label="Employment status"
                value={data.employment ? data.employment.status : "No employment on record"}
              />
              <DetailField
                label="Company"
                value={
                  data.employment ? nameOf(data.legalEntities, data.employment.legal_entity_id) : null
                }
              />
              <DetailField
                label="Department"
                value={data.assignment ? nameOf(data.departments, data.assignment.department_id) : null}
              />
              <DetailField
                label="Designation"
                value={
                  data.assignment
                    ? (() => {
                        const designation = data.designations.find(
                          (item) => item.id === data.assignment?.designation_id,
                        );
                        return designation?.title ?? null;
                      })()
                    : null
                }
              />
              <DetailField
                label="Branch"
                value={data.assignment ? nameOf(data.branches, data.assignment.branch_id) : null}
              />
              <DetailField label="Reporting manager" value={managerName()} />
              <DetailField
                label="Shift"
                value={data.assignment ? nameOf(data.shifts, data.assignment.shift_id) : null}
              />
              <DetailField
                label="Work location"
                value={data.assignment ? data.assignment.work_location_type : null}
              />
            </dl>
          ) : null}

          {!loading && !error && data && !data.employment ? (
            <p className="mt-4 text-sm text-foreground-muted">
              This employee has no employment record yet — add one from the Employment tab.
            </p>
          ) : null}
        </CardContent>
      </Card>
    </div>
  );
}
