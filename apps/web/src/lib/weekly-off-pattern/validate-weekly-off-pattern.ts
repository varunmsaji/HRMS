import type { WeeklyOffPattern } from "@/lib/weekly-off-pattern/types";

export interface WeeklyOffRuleFormValues {
  weekday: number;
  nthInMonth: string; // "" | "-1" | "1".."5"
  cycleStartDate: string;
  offFraction: "1.00" | "0.50";
  weekParity: "" | "EVEN" | "ODD";
}

export interface WeeklyOffPatternFormValues {
  name: string;
  code: string;
  patternKind: "FIXED_WEEKDAYS" | "NTH_WEEKDAY" | "ALTERNATE" | "CUSTOM";
  rules: WeeklyOffRuleFormValues[];
}

export type WeeklyOffPatternFormErrors = Partial<
  Record<"name" | "code" | "rules", string>
>;

export const EMPTY_RULE: WeeklyOffRuleFormValues = {
  weekday: 6,
  nthInMonth: "",
  cycleStartDate: "",
  offFraction: "1.00",
  weekParity: "",
};

export const EMPTY_WEEKLY_OFF_PATTERN_FORM_VALUES: WeeklyOffPatternFormValues = {
  name: "",
  code: "",
  patternKind: "FIXED_WEEKDAYS",
  rules: [{ ...EMPTY_RULE }],
};

export function weeklyOffPatternToFormValues(
  pattern: WeeklyOffPattern,
): WeeklyOffPatternFormValues {
  return {
    name: pattern.name,
    code: pattern.code ?? "",
    patternKind: pattern.pattern_kind,
    rules: pattern.rules.map((rule) => ({
      weekday: rule.weekday,
      nthInMonth: rule.nth_in_month === null ? "" : String(rule.nth_in_month),
      cycleStartDate: rule.cycle_start_date ?? "",
      offFraction: rule.off_fraction.startsWith("0.5") ? "0.50" : "1.00",
      weekParity: rule.week_parity ?? "",
    })),
  };
}

function buildRulePayload(rule: WeeklyOffRuleFormValues): Record<string, unknown> {
  return {
    weekday: rule.weekday,
    nth_in_month: rule.nthInMonth.trim() === "" ? null : Number(rule.nthInMonth),
    cycle_start_date: rule.cycleStartDate.trim() || null,
    off_fraction: rule.offFraction,
    week_parity: rule.weekParity || null,
  };
}

export function buildCreatePayload(values: WeeklyOffPatternFormValues): Record<string, unknown> {
  return {
    name: values.name.trim(),
    code: values.code.trim() || null,
    pattern_kind: values.patternKind,
    rules: values.rules.map(buildRulePayload),
  };
}

/** Always sends `rules` when present (atomic replace-all on the server), plus any changed
 * identity fields — mirrors `WeeklyOffPatternUpdate`'s "rules, when present, replaces the
 * entire set" contract. */
export function buildUpdatePatch(
  values: WeeklyOffPatternFormValues,
  pattern: WeeklyOffPattern,
): Record<string, unknown> {
  const patch: Record<string, unknown> = {};
  if (values.name.trim() !== pattern.name) patch.name = values.name.trim();
  const code = values.code.trim() || null;
  if (code !== pattern.code) patch.code = code;
  if (values.patternKind !== pattern.pattern_kind) patch.pattern_kind = values.patternKind;
  patch.rules = values.rules.map(buildRulePayload);
  return patch;
}

export function validateWeeklyOffPatternForm(
  values: WeeklyOffPatternFormValues,
): WeeklyOffPatternFormErrors {
  const errors: WeeklyOffPatternFormErrors = {};
  if (!values.name.trim()) {
    errors.name = "Pattern name is required.";
  }
  if (values.rules.length === 0) {
    errors.rules = "At least one rule is required.";
    return errors;
  }
  for (const rule of values.rules) {
    if (values.patternKind === "NTH_WEEKDAY" && !rule.nthInMonth.trim()) {
      errors.rules = "Every rule needs an occurrence (e.g. 2nd, last) for this pattern kind.";
    }
    if (values.patternKind === "ALTERNATE" && !rule.cycleStartDate.trim()) {
      errors.rules = "Every rule needs a starting date for an alternating pattern.";
    }
    if (
      values.patternKind === "FIXED_WEEKDAYS" &&
      (rule.nthInMonth.trim() || rule.cycleStartDate.trim())
    ) {
      errors.rules = "Fixed-weekday rules cannot use an occurrence or a starting date.";
    }
  }
  return errors;
}
