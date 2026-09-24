import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api/client", () => ({
  apiClient: { get: vi.fn(), post: vi.fn(), patch: vi.fn() },
}));

import { StatutoryRateDialog } from "@/components/payroll/statutory-rate-dialog";
import { apiClient } from "@/lib/api/client";
import type { StatutoryRate } from "@/lib/payroll/types";

const mockedPost = vi.mocked(apiClient.post);
const mockedPatch = vi.mocked(apiClient.patch);

const pfRate: StatutoryRate = {
  id: "rate-pf",
  company_id: "company-1",
  scheme: "PF",
  state_code: null,
  effective_from: "2014-09-01",
  effective_to: null,
  parameters: {
    employee_percent: "12",
    employer_percent: "12",
    eps_percent: "8.33",
    wage_ceiling_minor: 1_500_000,
    edli_percent: "0.5",
    admin_percent: "0.5",
    eps_age_limit: 58,
  },
  notes: null,
  is_seeded: true,
  verified: false,
  verified_at: null,
  verified_by_user_id: null,
  version: 2,
  created_at: "2026-09-24T00:00:00Z",
  updated_at: "2026-09-24T00:00:00Z",
};

describe("StatutoryRateDialog", () => {
  afterEach(() => vi.clearAllMocks());

  it("creates a professional tax rate with a February instalment", async () => {
    mockedPost.mockResolvedValue({});
    const onSaved = vi.fn();
    const user = userEvent.setup();
    render(<StatutoryRateDialog open rate={null} onOpenChange={vi.fn()} onSaved={onSaved} />);

    await user.type(screen.getByLabelText(/State code/), "tn");
    await user.type(screen.getByLabelText(/Effective from/), "2026-10-01");
    await user.clear(screen.getByLabelText("From ₹"));
    await user.type(screen.getByLabelText("From ₹"), "21000");
    await user.clear(screen.getByLabelText("Tax ₹"));
    await user.type(screen.getByLabelText("Tax ₹"), "200");
    await user.selectOptions(screen.getByLabelText("Except in"), "2");
    await user.type(screen.getByLabelText("Then ₹"), "300");
    await user.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() =>
      expect(mockedPost).toHaveBeenCalledWith("/payroll/statutory-rates", {
        scheme: "PT",
        state_code: "TN",
        effective_from: "2026-10-01",
        parameters: {
          slabs: [
            { min_minor: 2_100_000, max_minor: null, amount_minor: 20_000, month_amounts: { "2": 30_000 } },
          ],
        },
        notes: null,
      }),
    );
    expect(onSaved).toHaveBeenCalled();
  });

  it("corrects a PF rate in place, sending its version", async () => {
    mockedPatch.mockResolvedValue({});
    const user = userEvent.setup();
    render(<StatutoryRateDialog open rate={pfRate} onOpenChange={vi.fn()} onSaved={vi.fn()} />);

    const ceiling = screen.getByLabelText(/Wage ceiling/);
    expect(ceiling).toHaveValue("15000");
    await user.clear(ceiling);
    await user.type(ceiling, "21000");
    await user.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() =>
      expect(mockedPatch).toHaveBeenCalledWith(
        "/payroll/statutory-rates/rate-pf",
        {
          parameters: { ...pfRate.parameters, wage_ceiling_minor: 2_100_000 },
          notes: null,
        },
        { ifMatch: "2" },
      ),
    );
  });

  it("refuses a percentage that is not a number", async () => {
    const user = userEvent.setup();
    render(<StatutoryRateDialog open rate={pfRate} onOpenChange={vi.fn()} onSaved={vi.fn()} />);
    const employee = screen.getByLabelText(/Employee contribution/);
    await user.clear(employee);
    await user.type(employee, "twelve");
    await user.click(screen.getByRole("button", { name: "Save" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/must be a percentage/);
    expect(mockedPatch).not.toHaveBeenCalled();
  });
});
