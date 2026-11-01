import type { PayRun } from "@/lib/payroll/types";

export interface ChecklistItem {
  key: string;
  label: string;
  done: boolean;
}

/** The pre-disbursal checks, each read straight off the run's own recorded state. */
export function preDisbursalChecklist(
  run: Pick<
    PayRun,
    "inputs_locked_at" | "computed_at" | "error_count" | "variance_open_count" | "approved_at" | "status"
  >,
): ChecklistItem[] {
  const computed = run.computed_at !== null;
  return [
    { key: "inputs", label: "Attendance & leave inputs locked", done: run.inputs_locked_at !== null },
    { key: "computed", label: "Pay computed with no errors", done: computed && run.error_count === 0 },
    {
      key: "variance",
      label: "Variances acknowledged",
      done: computed && run.variance_open_count === 0,
    },
    { key: "approved", label: "Approved by a second user", done: run.approved_at !== null },
  ];
}
