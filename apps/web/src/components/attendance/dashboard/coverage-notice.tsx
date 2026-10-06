import { Info } from "lucide-react";

/** What the dashboard cannot show, and why — so a missing breakdown is never mistaken for a
 * zero. Mirrors the backend-gap list in the delivery report. */
const GAPS: { label: string; reason: string }[] = [
  {
    label: "Department, branch, location and designation analytics / filters",
    reason:
      "Attendance days and the employee list carry no department, branch or designation; they live on per-employee assignments, and reading them means one request per employee.",
  },
  {
    label: "Office vs remote distribution",
    reason: "There is no work-mode field. “Remote” here is only the WFH attendance status.",
  },
  {
    label: "Legal-entity filtering of attendance days",
    reason: "Days carry no legal entity; the entity filter applies to attendance periods only.",
  },
  {
    label: "Payable hours and expected working days",
    reason: "The period summary reports payable days, not payable hours or an expected-day count.",
  },
  {
    label: "Real-time presence",
    reason: "Attendance is calculated on each punch and by a daily job — it is a snapshot, not a live feed.",
  },
  {
    label: "Export (CSV / Excel / PDF)",
    reason: "No attendance export endpoint exists yet.",
  },
];

export function CoverageNotice() {
  return (
    <details className="group rounded-lg border border-border bg-surface px-4 py-3 text-sm">
      <summary className="flex cursor-pointer list-none items-center gap-2 font-medium text-foreground">
        <Info className="h-4 w-4 text-info" aria-hidden="true" />
        Not shown on this dashboard
        <span className="text-xs font-normal text-foreground-muted">— data the backend doesn&apos;t provide yet</span>
      </summary>
      <ul className="mt-3 space-y-2">
        {GAPS.map((gap) => (
          <li key={gap.label}>
            <p className="font-medium text-foreground">{gap.label}</p>
            <p className="text-xs text-foreground-secondary">{gap.reason}</p>
          </li>
        ))}
      </ul>
    </details>
  );
}
