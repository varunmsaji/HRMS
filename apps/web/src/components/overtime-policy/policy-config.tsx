"use client";

import { Timer } from "lucide-react";

import { OvertimePolicySummary } from "@/components/overtime-policy/overtime-policy-summary";
import { OvertimePolicyVersionForm } from "@/components/overtime-policy/overtime-policy-version-form";
import type { PolicyKindConfig } from "@/components/policy/policy-kind-config";
import { ELIGIBILITY_LABELS } from "@/lib/overtime-policy/labels";
import { OVERTIME_POLICY_TEMPLATES } from "@/lib/overtime-policy/templates";
import type { OvertimePolicy, OvertimePolicyVersion } from "@/lib/overtime-policy/types";
import {
  buildOvertimePolicyVersionPayload,
  EMPTY_OVERTIME_POLICY_VERSION_FORM_VALUES,
  mapOvertimePolicyVersionApiErrors,
  overtimePolicyVersionToFormValues,
  validateOvertimePolicyVersionForm,
  type OvertimePolicyVersionFormErrors,
  type OvertimePolicyVersionFormValues,
} from "@/lib/overtime-policy/validate-overtime-policy";
import { APPROVAL_CHAIN_LABELS } from "@/lib/policy/approval-labels";

function OvertimeRulesForm({
  values,
  errors,
  onChange,
}: {
  values: OvertimePolicyVersionFormValues;
  errors: OvertimePolicyVersionFormErrors;
  onChange: (values: OvertimePolicyVersionFormValues) => void;
  context: null;
}) {
  return <OvertimePolicyVersionForm values={values} errors={errors} onChange={onChange} />;
}

export const overtimePolicyConfig: PolicyKindConfig<
  OvertimePolicy,
  OvertimePolicyVersion,
  OvertimePolicyVersionFormValues,
  OvertimePolicyVersionFormErrors
> = {
  kind: "OVERTIME_POLICY",
  path: "/overtime-policies",
  pluralLabel: "Overtime Policies",
  singularLabel: "overtime policy",
  listDescription:
    "Who can earn overtime, how much counts, who approves it, and whether it is paid or taken as time off.",
  emptyListTitle: "No overtime policies have been configured yet.",
  icon: Timer,
  templates: OVERTIME_POLICY_TEMPLATES,
  emptyValues: EMPTY_OVERTIME_POLICY_VERSION_FORM_VALUES,
  Form: OvertimeRulesForm,
  Summary: OvertimePolicySummary,
  versionToValues: overtimePolicyVersionToFormValues,
  toPayload: buildOvertimePolicyVersionPayload,
  validateDraft: validateOvertimePolicyVersionForm,
  validateForPublish: validateOvertimePolicyVersionForm,
  mapApiErrors: mapOvertimePolicyVersionApiErrors,
  historySummary: (version) =>
    `${ELIGIBILITY_LABELS[version.eligibility] ?? version.eligibility}, ${
      APPROVAL_CHAIN_LABELS[version.approval_chain] ?? version.approval_chain
    }`,
};
