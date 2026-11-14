import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/components/common/toast", () => ({
  useToast: () => ({ toast: vi.fn() }),
}));
vi.mock("@/lib/api/client", () => ({
  apiClient: { get: vi.fn(), post: vi.fn() },
}));

import { SalarySetupEditor } from "@/components/payroll/salary-setup-editor";
import { apiClient } from "@/lib/api/client";
import type {
  EmployeeSalarySetup,
  SalaryComponent,
  SalaryStructure,
  SalaryStructureLine,
} from "@/lib/payroll/types";

const mockedGet = vi.mocked(apiClient.get);
const mockedPost = vi.mocked(apiClient.post);

function component(
  id: string,
  code: string,
  name: string,
  type = "EARNING",
): SalaryComponent {
  return {
    id,
    code,
    name,
    component_type: type,
    is_system: true,
    is_taxable: true,
    is_pf_wage: false,
    is_esi_wage: false,
    is_prorated: true,
    show_on_payslip: true,
    display_order: 0,
    is_active: true,
    version: 1,
    created_at: "",
    updated_at: "",
  } as SalaryComponent;
}

function line(
  componentId: string,
  code: string,
  calc: SalaryStructureLine["calculation_type"],
  percentage: string | null,
  base: string | null = null,
): SalaryStructureLine {
  return {
    id: `l-${code}`,
    salary_component_id: componentId,
    component_code: code,
    component_name: code,
    component_type: "EARNING",
    calculation_type: calc,
    percentage,
    amount_monthly_minor: null,
    base_salary_component_id: base,
    max_monthly_minor: null,
    applies_when: "ALWAYS",
    display_order: 10,
  };
}

const components = [
  component("c-basic", "BASIC", "Basic"),
  component("c-hra", "HRA", "HRA"),
  component("c-sa", "SPECIAL_ALLOWANCE", "Special Allowance"),
];
const templateLines = [
  line("c-basic", "BASIC", "PERCENTAGE_OF_GROSS", "50"),
  line("c-hra", "HRA", "PERCENTAGE_OF_COMPONENT", "40", "c-basic"),
  line("c-sa", "SPECIAL_ALLOWANCE", "BALANCING", null),
];
const standard: SalaryStructure = {
  id: "st-1",
  company_id: "co",
  code: "STANDARD",
  name: "Standard",
  description: null,
  is_active: true,
  version: 1,
  created_at: "",
  updated_at: "",
  versions: [
    {
      id: "v-1",
      salary_structure_id: "st-1",
      version_number: 1,
      status: "PUBLISHED",
      effective_from: "2026-01-01",
      effective_to: null,
      published_at: "",
      version: 1,
      lines: templateLines,
    },
  ],
} as SalaryStructure;

const setup: EmployeeSalarySetup = {
  employee_id: "emp-1",
  as_of: "2026-09-24",
  pay_basis: "MONTHLY",
  annual_ctc_minor: 120_000_000,
  pf_applicable: false,
  esi_applicable: false,
  assignment: null,
  salary_structure_id: null,
  salary_structure_name: null,
  template_structure_id: null,
  is_customised: false,
  lines: [],
};

/** Gross = monthly CTC here (no employer lines); Basic is its % of gross, HRA 40% of Basic. */
function fakePreview(body: {
  annual_ctc_minor: number;
  lines: { salary_component_id: string; percentage: string | null }[];
}) {
  const gross = body.annual_ctc_minor / 12;
  const basicPct = Number(
    body.lines.find((l) => l.salary_component_id === "c-basic")?.percentage,
  );
  const basic = Math.round((gross * basicPct) / 100);
  const hra = Math.round(basic * 0.4);
  const mk = (code: string, monthly: number) => ({
    component_code: code,
    component_name: code,
    component_type: "EARNING",
    monthly_minor: monthly,
    annual_minor: monthly * 12,
    basis: "",
  });
  return {
    pf_applicable: false,
    esi_applicable: false,
    breakup: {
      annual_ctc_minor: body.annual_ctc_minor,
      monthly_ctc_minor: gross,
      gross_monthly_minor: gross,
      employer_contributions_monthly_minor: 0,
      lines: [
        mk("BASIC", basic),
        mk("HRA", hra),
        mk("SPECIAL_ALLOWANCE", gross - basic - hra),
      ],
    },
  };
}

