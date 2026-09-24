import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { PayslipView } from "@/components/payroll/payslip-view";
import type { Payslip } from "@/lib/payroll/types";

const payslip: Payslip = {
  pay_run_id: "run-1",
  month: "2026-09",
  period_start: "2026-09-01",
  period_end: "2026-09-30",
  pay_date: "2026-10-01",
  status: "FINALISED",
  is_final: true,
  company_name: "Acme",
  legal_entity_name: "Acme Pvt Ltd",
  legal_entity_address: "Pune",
  legal_entity_pan: null,
  legal_entity_tan: null,
  employee_id: "emp-1",
  employee_code: "E001",
  employee_name: "Asha Rao",
  designation: "Engineer",
  department: "Engineering",
  date_of_joining: "2026-01-01",
  pan_masked: "******234F",
  uan_number: "100200300400",
  esi_ip_number: null,
  payment_mode: "BANK",
  bank_name: "State Bank",
  account_last4: "9012",
  days_in_month: 30,
  paid_days: "30",
  lop_days: "0",
  earnings: [
    { component_code: "BASIC", component_name: "Basic", full_monthly_minor: 2_910_000, amount_minor: 2_910_000 },
  ],
  deductions: [
    { component_code: "PF_EMPLOYEE", component_name: "Provident Fund", full_monthly_minor: null, amount_minor: 180_000 },
  ],
  employer_contributions: [
    { component_code: "EPS_EMPLOYER", component_name: "Employer pension (EPS)", full_monthly_minor: null, amount_minor: 125_000 },
  ],
  gross_minor: 2_910_000,
  deductions_minor: 180_000,
  net_minor: 2_730_000,
  net_in_words: "Rupees Twenty Seven Thousand Three Hundred Only",
  leave_balances: [{ code: "EL", name: "Earned leave", balance: "12.5" }],
};

describe("PayslipView", () => {
  it("renders a final payslip with net pay in words and employer contributions apart", () => {
    render(<PayslipView payslip={payslip} />);
    expect(screen.getByText("Payslip for September 2026")).toBeInTheDocument();
    expect(screen.getByText("Rupees Twenty Seven Thousand Three Hundred Only")).toBeInTheDocument();
    expect(screen.getByText("₹27,300")).toBeInTheDocument();
    expect(screen.getByText(/Employer contributions \(not part of net pay\)/)).toBeInTheDocument();
    expect(screen.getByText("State Bank ····9012")).toBeInTheDocument();
    expect(screen.getByText(/Earned leave/)).toBeInTheDocument();
    expect(screen.queryByText(/Preview/)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Print \/ save as PDF/ })).toBeInTheDocument();
  });

  it("marks a preview of an unfinalised run", () => {
    render(<PayslipView payslip={{ ...payslip, is_final: false, status: "COMPUTED" }} />);
    expect(screen.getByText(/Preview — this pay run is not finalised yet/)).toBeInTheDocument();
    expect(screen.getByText("Payslip for September 2026 (preview)")).toBeInTheDocument();
  });
});
