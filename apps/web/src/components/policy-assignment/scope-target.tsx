import { useEffect, useState } from "react";

import { FormField } from "@/components/common/form-field";
import { EmployeeSelect } from "@/components/employee/employee-select";
import { NativeSelect } from "@/components/ui/native-select";
import { apiClient } from "@/lib/api/client";
import { useEmployeeDirectory } from "@/lib/employee/use-employee-directory";
import {
  coveragePath,
  SCOPE_TYPE_LABELS,
  type PolicyCoverage,
  type PolicyCoverageRow,
  type PolicyKind,
  type ScopeType,
} from "@/lib/policy-assignment/types";

/** Where each named scope's records are listed. COMPANY and EMPLOYEE have no list here. */
export const SCOPE_LIST_PATH: Partial<Record<ScopeType, string>> = {
  LEGAL_ENTITY: "/legal-entities",
  BRANCH: "/branches",
  DEPARTMENT: "/departments",
  GRADE: "/grades",
  DESIGNATION: "/designations",
  SHIFT: "/shifts",
};

export interface NamedOption {
  id: string;
  name?: string;
  title?: string;
  is_active?: boolean;
}

export function optionLabel(option: NamedOption): string {
  return option.name ?? option.title ?? option.id;
}

/** The active records a scope type can point at, e.g. every active branch. */
export function useActiveScopeOptions(scopeType: ScopeType | null): NamedOption[] {
  const [result, setResult] = useState<{ scopeType: ScopeType; options: NamedOption[] } | null>(
    null,
  );
  const path = scopeType ? SCOPE_LIST_PATH[scopeType] : undefined;

  useEffect(() => {
    if (!path || !scopeType) return;
    let current = true;
    apiClient
      .get<NamedOption[]>(path)
      .then((list) => {
        if (current) {
          setResult({ scopeType, options: list.filter((option) => option.is_active !== false) });
        }
      })
      .catch(() => {
        if (current) setResult({ scopeType, options: [] });
      });
    return () => {
      current = false;
    };
  }, [path, scopeType]);

  return result && result.scopeType === scopeType ? result.options : [];
}

/** For one scope, the coverage row of one kind of policy: what is set there and what applies.
 * `undefined` while loading or before a target is chosen; `null` when nothing is set or inherited. */
export function useCoverageRow({
  policyKind,
  leaveTypeId,
  scopeType,
  scopeId,
  today,
}: {
  policyKind: PolicyKind;
  leaveTypeId: string | null;
  scopeType: ScopeType | null;
  scopeId: string | null;
  today: string;
}): PolicyCoverageRow | null | undefined {
  const ready = scopeType === "COMPANY" || (scopeType !== null && Boolean(scopeId));
  const key = ready ? `${scopeType}:${scopeType === "COMPANY" ? "" : scopeId}:${today}` : null;
  const [result, setResult] = useState<{ key: string; row: PolicyCoverageRow | null } | null>(null);

  useEffect(() => {
    if (!key || !scopeType) return;
    let current = true;
    apiClient
      .get<PolicyCoverage>(
        coveragePath(scopeType, scopeType === "COMPANY" ? null : scopeId, today),
      )
      .then((coverage) => {
        const row =
          coverage.rows.find(
            (r) => r.policy_kind === policyKind && r.leave_type_id === leaveTypeId,
          ) ?? null;
        if (current) setResult({ key, row });
      })
      .catch(() => {
        if (current) setResult({ key, row: null });
      });
    return () => {
      current = false;
    };
    // `key` already captures scopeType, scopeId and today.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, policyKind, leaveTypeId]);

  if (!key) return undefined;
  return result?.key === key ? result.row : undefined;
}

/** The "which branch / department / employee" field that follows a scope-type choice. Renders
 * nothing for the whole company. */
export function ScopeTargetField({
  idPrefix,
  scopeType,
  value,
  onChange,
}: {
  idPrefix: string;
  scopeType: ScopeType;
  value: string;
  onChange: (id: string) => void;
}) {
  const options = useActiveScopeOptions(scopeType === "COMPANY" ? null : scopeType);
  const directory = useEmployeeDirectory({ enabled: scopeType === "EMPLOYEE" });

  if (scopeType === "COMPANY") return null;
  if (scopeType === "EMPLOYEE") {
    return (
      <FormField id={`${idPrefix}-employee`} label="Employee" required>
        <EmployeeSelect directory={directory} value={value} onChange={onChange} />
      </FormField>
    );
  }
  return (
    <FormField id={`${idPrefix}-target`} label={SCOPE_TYPE_LABELS[scopeType]} required>
      <NativeSelect value={value} onChange={(e) => onChange(e.target.value)}>
        <option value="">Choose…</option>
        {options.map((option) => (
          <option key={option.id} value={option.id}>
            {optionLabel(option)}
          </option>
        ))}
      </NativeSelect>
    </FormField>
  );
}
