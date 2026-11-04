import type { PolicyTemplate } from "@/components/policy/policy-kind-config";
import { REGULARIZATION_TYPES } from "@/lib/regularization-policy/types";
import {
  EMPTY_REGULARIZATION_POLICY_VERSION_FORM_VALUES as BASE,
  type RegularizationPolicyVersionFormValues,
} from "@/lib/regularization-policy/validate-regularization-policy";

const ALL_TYPES = [...REGULARIZATION_TYPES];

export const REGULARIZATION_POLICY_TEMPLATES: PolicyTemplate<RegularizationPolicyVersionFormValues>[] =
  [
    {
      key: "manager",
      label: "Manager approves",
      description:
        "Everyone can ask for any kind of correction, with a reason. The manager approves. No limits.",
      defaultName: "Manager approves corrections",
      values: { ...BASE, approvalChain: "MANAGER", allowedTypes: ALL_TYPES },
    },
    {
      key: "manager-hr",
      label: "Manager, then HR approve",
      description: "The same, but HR approves after the manager.",
      defaultName: "Manager and HR approve corrections",
      values: { ...BASE, approvalChain: "MANAGER_THEN_HR", allowedTypes: ALL_TYPES },
    },
    {
      key: "hr",
      label: "HR approves",
      description: "The same, but only HR approves.",
      defaultName: "HR approves corrections",
      values: { ...BASE, approvalChain: "HR", allowedTypes: ALL_TYPES },
    },
    {
      key: "blank",
      label: "Start from scratch",
      description: "Choose each kind of correction yourself.",
      defaultName: "",
      values: BASE,
    },
  ];
