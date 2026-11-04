import { useEffect, useMemo, useState } from "react";

import { FormField } from "@/components/common/form-field";
import { EmployeeSelect } from "@/components/employee/employee-select";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/native-select";
import { apiClient } from "@/lib/api/client";
import { formatCompanyDate } from "@/lib/dates/company-date";
import { useCompanyDatePattern } from "@/lib/dates/use-company-date";
import { useEmployeeDirectory } from "@/lib/employee/use-employee-directory";
import {
  coveragePath,
  SCOPE_TYPE_LABELS,
  SCOPE_TYPES,
  type PolicyCoverage,
  type PolicyCoverageRow,
  type PolicyKind,
  type ScopeType,
} from "@/lib/policy-assignment/types";

const SCOPE_LIST_PATH: Partial<Record<ScopeType, string>> = {
  LEGAL_ENTITY: "/legal-entities",
  BRANCH: "/branches",
  DEPARTMENT: "/departments",
  GRADE: "/grades",
  DESIGNATION: "/designations",
  SHIFT: "/shifts",
};

interface NamedOption {
  id: string;
  name?: string;
  title?: string;
  is_active?: boolean;
}

export interface PublishAssignment {
  scopeType: ScopeType;
  scopeId: string | null;
  expectedVersion: number | null;
}

export interface PublishChoice {
  effectiveFrom: string;
  reason: string;
  assign: PublishAssignment | null;
}

type WhoValue = ScopeType | "NOBODY";

/** The last step of making a policy live: when it starts, and who follows it. Mount only while
 * open, so each opening starts from the current state. */
