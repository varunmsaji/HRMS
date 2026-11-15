"use client";

import { useCallback, useEffect, useState } from "react";

import { apiClient } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import type { Branch } from "@/lib/branch/types";
import type { Department } from "@/lib/department/types";
import type { Designation } from "@/lib/designation/types";
import { employeeFullName } from "@/lib/employee/names";
import type { Assignment, Employee, Employment } from "@/lib/employee/types";
import type { LegalEntity } from "@/lib/legal-entity/types";
import type { Shift } from "@/lib/shift/types";

/** The employee's current employment and assignment, with every id resolved to a display name.
 * Read by the profile header and the Overview tab, so the page fetches it once. */
export interface EmployeeWorkSummary {
  employment: Employment | null;
  assignment: Assignment | null;
  company: string | null;
  department: string | null;
  designation: string | null;
  branch: string | null;
  shift: string | null;
  manager: { id: string; name: string } | null;
}

function nameOf<T extends { id: string; name?: string; title?: string }>(
  list: T[],
  id: string | null | undefined,
): string | null {
  if (!id) return null;
  const item = list.find((entry) => entry.id === id);
  if (!item) return "Unknown";
  return item.name ?? item.title ?? "Unknown";
}

export function useEmployeeWorkSummary(employeeId: string | null) {
  const [data, setData] = useState<EmployeeWorkSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<ApiError | null>(null);
  const [nonce, setNonce] = useState(0);
  const reload = useCallback(() => setNonce((n) => n + 1), []);

  useEffect(() => {
    if (!employeeId) return;
    let cancelled = false;

    async function load(id: string) {
      setLoading(true);
      setError(null);
      try {
        const [employments, assignments, branches, departments, designations, shifts, legalEntities] =
          await Promise.all([
            apiClient.get<Employment[]>(`/employees/${id}/employments`),
            apiClient.get<Assignment[]>(`/employees/${id}/assignments`),
            apiClient.get<Branch[]>("/branches").catch(() => [] as Branch[]),
            apiClient.get<Department[]>("/departments").catch(() => [] as Department[]),
            apiClient.get<Designation[]>("/designations").catch(() => [] as Designation[]),
            apiClient.get<Shift[]>("/shifts").catch(() => [] as Shift[]),
            apiClient.get<LegalEntity[]>("/legal-entities").catch(() => [] as LegalEntity[]),
          ]);

        const employment = employments.find((item) => item.status === "ACTIVE") ?? null;
        const assignment = assignments.find((item) => item.effective_to === null) ?? null;

        let manager: EmployeeWorkSummary["manager"] = null;
        if (assignment?.reporting_manager_id) {
          try {
            const record = await apiClient.get<Employee>(`/employees/${assignment.reporting_manager_id}`);
            manager = { id: record.id, name: employeeFullName(record) || record.employee_code };
          } catch {
            manager = null;
          }
        }

        const designation = assignment
          ? (designations.find((item) => item.id === assignment.designation_id)?.title ?? null)
          : null;

        if (!cancelled) {
          setData({
            employment,
            assignment,
            company: employment ? nameOf(legalEntities, employment.legal_entity_id) : null,
            department: nameOf(departments, assignment?.department_id),
            designation,
            branch: nameOf(branches, assignment?.branch_id),
            shift: nameOf(shifts, assignment?.shift_id),
            manager,
          });
        }
      } catch (err) {
        if (!cancelled) {
          setData(null);
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

    void load(employeeId);
    return () => {
      cancelled = true;
    };
  }, [employeeId, nonce]);

  return { data, loading, error, reload };
}
