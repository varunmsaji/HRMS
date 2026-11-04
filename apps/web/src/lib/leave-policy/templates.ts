import type { PolicyTemplate } from "@/components/policy/policy-kind-config";
import {
  EMPTY_LEAVE_POLICY_VERSION_FORM_VALUES as BASE,
  type LeavePolicyVersionFormValues,
} from "@/lib/leave-policy/validate-leave-policy";

/** Common starting points. The days are typical figures, not legal minimums: change them to match
 * the company's own leave rules. */
export const LEAVE_POLICY_TEMPLATES: PolicyTemplate<LeavePolicyVersionFormValues>[] = [
  {
    key: "casual",
    label: "Casual leave",
    description: "1 day a month. Unused days lapse at the end of the leave year.",
    defaultName: "Casual leave",
    values: {
      ...BASE,
      accrualFrequency: "MONTHLY",
      accrualRatePerCycle: "1",
      yearEndAction: "LAPSE",
    },
  },
  {
    key: "earned",
    label: "Earned leave",
    description: "1.5 days a month. Up to 30 unused days carry into the next year.",
    defaultName: "Earned leave",
    values: {
      ...BASE,
      accrualFrequency: "MONTHLY",
      accrualRatePerCycle: "1.5",
      yearEndAction: "CARRY_FORWARD",
      maxCarryForwardDays: "30",
    },
  },
  {
    key: "sick",
    label: "Sick leave",
    description: "12 days credited once a year. Unused days lapse.",
    defaultName: "Sick leave",
    values: {
      ...BASE,
      accrualFrequency: "YEARLY",
      accrualRatePerCycle: "12",
      yearEndAction: "LAPSE",
      sandwichRuleEnabled: false,
    },
  },
  {
    key: "blank",
    label: "Start from scratch",
    description: "Set every rule yourself.",
    defaultName: "",
    values: BASE,
  },
];
