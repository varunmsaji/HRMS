"use client";

import { CalendarOff } from "lucide-react";

import { LeavePolicySummary } from "@/components/leave-policy/leave-policy-summary";
import { LeavePolicyVersionForm } from "@/components/leave-policy/leave-policy-version-form";
import type { PolicyKindConfig } from "@/components/policy/policy-kind-config";
import { LEAVE_APPROVAL_LABELS } from "@/lib/leave-policy/labels";
import { LEAVE_POLICY_TEMPLATES } from "@/lib/leave-policy/templates";
import type { LeavePolicy, LeavePolicyVersion } from "@/lib/leave-policy/types";
import {
  buildLeavePolicyVersionPayload,
  EMPTY_LEAVE_POLICY_VERSION_FORM_VALUES,
  leavePolicyVersionToFormValues,
  mapLeavePolicyVersionApiErrors,
  validateLeavePolicyVersionForm,
  type LeavePolicyVersionFormErrors,
  type LeavePolicyVersionFormValues,
} from "@/lib/leave-policy/validate-leave-policy";

function LeaveRulesForm({
  values,
  errors,
  onChange,
}: {
  values: LeavePolicyVersionFormValues;
  errors: LeavePolicyVersionFormErrors;
  onChange: (values: LeavePolicyVersionFormValues) => void;
  context: null;
}) {
  return <LeavePolicyVersionForm values={values} errors={errors} onChange={onChange} />;
}

export const leavePolicyConfig: PolicyKindConfig<
  LeavePolicy,
  LeavePolicyVersion,
  LeavePolicyVersionFormValues,
  LeavePolicyVersionFormErrors
> = {
  kind: "LEAVE_POLICY",
  path: "/leave-policies",
  pluralLabel: "Leave Policies",
  singularLabel: "leave policy",
  listDescription:
    "Who can apply, who approves, how days are credited and what happens at year end, for each leave type.",
  emptyListTitle: "No leave policies have been configured yet.",
  icon: CalendarOff,
  leaveTyped: true,
  managePermission: "LEAVE.POLICY_MANAGE",
  templates: LEAVE_POLICY_TEMPLATES,
  emptyValues: EMPTY_LEAVE_POLICY_VERSION_FORM_VALUES,
  Form: LeaveRulesForm,
  Summary: LeavePolicySummary,
  versionToValues: leavePolicyVersionToFormValues,
  toPayload: buildLeavePolicyVersionPayload,
  validateDraft: validateLeavePolicyVersionForm,
  validateForPublish: validateLeavePolicyVersionForm,
  mapApiErrors: mapLeavePolicyVersionApiErrors,
  historySummary: (version) =>
    `${LEAVE_APPROVAL_LABELS[version.approval_chain] ?? version.approval_chain}, ${
      version.accrual_frequency === "NONE"
        ? "no automatic credit"
        : `${version.accrual_rate_per_cycle ?? "0"} ${
            version.accrual_frequency === "MONTHLY" ? "a month" : "a year"
          }`
    }`,
};