describe("SalarySetupEditor", () => {
  beforeEach(() => {
    mockedGet.mockImplementation((path: string) =>
      Promise.resolve(
        path.includes("/salary/setup")
          ? setup
          : path.includes("salary-structures")
            ? [standard]
            : components,
      ),
    );
    mockedPost.mockImplementation((path: string, body: unknown) =>
      path.endsWith("/preview")
        ? Promise.resolve(
            fakePreview(body as Parameters<typeof fakePreview>[0]),
          )
        : Promise.resolve({
            ...setup,
            is_customised: true,
            template_structure_id: "st-1",
          }),
    );
  });
  afterEach(() => {
    mockedGet.mockReset();
    mockedPost.mockReset();
  });

  it("fills in every component's amount from the CTC and the percentages", async () => {
    render(
      <SalarySetupEditor
        employeeId="emp-1"
        today="2026-09-24"
        onSaved={vi.fn()}
        fallback={null}
      />,
    );

    // ₹12,00,000 a year, Basic 50% of gross → ₹50,000 a month; HRA 40% of Basic → ₹20,000.
    await waitFor(() =>
      expect(screen.getByTestId("line-amount-c-basic")).toHaveTextContent(
        "₹50,000",
      ),
    );
    expect(screen.getByTestId("line-amount-c-hra")).toHaveTextContent(
      "₹20,000",
    );
    expect(screen.getByText("Same as Standard")).toBeInTheDocument();

    // Basic to 40% → amounts follow, and the structure is now this employee's own.
    fireEvent.change(screen.getAllByLabelText("Percentage")[0], {
      target: { value: "40" },
    });
    await waitFor(() =>
      expect(screen.getByTestId("line-amount-c-basic")).toHaveTextContent(
        "₹40,000",
      ),
    );
    expect(screen.getByTestId("line-amount-c-hra")).toHaveTextContent(
      "₹16,000",
    );
    expect(
      screen.getByText("Customised for this employee"),
    ).toBeInTheDocument();
  });

  it("saves the CTC and the changed lines together", async () => {
    const onSaved = vi.fn();
    render(
      <SalarySetupEditor
        employeeId="emp-1"
        today="2026-09-24"
        onSaved={onSaved}
        fallback={null}
      />,
    );
    await screen.findByText("Same as Standard");

    fireEvent.change(screen.getByLabelText(/annual ctc/i), {
      target: { value: "1500000" },
    });
    fireEvent.change(screen.getAllByLabelText("Percentage")[0], {
      target: { value: "45" },
    });
    fireEvent.change(screen.getByLabelText(/reason/i), {
      target: { value: "Annual review" },
    });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /save salary/i }));
    });

    const save = mockedPost.mock.calls.find(
      ([path]) => path === "/employees/emp-1/salary/setup",
    );
    expect(save?.[1]).toMatchObject({
      effective_from: "2026-09-24",
      reason: "Annual review",
      template_structure_id: "st-1",
      annual_ctc_minor: 150_000_000,
      revision_type: "ANNUAL",
    });
    const sent = (
      save?.[1] as {
        lines: { salary_component_id: string; percentage: string | null }[];
      }
    ).lines;
    expect(
      sent.find((l) => l.salary_component_id === "c-basic")?.percentage,
    ).toBe("45");
    expect(onSaved).toHaveBeenCalled();
  });

  it("says what is missing instead of silently refusing to save", async () => {
    render(
      <SalarySetupEditor
        employeeId="emp-1"
        today="2026-09-24"
        onSaved={vi.fn()}
        fallback={null}
      />,
    );
    await screen.findByText("Same as Standard");
    fireEvent.change(screen.getByLabelText(/annual ctc/i), {
      target: { value: "1500000" },
    });

    const save = screen.getByRole("button", { name: /save salary/i });
    expect(save).toBeEnabled();
    await act(async () => {
      fireEvent.click(save);
    });

    expect(screen.getByRole("alert")).toHaveTextContent(
      "Before saving, add a reason.",
    );
    expect(screen.getByLabelText(/reason/i)).toHaveAttribute("aria-invalid", "true");
    expect(
      mockedPost.mock.calls.some(([path]) => path === "/employees/emp-1/salary/setup"),
    ).toBe(false);

    // The warning goes away as soon as the missing field is filled in.
    fireEvent.change(screen.getByLabelText(/reason/i), {
      target: { value: "Annual review" },
    });
    expect(screen.queryByText(/Before saving/)).not.toBeInTheDocument();
    expect(screen.getByLabelText(/reason/i)).toHaveAttribute("aria-invalid", "false");
  });

  it("says when there is nothing to save", async () => {
    // Already on Standard with its exact lines: nothing differs until HR edits something.
    const assigned = { ...setup, template_structure_id: "st-1", lines: templateLines };
    mockedGet.mockImplementation((path: string) =>
      Promise.resolve(
        path.includes("/salary/setup")
          ? assigned
          : path.includes("salary-structures")
            ? [standard]
            : components,
      ),
    );
    render(
      <SalarySetupEditor
        employeeId="emp-1"
        today="2026-09-24"
        onSaved={vi.fn()}
        fallback={null}
      />,
    );
    await screen.findByText("Same as Standard");
    fireEvent.change(screen.getByLabelText(/reason/i), {
      target: { value: "Annual review" },
    });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /save salary/i }));
    });

    expect(screen.getByRole("alert")).toHaveTextContent("Nothing has changed yet");
    expect(
      mockedPost.mock.calls.some(([path]) => path === "/employees/emp-1/salary/setup"),
    ).toBe(false);
  });

  it("shows the fallback for a daily-wage employee", async () => {
    mockedGet.mockImplementation((path: string) =>
      Promise.resolve(
        path.includes("/salary/setup")
          ? { ...setup, pay_basis: "DAILY_WAGE" }
          : path.includes("salary-structures")
            ? [standard]
            : components,
      ),
    );
    render(
      <SalarySetupEditor
        employeeId="emp-1"
        today="2026-09-24"
        onSaved={vi.fn()}
        fallback={<p>daily card</p>}
      />,
    );
    expect(await screen.findByText("daily card")).toBeInTheDocument();
  });
});
