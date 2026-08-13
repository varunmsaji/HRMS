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
    mockedGet.mockResolvedValueOnce(incompleteProgress);
    render(<CompanySetupPage />);

    expect(await screen.findByText("Company Profile")).toBeInTheDocument();
    expect(screen.getByText("Pending")).toBeInTheDocument();
    expect(screen.getByText("0 of 1 complete")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /go to company profile/i })).toHaveAttribute(
      "href",
      "/app/company",
    );
  });

  it("renders a partially completed setup with per-step status", async () => {
    mockedGet.mockResolvedValueOnce(partialProgress);
    render(<CompanySetupPage />);

    await screen.findByText("Company Profile");
    expect(screen.getByText("Branches")).toBeInTheDocument();
    expect(screen.getByText("1 of 2 complete")).toBeInTheDocument();
    expect(screen.getAllByText("Complete")).toHaveLength(1);
    expect(screen.getAllByText("Pending")).toHaveLength(1);
  });

  it("renders a fully completed setup with no next-step action", async () => {
    mockedGet.mockResolvedValueOnce(completeProgress);
    render(<CompanySetupPage />);

    expect(await screen.findByText("Setup complete")).toBeInTheDocument();
    expect(screen.getByText("Complete")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /go to company profile/i })).not.toBeInTheDocument();
  });

  it("shows an error state on API failure", async () => {
    mockedGet.mockRejectedValueOnce(
      new ApiError({ status: 500, code: "INTERNAL_ERROR", message: "Boom" }),
    );
    render(<CompanySetupPage />);

    expect(await screen.findByText("Boom")).toBeInTheDocument();
  });

  it("shows a permission-specific message on 403", async () => {
    mockedGet.mockRejectedValueOnce(
      new ApiError({ status: 403, code: "PERMISSION_DENIED", message: "Forbidden" }),
    );
    render(<CompanySetupPage />);

    expect(
      await screen.findByText(/do not have permission to view company setup progress/i),
    ).toBeInTheDocument();
  });

  it("retries loading after an error", async () => {
    mockedGet.mockRejectedValueOnce(
      new ApiError({ status: 500, code: "INTERNAL_ERROR", message: "Boom" }),
    );
    render(<CompanySetupPage />);
    await screen.findByText(/try again/i);

    mockedGet.mockResolvedValueOnce(completeProgress);
    screen.getByRole("button", { name: /try again/i }).click();

    await waitFor(() => expect(mockedGet).toHaveBeenCalledTimes(2));
    expect(await screen.findByText("Setup complete")).toBeInTheDocument();
  });
});
