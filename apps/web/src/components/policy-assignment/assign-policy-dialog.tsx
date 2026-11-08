import { useState } from "react";

import { FormField } from "@/components/common/form-field";
import { useToast } from "@/components/common/toast";
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
import { ChangeImpactDialog } from "@/components/work-calendar/change-impact-dialog";
import { apiClient } from "@/lib/api/client";
import { describeApiError } from "@/lib/api/errors";
import { formatCompanyDate } from "@/lib/dates/company-date";
import { useCompanyDatePattern } from "@/lib/dates/use-company-date";
import {
  needsImpactPreview,
  SCOPE_TYPE_LABELS,
  SCOPE_TYPES,
  type PolicyKind,
  type ScopeType,
} from "@/lib/policy-assignment/types";
import type { ProposedChange } from "@/lib/work-calendar/change-impact";

/** Make one more group follow a policy, from the policy's own screen. Work calendars and
 * weekly-off patterns change day types, so for them this hands over to the impact preview.
 * Mount only while open, so each opening starts fresh. */
export function AssignPolicyDialog({
  policyKind,
  policyId,
  policyName,
  leaveTypeId = null,
  today,
  onClose,
  onAssigned,
}: {
  policyKind: PolicyKind;
  policyId: string;
  policyName: string;
  leaveTypeId?: string | null;
  today: string;
  onClose: () => void;
  onAssigned: () => void;
}) {
  const { toast } = useToast();
  const datePattern = useCompanyDatePattern();
  const [scopeType, setScopeType] = useState<ScopeType>("BRANCH");
  const [scopeId, setScopeId] = useState("");
  const [effectiveFrom, setEffectiveFrom] = useState(today);
  const [reason, setReason] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [impact, setImpact] = useState<ProposedChange | null>(null);

  const row = useCoverageRow({
    policyKind,
    leaveTypeId,
    scopeType,
    scopeId: scopeType === "COMPANY" ? null : scopeId || null,
    today,
  });
  const alreadyFollows = row?.own?.policy_id === policyId;

  async function handleConfirm() {
    if (!effectiveFrom) {
      setError("Start date is required.");
      return;
    }
    if (scopeType !== "COMPANY" && !scopeId) {
      setError(`Choose the ${SCOPE_TYPE_LABELS[scopeType].toLowerCase()} this applies to.`);
      return;
    }
    if (row === undefined) {
      setError("Still checking what they follow now. Try again in a moment.");
      return;
    }
    if (alreadyFollows) {
      setError("They already follow this policy.");
      return;
    }
    if (row?.own && effectiveFrom <= row.own.effective_from) {
      setError(
        `Must be after ${formatCompanyDate(row.own.effective_from, datePattern)}, when their current assignment started.`,
      );
      return;
    }
    setError(null);
    const target = scopeType === "COMPANY" ? null : scopeId;

    if (needsImpactPreview(policyKind)) {
      setImpact({
        change_type: "ASSIGNMENT_CREATE",
        expected_version: row?.own?.version,
        body: {
          policy_kind: policyKind,
          policy_id: policyId,
          scope_type: scopeType,
          scope_id: target,
          effective_from: effectiveFrom,
          reason: reason.trim() || null,
        },
      });
      return;
    }

    setSaving(true);
    try {
      await apiClient.post("/policy-assignments/batch", {
        scope_type: scopeType,
        scope_id: target,
        effective_from: effectiveFrom,
        reason: reason.trim() || null,
        changes: [
          {
            policy_kind: policyKind,
            policy_id: policyId,
            leave_type_id: leaveTypeId,
            expected_version: row?.own?.version ?? null,
          },
        ],
      });
      toast({ title: "Assignment saved", variant: "success" });
      onAssigned();
    } catch (err) {
      setError(describeApiError(err));
    } finally {
      setSaving(false);
    }
  }

  if (impact) {
    return (
      <ChangeImpactDialog
        change={impact}
        title={`Assign ${policyName}`}
        onClose={onClose}
        onApplied={onAssigned}
      />
    );
  }

  return (
    <Dialog open onOpenChange={(open) => (!open && !saving ? onClose() : null)}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Add who follows {policyName}</DialogTitle>
          <DialogDescription>
            The most specific setting wins: a person follows their own assignment first, then their
            shift, designation, grade, department, branch, legal entity and finally the company.
          </DialogDescription>
        </DialogHeader>
        <FormField id="assign-scope-type" label="Who" required>
          <NativeSelect
            value={scopeType}
            onChange={(e) => {
              setScopeType(e.target.value as ScopeType);
              setScopeId("");
              setError(null);
            }}
          >
            {SCOPE_TYPES.map((scope) => (
              <option key={scope} value={scope}>
                {SCOPE_TYPE_LABELS[scope]}
              </option>
            ))}
          </NativeSelect>
        </FormField>
        <ScopeTargetField
          idPrefix="assign"
          scopeType={scopeType}
          value={scopeId}
          onChange={(id) => {
            setScopeId(id);
            setError(null);
          }}
        />
        {alreadyFollows ? (
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
        <FormField id="assign-effective-from" label="Starts on" required>
          <Input
            type="date"
            value={effectiveFrom}
            onChange={(e) => setEffectiveFrom(e.target.value)}
          />
        </FormField>
        {effectiveFrom && effectiveFrom < today ? (
          <p className="text-sm text-warning">This starts in the past.</p>
        ) : null}
        <FormField id="assign-reason" label="Reason (optional)">
          <Input value={reason} onChange={(e) => setReason(e.target.value)} />
        </FormField>
        {needsImpactPreview(policyKind) ? (
          <p className="text-sm text-foreground-secondary">
            Next you&apos;ll see which days change before anything is saved.
          </p>
        ) : null}
        {error ? <p className="text-sm text-danger">{error}</p> : null}
        <DialogFooter>
          <Button type="button" variant="outline" onClick={onClose} disabled={saving}>
            Cancel
          </Button>
          <Button type="button" onClick={() => void handleConfirm()} disabled={saving}>
            {saving ? "Saving…" : needsImpactPreview(policyKind) ? "Preview changes" : "Assign"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
