"use client";

import { Printer } from "lucide-react";
import type { ReactNode } from "react";

import { Button } from "@/components/ui/button";
import { formatInr, formatPayMonth, type Payslip, type PayslipLine } from "@/lib/payroll/types";

function Fact({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="flex justify-between gap-3 py-0.5 text-sm">
      <span className="text-foreground-muted">{label}</span>
      <span className="text-right text-foreground">{value || "—"}</span>
    </div>
  );
}

function Lines({
  title,
  lines,
  total,
  showFull,
}: {
  title: string;
  lines: PayslipLine[];
  total: number;
  showFull?: boolean;
}) {
  return (
    <table className="w-full text-sm">
      <thead>
        <tr className="border-b border-border text-xs uppercase tracking-wide text-foreground-muted">
          <th className="py-1.5 text-left font-medium">{title}</th>
          {showFull ? <th className="py-1.5 text-right font-medium">Full month</th> : null}
          <th className="py-1.5 text-right font-medium">Amount</th>
        </tr>
      </thead>
      <tbody>
        {lines.length === 0 ? (
          <tr>
            <td colSpan={showFull ? 3 : 2} className="py-1.5 text-foreground-muted">
              None
            </td>
          </tr>
        ) : (
          lines.map((line) => (
            <tr key={line.component_code}>
              <td className="py-1 text-foreground">{line.component_name}</td>
              {showFull ? (
                <td className="py-1 text-right tabular-nums text-foreground-secondary">
                  {line.full_monthly_minor !== null ? formatInr(line.full_monthly_minor) : ""}
                </td>
              ) : null}
              <td className="py-1 text-right tabular-nums">{formatInr(line.amount_minor)}</td>
            </tr>
          ))
        )}
        <tr className="border-t border-border font-medium">
          <td className="py-1.5 text-foreground">Total</td>
          {showFull ? <td /> : null}
          <td className="py-1.5 text-right tabular-nums">{formatInr(total)}</td>
        </tr>
      </tbody>
    </table>
  );
}

/** A printable payslip (FR-PAY-017). "Print / save as PDF" uses the browser's print dialog; the
 * app shell is hidden when printing. */
export function PayslipView({ payslip }: { payslip: Payslip }) {
  const employerTotal = payslip.employer_contributions.reduce((sum, l) => sum + l.amount_minor, 0);
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2 print:hidden">
        {payslip.is_final ? (
          <span className="text-sm text-foreground-muted">Final payslip</span>
        ) : (
          <span className="text-sm font-medium text-warning">
            Preview — this pay run is not finalised yet
          </span>
        )}
        <Button type="button" variant="outline" onClick={() => window.print()}>
          <Printer className="mr-2 h-4 w-4" aria-hidden="true" />
          Print / save as PDF
        </Button>
      </div>

      <article className="mx-auto max-w-3xl space-y-5 rounded-md border border-border bg-surface p-6 print:max-w-none print:border-0 print:p-0">
        <header className="border-b border-border pb-4 text-center">
          <h2 className="text-lg font-semibold text-foreground">
            {payslip.legal_entity_name ?? payslip.company_name}
          </h2>
          {payslip.legal_entity_address ? (
            <p className="text-xs text-foreground-muted">{payslip.legal_entity_address}</p>
          ) : null}
          <p className="mt-2 text-sm font-medium text-foreground">
            Payslip for {formatPayMonth(payslip.month)}
            {payslip.is_final ? "" : " (preview)"}
          </p>
        </header>

        <section className="grid gap-x-8 gap-y-1 sm:grid-cols-2 print:grid-cols-2">
          <div>
            <Fact label="Employee" value={payslip.employee_name} />
            <Fact label="Employee code" value={payslip.employee_code} />
            <Fact label="Designation" value={payslip.designation} />
            <Fact label="Department" value={payslip.department} />
            <Fact label="Date of joining" value={payslip.date_of_joining} />
            <Fact label="PAN" value={payslip.pan_masked} />
          </div>
          <div>
            <Fact label="UAN" value={payslip.uan_number} />
            {payslip.esi_ip_number ? <Fact label="ESI IP number" value={payslip.esi_ip_number} /> : null}
            <Fact
              label="Paid by"
              value={
                payslip.payment_mode === "BANK"
                  ? `${payslip.bank_name ?? "Bank"} ····${payslip.account_last4 ?? ""}`
                  : payslip.payment_mode
              }
            />
            <Fact label="Days in month" value={payslip.days_in_month} />
            <Fact label="Paid days" value={payslip.paid_days} />
            <Fact label="Loss of pay days" value={payslip.lop_days} />
            <Fact label="Pay date" value={payslip.pay_date} />
          </div>
        </section>

        <section className="grid gap-6 sm:grid-cols-2 print:grid-cols-2">
          <Lines title="Earnings" lines={payslip.earnings} total={payslip.gross_minor} showFull />
          <Lines title="Deductions" lines={payslip.deductions} total={payslip.deductions_minor} />
        </section>

        <section className="rounded-md bg-surface-secondary p-3">
          <div className="flex justify-between text-base font-semibold text-foreground">
            <span>Net pay</span>
            <span className="tabular-nums">{formatInr(payslip.net_minor)}</span>
          </div>
          <p className="mt-1 text-sm text-foreground-secondary">{payslip.net_in_words}</p>
        </section>

        {payslip.employer_contributions.length > 0 ? (
          <section>
            <Lines
              title="Employer contributions (not part of net pay)"
              lines={payslip.employer_contributions}
              total={employerTotal}
            />
          </section>
        ) : null}

        {payslip.leave_balances.length > 0 ? (
          <section>
            <h3 className="mb-1 text-xs font-medium uppercase tracking-wide text-foreground-muted">
              Leave balance on {payslip.period_end}
            </h3>
            <div className="flex flex-wrap gap-x-6 gap-y-1 text-sm">
              {payslip.leave_balances.map((balance) => (
                <span key={balance.code}>
                  {balance.name}: <span className="tabular-nums">{balance.balance}</span>
                </span>
              ))}
            </div>
          </section>
        ) : null}

        <footer className="border-t border-border pt-3 text-center text-xs text-foreground-muted">
          This is a computer-generated payslip and does not need a signature.
        </footer>
      </article>
    </div>
  );
}
