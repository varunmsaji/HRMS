import type { PolicyTemplate } from "@/components/policy/policy-kind-config";
import {
  EMPTY_OVERTIME_POLICY_VERSION_FORM_VALUES as BASE,
  type OvertimePolicyVersionFormValues,
} from "@/lib/overtime-policy/validate-overtime-policy";

/** Labels payroll can read. The multiplier is information only, so it is left blank. */
const LABELS = [
  { dayClass: "NORMAL", classificationCode: "OT_NORMAL", multiplierDecimal: "" },
  { dayClass: "WEEKLY_OFF", classificationCode: "OT_WEEKOFF", multiplierDecimal: "" },
  { dayClass: "HOLIDAY", classificationCode: "OT_HOLIDAY", multiplierDecimal: "" },
];

export const OVERTIME_POLICY_TEMPLATES: PolicyTemplate<OvertimePolicyVersionFormValues>[] = [
  {
    key: "manager",
    label: "Manager approves",
    description:
      "Overtime counts on shifts marked eligible, and the manager approves it afterwards. No limits.",
    defaultName: "Manager approves overtime",
    values: { ...BASE, approvalChain: "MANAGER", rateRows: LABELS },
  },
  {
    key: "manager-hr",
    label: "Manager, then HR approve",
    description: "The same, but HR approves after the manager.",
    defaultName: "Manager and HR approve overtime",
    values: { ...BASE, approvalChain: "MANAGER_THEN_HR", rateRows: LABELS },
  },
  {
    key: "none",
    label: "Overtime not allowed",
    description: "Nobody earns overtime under this policy.",
    defaultName: "No overtime",
    values: { ...BASE, eligibility: "NEVER" },
  },
  {
    key: "blank",
    label: "Start from scratch",
    description: "Set every rule yourself.",
    defaultName: "",
    values: BASE,
  },
];
