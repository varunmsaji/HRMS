"use client";

import { FileClock } from "lucide-react";

import type { PolicyKindConfig } from "@/components/policy/policy-kind-config";
import { RegularizationPolicySummary } from "@/components/regularization-policy/regularization-policy-summary";
import { RegularizationPolicyVersionForm } from "@/components/regularization-policy/regularization-policy-version-form";
import { APPROVAL_CHAIN_LABELS } from "@/lib/policy/approval-labels";
import { REGULARIZATION_POLICY_TEMPLATES } from "@/lib/regularization-policy/templates";
import type {
  RegularizationPolicy,
  RegularizationPolicyVersion,
} from "@/lib/regularization-policy/types";
import {
  buildRegularizationPolicyVersionPayload,
  EMPTY_REGULARIZATION_POLICY_VERSION_FORM_VALUES,
  mapRegularizationPolicyVersionApiErrors,
  regularizationPolicyVersionToFormValues,
  validateRegularizationPolicyForPublish,
  validateRegularizationPolicyVersionForm,
  type RegularizationPolicyVersionFormErrors,
  type RegularizationPolicyVersionFormValues,
} from "@/lib/regularization-policy/validate-regularization-policy";

function RegularizationRulesForm({
  values,
  errors,
  onChange,
}: {
  values: RegularizationPolicyVersionFormValues;
  errors: RegularizationPolicyVersionFormErrors;
  onChange: (values: RegularizationPolicyVersionFormValues) => void;
  context: null;
}) {
  return <RegularizationPolicyVersionForm values={values} errors={errors} onChange={onChange} />;
}

export const regularizationPolicyConfig: PolicyKindConfig<
  RegularizationPolicy,
  RegularizationPolicyVersion,
  RegularizationPolicyVersionFormValues,
  RegularizationPolicyVersionFormErrors
> = {
  kind: "REGULARIZATION_POLICY",
  path: "/regularization-policies",
  pluralLabel: "Correction Policies",
  singularLabel: "correction policy",
  listDescription:
    "Who can ask for an attendance correction after the day has passed, how far back, and who approves it.",
  emptyListTitle: "No correction policies have been set up yet.",
  icon: FileClock,
  templates: REGULARIZATION_POLICY_TEMPLATES,
  emptyValues: EMPTY_REGULARIZATION_POLICY_VERSION_FORM_VALUES,
  Form: RegularizationRulesForm,
  Summary: RegularizationPolicySummary,
  versionToValues: regularizationPolicyVersionToFormValues,
  toPayload: buildRegularizationPolicyVersionPayload,
  validateDraft: validateRegularizationPolicyVersionForm,
  validateForPublish: validateRegularizationPolicyForPublish,
  mapApiErrors: mapRegularizationPolicyVersionApiErrors,
  historySummary: (version) =>
    `${version.allowed_types.length} kinds of correction, ${
      APPROVAL_CHAIN_LABELS[version.approval_chain] ?? version.approval_chain
    }`,
};