export function PublishAssignDialog({
  policyKind,
  leaveTypeId = null,
  policyId = null,
  today,
  initialDate,
  notBefore,
  saving,
  error,
  onCancel,
  onConfirm,
}: {
  policyKind: PolicyKind;
  leaveTypeId?: string | null;
  /** The policy being published, when it already exists. */
  policyId?: string | null;
  today: string;
  initialDate: string;
  /** The date must be after this one: the start of the version it replaces. */
  notBefore: string | null;
  saving: boolean;
  error: string | null;
  onCancel: () => void;
  onConfirm: (choice: PublishChoice) => void;
}) {
  const datePattern = useCompanyDatePattern();
  const [effectiveFrom, setEffectiveFrom] = useState(initialDate);
  const [reason, setReason] = useState("");
  // Until the user chooses, the default follows what the company already has.
  const [chosenWho, setChosenWho] = useState<WhoValue | null>(null);
  const [targetId, setTargetId] = useState("");
  const [companyRow, setCompanyRow] = useState<PolicyCoverageRow | null | undefined>(undefined);
  const [targetRow, setTargetRow] = useState<{ key: string; row: PolicyCoverageRow | null } | null>(
    null,
  );
  const [scopeOptions, setScopeOptions] = useState<NamedOption[]>([]);
  const [formError, setFormError] = useState<string | null>(null);

  function matching(coverage: PolicyCoverage): PolicyCoverageRow | null {
    return (
      coverage.rows.find(
        (row) => row.policy_kind === policyKind && row.leave_type_id === leaveTypeId,
      ) ?? null
    );
  }

  useEffect(() => {
    let current = true;
    apiClient
      .get<PolicyCoverage>(coveragePath("COMPANY", null, today))
      .then((coverage) => {
        if (current) setCompanyRow(matching(coverage));
      })
      .catch(() => {
        if (current) setCompanyRow(null);
      });
    return () => {
      current = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [today]);

  // A brand-new policy in a company with none of this kind almost always applies company-wide.
  // Publishing new rules for an existing policy leaves who follows it alone.
  const defaultWho: WhoValue = policyId || companyRow?.own ? "NOBODY" : "COMPANY";
  const who = chosenWho ?? defaultWho;
  const directory = useEmployeeDirectory({ enabled: who === "EMPLOYEE" });

  useEffect(() => {
    const path = who === "NOBODY" ? undefined : SCOPE_LIST_PATH[who];
    if (!path) return;
    let current = true;
    apiClient
      .get<NamedOption[]>(path)
      .then((list) => {
        if (current) setScopeOptions(list.filter((option) => option.is_active !== false));
      })
      .catch(() => {
        if (current) setScopeOptions([]);
      });
    return () => {
      current = false;
    };
  }, [who]);

  const targetKey = who !== "NOBODY" && who !== "COMPANY" && targetId ? `${who}:${targetId}` : null;

  useEffect(() => {
    if (!targetKey || who === "NOBODY") return;
    let current = true;
    apiClient
      .get<PolicyCoverage>(coveragePath(who, targetId, today))
      .then((coverage) => {
        if (current) setTargetRow({ key: targetKey, row: matching(coverage) });
      })
      .catch(() => {
        if (current) setTargetRow({ key: targetKey, row: null });
      });
    return () => {
      current = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [targetKey, today]);

  const row = useMemo(() => {
    if (who === "NOBODY") return null;
    if (who === "COMPANY") return companyRow ?? null;
    return targetRow?.key === targetKey ? targetRow?.row : null;
  }, [who, companyRow, targetRow, targetKey]);

  const replacesSamePolicy = Boolean(policyId && row?.own?.policy_id === policyId);

  function handleConfirm() {
    if (!effectiveFrom) {
      setFormError("Effective from is required.");
      return;
    }
    if (notBefore && effectiveFrom <= notBefore) {
      setFormError(
        `Must be after ${formatCompanyDate(notBefore, datePattern)}, when the current rules started.`,
      );
      return;
    }
    if (who !== "NOBODY" && who !== "COMPANY" && !targetId) {
      setFormError(`Choose the ${SCOPE_TYPE_LABELS[who].toLowerCase()} this applies to.`);
      return;
    }
    if (row?.own && !replacesSamePolicy && effectiveFrom <= row.own.effective_from) {
      setFormError(
        `Must be after ${formatCompanyDate(row.own.effective_from, datePattern)}, when their current assignment started.`,
      );
      return;
    }
    setFormError(null);
    onConfirm({
      effectiveFrom,
      reason: reason.trim(),
      assign:
        who === "NOBODY" || replacesSamePolicy
          ? null
          : {
              scopeType: who,
              scopeId: who === "COMPANY" ? null : targetId,
              expectedVersion: row?.own?.version ?? null,
            },
    });
  }

  const shown = formError ?? error;

  return (
    <Dialog open onOpenChange={(open) => (!open && !saving ? onCancel() : null)}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Publish</DialogTitle>
          <DialogDescription>
            Published rules can&apos;t be edited, and past days keep the rules they had. To change
            them later, publish again with a new date.
          </DialogDescription>
        </DialogHeader>
        <FormField id="publish-effective-from" label="Rules start on" required>
          <Input
            type="date"
            value={effectiveFrom}
            onChange={(e) => setEffectiveFrom(e.target.value)}
          />
        </FormField>
        {effectiveFrom && effectiveFrom < today ? (
          <p className="text-sm text-warning">This starts in the past.</p>
        ) : null}
        <FormField id="publish-who" label="Who follows this policy?" required>
          <NativeSelect
            value={who}
            onChange={(e) => {
              setChosenWho(e.target.value as WhoValue);
              setTargetId("");
              setFormError(null);
            }}
          >
            <option value="NOBODY">
              {policyId ? "No change to who follows it" : "Nobody yet, I'll assign it later"}
            </option>
            {SCOPE_TYPES.map((scope) => (
              <option key={scope} value={scope}>
                {SCOPE_TYPE_LABELS[scope]}
              </option>
            ))}
          </NativeSelect>
        </FormField>
        {who === "EMPLOYEE" ? (
          <FormField id="publish-employee" label="Employee" required>
            <EmployeeSelect directory={directory} value={targetId} onChange={setTargetId} />
          </FormField>
        ) : null}
        {who !== "NOBODY" && who !== "COMPANY" && who !== "EMPLOYEE" ? (
          <FormField id="publish-target" label={SCOPE_TYPE_LABELS[who]} required>
            <NativeSelect value={targetId} onChange={(e) => setTargetId(e.target.value)}>
              <option value="">Choose…</option>
              {scopeOptions.map((option) => (
                <option key={option.id} value={option.id}>
                  {option.name ?? option.title ?? option.id}
                </option>
              ))}
            </NativeSelect>
          </FormField>
        ) : null}
        {replacesSamePolicy ? (
          <p className="text-sm text-foreground-secondary">They already follow this policy.</p>
        ) : row?.own ? (
          <p className="text-sm text-foreground-secondary">
            Replaces {row.own.policy_name ?? "their current policy"} from this date.
          </p>
        ) : row?.applied ? (
          <p className="text-sm text-foreground-secondary">
            Overrides the inherited {row.applied.policy_name ?? "policy"} from this date.
          </p>
        ) : null}
        <FormField id="publish-reason" label="Reason (optional)">
          <Input value={reason} onChange={(e) => setReason(e.target.value)} />
        </FormField>
        {shown ? <p className="text-sm text-danger">{shown}</p> : null}
        <DialogFooter>
          <Button type="button" variant="outline" onClick={onCancel} disabled={saving}>
            Back
          </Button>
          <Button type="button" onClick={handleConfirm} disabled={saving}>
            {saving ? "Publishing…" : "Publish"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
