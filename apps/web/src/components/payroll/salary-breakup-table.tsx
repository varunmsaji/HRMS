import { COMPONENT_TYPE_LABELS, formatInr, type SalaryBreakup } from "@/lib/payroll/types";

/** Monthly and annual amount per component, with gross, employer contributions and CTC totals
 * (payroll Phase 5.1 — D2: employer contributions sit inside CTC). */
export function SalaryBreakupTable({ breakup }: { breakup: SalaryBreakup }) {
  const earnings = breakup.lines.filter((line) => line.component_type === "EARNING");
  const employer = breakup.lines.filter((line) => line.component_type === "EMPLOYER_CONTRIBUTION");
  const rows = (lines: typeof breakup.lines) =>
    lines.map((line) => (
      <tr key={line.component_code}>
        <td className="px-3 py-2">
          <div className="text-foreground">{line.component_name}</div>
          <div className="text-xs text-foreground-muted">{line.basis}</div>
        </td>
        <td className="px-3 py-2 text-right tabular-nums">{formatInr(line.monthly_minor)}</td>
        <td className="px-3 py-2 text-right tabular-nums">{formatInr(line.annual_minor)}</td>
      </tr>
    ));
  const total = (label: string, monthly: number) => (
    <tr className="bg-surface-secondary font-medium">
      <td className="px-3 py-2 text-foreground">{label}</td>
      <td className="px-3 py-2 text-right tabular-nums">{formatInr(monthly)}</td>
      <td className="px-3 py-2 text-right tabular-nums">{formatInr(monthly * 12)}</td>
    </tr>
  );
  return (
    <div className="overflow-x-auto rounded-md border border-border">
      <table className="w-full text-sm">
        <thead className="bg-surface-secondary text-xs uppercase tracking-wide text-foreground-muted">
          <tr>
            <th className="px-3 py-2 text-left font-medium">Component</th>
            <th className="px-3 py-2 text-right font-medium">Monthly</th>
            <th className="px-3 py-2 text-right font-medium">Annual</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-border">
          {rows(earnings)}
          {total("Gross", breakup.gross_monthly_minor)}
          {employer.length > 0 ? (
            <>
              <tr>
                <td colSpan={3} className="px-3 pt-3 text-xs uppercase text-foreground-muted">
                  {COMPONENT_TYPE_LABELS.EMPLOYER_CONTRIBUTION}s
                </td>
              </tr>
              {rows(employer)}
            </>
          ) : null}
          {total("Cost to company", breakup.monthly_ctc_minor)}
        </tbody>
      </table>
    </div>
  );
}
