import { useState } from "react";

import { FormField } from "@/components/common/form-field";
import {
  ScopeTargetField,
  useCoverageRow,
} from "@/components/policy-assignment/scope-target";
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
import { formatCompanyDate } from "@/lib/dates/company-date";
import { useCompanyDatePattern } from "@/lib/dates/use-company-date";
import {
  SCOPE_TYPE_LABELS,
  SCOPE_TYPES,
  type PolicyKind,
  type ScopeType,
} from "@/lib/policy-assignment/types";
import { usePolicyFollowers } from "@/lib/policy-assignment/use-policy-followers";

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
  const [formError, setFormError] = useState<string | null>(null);

  const companyRow = useCoverageRow({
    policyKind,
    leaveTypeId,
    scopeType: "COMPANY",
    scopeId: null,
    today,
  });
  const followers = usePolicyFollowers({ policyKind, policyId, today });

  // A brand-new policy in a company with none of this kind almost always applies company-wide.
  // Publishing new rules for an existing policy leaves who follows it alone.
  const defaultWho: WhoValue = policyId || companyRow?.own ? "NOBODY" : "COMPANY";
  const who = chosenWho ?? defaultWho;

  const targetRow = useCoverageRow({
    policyKind,
    leaveTypeId,
    scopeType: who === "NOBODY" || who === "COMPANY" ? null : who,
    scopeId: targetId || null,
    today,
  });
  const row =
    who === "NOBODY" ? null : who === "COMPANY" ? (companyRow ?? null) : (targetRow ?? null);

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
        {who === "NOBODY" && policyId && followers.assignments ? (
          <p className="text-sm text-foreground-secondary">
            {followers.assignments.length === 0
              ? "Nobody follows it yet. You can add who follows it from the policy's Who follows this tab."
              : `Followed by: ${followers.assignments.map((a) => followers.scopeLabel(a)).join(", ")}.`}
          </p>
        ) : null}
        {who !== "NOBODY" ? (
          <ScopeTargetField
            idPrefix="publish"
            scopeType={who}
            value={targetId}
            onChange={setTargetId}
          />
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
