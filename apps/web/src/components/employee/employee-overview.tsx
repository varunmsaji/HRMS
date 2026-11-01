"use client";

import { useEffect, useState } from "react";

import { EmployeeSideCards } from "@/components/employee/employee-side-cards";
import { ErrorState } from "@/components/common/error-state";
import { formatCompanyDate } from "@/lib/dates/company-date";
import { useCompanyDatePattern } from "@/lib/dates/use-company-date";
import { LoadingState } from "@/components/common/loading-state";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { apiClient } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import type { Assignment, Employee, Employment } from "@/lib/employee/types";
import type { Branch } from "@/lib/branch/types";
import type { Department } from "@/lib/department/types";
import type { Designation } from "@/lib/designation/types";
import type { Shift } from "@/lib/shift/types";
import type { LegalEntity } from "@/lib/legal-entity/types";

function DetailField({
  label,
  value,
  mono = false,
}: {
  label: string;
  value: string | null | undefined;
  mono?: boolean;
}) {
  const hasValue = Boolean(value && value.trim());
  const display = hasValue ? value : "Not configured";
  return (
    <div className="py-1">
      <dt className="text-xs font-medium text-foreground-muted">{label}</dt>
      <dd
        className={`mt-0.5 text-sm ${
          hasValue ? "font-medium text-foreground" : "text-foreground-disabled"
        } ${mono && hasValue ? "font-mono" : ""}`}
      >
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
  const datePattern = useCompanyDatePattern();
  const [data, setData] = useState<CurrentWorkData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<ApiError | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function load() {
      setLoading(true);
      setError(null);
      try {
        const [
          employments,
          assignments,
          branches,
          departments,
          designations,
          shifts,
          legalEntities,
        ] = await Promise.all([
          apiClient.get<Employment[]>(`/employees/${employee.id}/employments`),
          apiClient.get<Assignment[]>(`/employees/${employee.id}/assignments`),
          apiClient.get<Branch[]>("/branches").catch(() => []),
          apiClient.get<Department[]>("/departments").catch(() => []),
          apiClient.get<Designation[]>("/designations").catch(() => []),
          apiClient.get<Shift[]>("/shifts").catch(() => []),
          apiClient.get<LegalEntity[]>("/legal-entities").catch(() => []),
        ]);

        const currentEmployment =
          employments.find((item) => item.status === "ACTIVE") ?? null;
        const currentAssignment =
          assignments.find((item) => item.effective_to === null) ?? null;

        let manager: Employee | null = null;
        if (currentAssignment?.reporting_manager_id) {
          try {
            manager = await apiClient.get<Employee>(
              `/employees/${currentAssignment.reporting_manager_id}`,
            );
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
              : new ApiError({
                  status: 0,
                  code: "UNKNOWN_ERROR",
                  message: "Something went wrong.",
                }),
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
    <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_22rem]">
    <div className="grid content-start gap-6 lg:grid-cols-2">
      <Card>
        <CardHeader>
          <CardTitle>Personal &amp; Contact Information</CardTitle>
        </CardHeader>
        <CardContent className="space-y-6">
          <section>
            <h3 className="text-xs font-semibold uppercase tracking-wider text-foreground-muted">
              Identity
            </h3>
            <dl className="mt-2.5 grid grid-cols-1 gap-x-6 gap-y-3 sm:grid-cols-2">
              <DetailField label="Employee code" value={employee.employee_code} mono />
              <DetailField
                label="Name"
                value={
                  employee.display_name?.trim() ||
                  [employee.first_name, employee.middle_name, employee.last_name]
                    .filter(Boolean)
                    .join(" ")
                }
              />
              <DetailField
                label="Date of birth"
                value={
                  employee.date_of_birth
                    ? formatCompanyDate(employee.date_of_birth, datePattern)
                    : null
                }
              />
              <DetailField label="Gender" value={employee.gender} />
              <DetailField label="Marital status" value={employee.marital_status} />
              <DetailField label="Blood group" value={employee.blood_group} />
              <DetailField label="Nationality" value={employee.nationality} />
            </dl>
          </section>

          <section className="border-t border-border pt-5">
            <h3 className="text-xs font-semibold uppercase tracking-wider text-foreground-muted">
              Personal contact
            </h3>
            <dl className="mt-2.5 grid grid-cols-1 gap-x-6 gap-y-3 sm:grid-cols-2">
              <DetailField label="Personal email" value={employee.personal_email} />
              <DetailField label="Personal mobile" value={employee.personal_mobile} />
            </dl>
          </section>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Current Work Information</CardTitle>
        </CardHeader>
        <CardContent>
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
            <>
              <dl className="grid grid-cols-1 gap-x-6 gap-y-3 sm:grid-cols-2">
                <DetailField
                  label="Employment status"
                  value={data.employment ? data.employment.status : "No employment on record"}
                />
                <DetailField
                  label="Company"
                  value={
                    data.employment
                      ? nameOf(data.legalEntities, data.employment.legal_entity_id)
                      : null
                  }
                />
                <DetailField
                  label="Department"
                  value={
                    data.assignment
                      ? nameOf(data.departments, data.assignment.department_id)
                      : null
                  }
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
                  value={
                    data.assignment ? nameOf(data.branches, data.assignment.branch_id) : null
                  }
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

              {!data.employment ? (
                <p className="mt-5 rounded-md border border-dashed border-border bg-surface-secondary/50 px-3.5 py-2.5 text-xs text-foreground-secondary">
                  This employee has no employment record yet — add one from the Employment tab.
                </p>
              ) : null}
            </>
          ) : null}
        </CardContent>
      </Card>
    </div>
    <EmployeeSideCards employeeId={employee.id} />
    </div>
  );
}
