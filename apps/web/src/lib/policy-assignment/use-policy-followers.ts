import { useCallback, useEffect, useMemo, useState } from "react";

import { apiClient } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import { employeeOptionName, type EmployeeOption } from "@/lib/employee/use-employee-directory";
import {
  SCOPE_TYPE_LABELS,
  SCOPE_TYPES,
  type PolicyAssignment,
  type PolicyKind,
  type ScopeType,
} from "@/lib/policy-assignment/types";

const SCOPE_NAME_PATH: Partial<Record<ScopeType, string>> = {
  LEGAL_ENTITY: "/legal-entities",
  BRANCH: "/branches",
  DEPARTMENT: "/departments",
  GRADE: "/grades",
  DESIGNATION: "/designations",
  SHIFT: "/shifts",
};

interface Named {
  id: string;
  name?: string;
  title?: string;
}

export interface PolicyFollowers {
  /** Assignments of this policy that apply today or start later, widest scope first. Null while
   * loading or after an error. */
  assignments: PolicyAssignment[] | null;
  error: ApiError | null;
  /** True when the policy has more assignments than one page holds; the list is then partial. */
  truncated: boolean;
  /** "Branch: Pune", "Whole company", "Employee: Asha Rao" */
  scopeLabel: (assignment: Pick<PolicyAssignment, "scope_type" | "scope_id">) => string;
  reload: () => void;
}

const PAGE_SIZE = 100;

/** Who follows one policy: its assignments that are in force today or scheduled to start. */
export function usePolicyFollowers({
  policyKind,
  policyId,
  today,
  enabled = true,
}: {
  policyKind: PolicyKind;
  policyId: string | null;
  today: string;
  enabled?: boolean;
}): PolicyFollowers {
  const [refresh, setRefresh] = useState(0);
  const key = enabled && policyId ? `${policyKind}:${policyId}:${today}:${refresh}` : null;
  const [result, setResult] = useState<{
    key: string;
    assignments: PolicyAssignment[] | null;
    truncated: boolean;
    error: ApiError | null;
  } | null>(null);
  const [names, setNames] = useState<Record<string, string>>({});

  useEffect(() => {
    if (!key || !policyId) return;
    let current = true;
    apiClient
      .getList<PolicyAssignment>("/policy-assignments", {
        policy_kind: policyKind,
        policy_id: policyId,
        per_page: PAGE_SIZE,
      })
      .then(({ data, pagination }) => {
        if (!current) return;
        const live = data
          .filter((a) => a.is_active && (a.effective_to === null || a.effective_to >= today))
          .sort(
            (a, b) =>
              SCOPE_TYPES.indexOf(a.scope_type) - SCOPE_TYPES.indexOf(b.scope_type) ||
              a.effective_from.localeCompare(b.effective_from),
          );
        setResult({
          key,
          assignments: live,
          truncated: (pagination?.total ?? 0) > data.length,
          error: null,
        });
      })
      .catch((err: unknown) => {
        if (!current) return;
        setResult({
          key,
          assignments: null,
          truncated: false,
          error:
            err instanceof ApiError
              ? err
              : new ApiError({ status: 0, code: "UNKNOWN_ERROR", message: "Something went wrong." }),
        });
      });
    return () => {
      current = false;
    };
  }, [key, policyKind, policyId, today]);

  const showing = result?.key === key ? result : null;
  const assignments = showing?.assignments ?? null;

  // Only look up the names this list needs.
  const wanted = useMemo(() => {
    const types = new Set<ScopeType>();
    const employeeIds = new Set<string>();
    for (const a of assignments ?? []) {
      if (a.scope_type === "EMPLOYEE" && a.scope_id) employeeIds.add(a.scope_id);
      else if (SCOPE_NAME_PATH[a.scope_type]) types.add(a.scope_type);
    }
    return { types: [...types].sort().join(","), employees: [...employeeIds].sort().join(",") };
  }, [assignments]);

  useEffect(() => {
    if (!wanted.types && !wanted.employees) return;
    let current = true;
    const lists = wanted.types
      ? wanted.types.split(",").map((type) =>
          apiClient
            .get<Named[]>(SCOPE_NAME_PATH[type as ScopeType] as string)
            .catch(() => [] as Named[]),
        )
      : [];
    const people = wanted.employees
      ? wanted.employees.split(",").map((id) =>
          apiClient
            .get<EmployeeOption>(`/employees/${id}`)
            .then((e): Named => ({ id, name: employeeOptionName(e) }))
            .catch((): Named => ({ id })),
        )
      : [];
    void Promise.all([Promise.all(lists), Promise.all(people)]).then(([scoped, employees]) => {
      if (!current) return;
      const found: Record<string, string> = {};
      for (const option of [...scoped.flat(), ...employees]) {
        const label = option.name ?? option.title;
        if (label) found[option.id] = label;
      }
      setNames((existing) => ({ ...existing, ...found }));
    });
    return () => {
      current = false;
    };
  }, [wanted]);

  const scopeLabel = useCallback(
    (a: Pick<PolicyAssignment, "scope_type" | "scope_id">) => {
      const label = SCOPE_TYPE_LABELS[a.scope_type];
      if (!a.scope_id) return label;
      return `${label}: ${names[a.scope_id] ?? "…"}`;
    },
    [names],
  );

  const reload = useCallback(() => setRefresh((n) => n + 1), []);

  return {
    assignments,
    error: showing?.error ?? null,
    truncated: showing?.truncated ?? false,
    scopeLabel,
    reload,
  };
}
