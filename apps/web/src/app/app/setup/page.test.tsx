import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api/client", () => ({
  apiClient: { get: vi.fn() },
}));

import CompanySetupPage from "@/app/app/setup/page";
import { apiClient } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import type { CompanySetupProgressSummary } from "@/lib/company/types";

const mockedGet = vi.mocked(apiClient.get);

const incompleteProgress: CompanySetupProgressSummary = {
  status: "IN_PROGRESS",
  current_step: "COMPANY_PROFILE",
  steps: [{ code: "COMPANY_PROFILE", label: "Company Profile", is_complete: false }],
  started_at: "2026-08-10T00:00:00Z",
  completed_at: null,
};

const completeProgress: CompanySetupProgressSummary = {
  status: "COMPLETE",
  current_step: null,
  steps: [{ code: "COMPANY_PROFILE", label: "Company Profile", is_complete: true }],
  started_at: "2026-08-10T00:00:00Z",
  completed_at: "2026-08-10T00:05:00Z",
};

const partialProgress: CompanySetupProgressSummary = {
  status: "IN_PROGRESS",
  current_step: "BRANCHES",
  steps: [
    { code: "COMPANY_PROFILE", label: "Company Profile", is_complete: true },
    { code: "BRANCHES", label: "Branches", is_complete: false },
  ],
  started_at: "2026-08-10T00:00:00Z",
  completed_at: null,
};

/** The page also asks for the live checklist, which these tests do not cover; answer only the
 * progress path so each mock below cannot be consumed by the wrong request. */
function answer(result: unknown, fail = false) {
  mockedGet.mockImplementation(((path: string) => {
    if (path === "/companies/current/setup-checklist") return Promise.reject(new Error("n/a"));
    return fail ? Promise.reject(result) : Promise.resolve(result);
  }) as never);
}

describe("CompanySetupPage", () => {
  afterEach(() => {
    mockedGet.mockReset();
  });

  it("shows a loading state before the response resolves", async () => {
    mockedGet.mockImplementation(() => new Promise(() => {}));
    render(<CompanySetupPage />);
    expect(screen.getByRole("status")).toBeInTheDocument();
  });

  it("renders an incomplete setup with a next-step call to action", async () => {
    answer(incompleteProgress);
    render(<CompanySetupPage />);

    expect(await screen.findByText("Company Profile")).toBeInTheDocument();
    expect(screen.getByText("Pending")).toBeInTheDocument();
    expect(screen.getByText("0 of 1 registration steps done")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /go to company profile/i })).toHaveAttribute(
      "href",
      "/app/company",
    );
  });

  it("renders a partially completed setup with per-step status", async () => {
    answer(partialProgress);
    render(<CompanySetupPage />);

    await screen.findByText("Company Profile");
    expect(screen.getByText("Branches")).toBeInTheDocument();
    expect(screen.getByText("1 of 2 registration steps done")).toBeInTheDocument();
    expect(screen.getAllByText("Complete")).toHaveLength(1);
    expect(screen.getAllByText("Pending")).toHaveLength(1);
  });

  it("renders a fully completed setup with no next-step action", async () => {
    answer(completeProgress);
    render(<CompanySetupPage />);

    expect(await screen.findByText("Registration complete")).toBeInTheDocument();
    expect(screen.getByText("Complete")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /go to company profile/i })).not.toBeInTheDocument();
  });

  it("shows an error state on API failure", async () => {
    answer(
      new ApiError({ status: 500, code: "INTERNAL_ERROR", message: "Boom" }),
      true,
    );
    render(<CompanySetupPage />);

    expect(await screen.findByText("Boom")).toBeInTheDocument();
  });

  it("shows a permission-specific message on 403", async () => {
    answer(
      new ApiError({ status: 403, code: "PERMISSION_DENIED", message: "Forbidden" }),
      true,
    );
    render(<CompanySetupPage />);

    expect(
      await screen.findByText(/do not have permission to view company setup progress/i),
    ).toBeInTheDocument();
  });

  it("retries loading after an error", async () => {
    answer(
      new ApiError({ status: 500, code: "INTERNAL_ERROR", message: "Boom" }),
      true,
    );
    render(<CompanySetupPage />);
    await screen.findByText(/try again/i);

    answer(completeProgress);
    screen.getByRole("button", { name: /try again/i }).click();

    await waitFor(() =>
      expect(
        mockedGet.mock.calls.filter(([path]) => path === "/companies/current/setup-progress"),
      ).toHaveLength(2),
    );
    expect(await screen.findByText("Registration complete")).toBeInTheDocument();
  });
});
