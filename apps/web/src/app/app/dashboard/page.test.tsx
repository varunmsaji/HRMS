import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/auth/auth-context", () => ({
  useAuth: () => ({ session: { companyId: "company-1", accessToken: "token", companies: [] } }),
}));

vi.mock("@/lib/api/client", () => ({
  apiClient: { get: vi.fn() },
}));

// The body is covered by dashboard-overview.test.tsx; here only the page chrome is under test.
vi.mock("@/components/dashboard/dashboard-overview", () => ({
  DashboardOverview: () => <div data-testid="overview" />,
}));

import CompanyDashboardPage from "@/app/app/dashboard/page";
import { apiClient } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import type { CompanyDashboardSummary, CompanyProfile } from "@/lib/company/types";

const mockedGet = vi.mocked(apiClient.get);

const dashboard: CompanyDashboardSummary = {
  setup_progress: { status: "IN_PROGRESS", steps_completed: 1, steps_total: 4 },
  subscription: null,
  branch_count: null,
  department_count: null,
  employee_count: null,
};

const profile = {
  id: "company-1",
  name: "Acme Manufacturing",
  timezone: "Asia/Kolkata",
  locale: { language_code: "en-IN", date_format: "DD/MM/YYYY" },
} as CompanyProfile;

/** `useApiResource` fires one GET per hook instance in mount order: dashboard, then profile. */
function mockCalls(dash: unknown, prof: unknown, behavior: "resolve" | "reject" = "resolve") {
  for (const result of [dash, prof]) {
    if (behavior === "reject") mockedGet.mockRejectedValueOnce(result);
    else mockedGet.mockResolvedValueOnce(result);
  }
}

describe("CompanyDashboardPage", () => {
  afterEach(() => {
    mockedGet.mockReset();
  });

  it("shows a loading state before the responses resolve", () => {
    mockedGet.mockImplementation(() => new Promise(() => {}));
    render(<CompanyDashboardPage />);
    expect(screen.getByRole("status")).toBeInTheDocument();
  });

  it("renders the title, company name and the overview once loaded", async () => {
    mockCalls(dashboard, profile);
    render(<CompanyDashboardPage />);

    expect(await screen.findByTestId("overview")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Dashboard" })).toBeInTheDocument();
    expect(screen.getByText(/in Acme Manufacturing today/)).toBeInTheDocument();
  });

  it("shows setup progress while setup is incomplete", async () => {
    mockCalls(dashboard, profile);
    render(<CompanyDashboardPage />);

    expect(await screen.findByText("Finish setting up Acme Manufacturing")).toBeInTheDocument();
    expect(screen.getByText("1 of 4 steps complete")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open setup" })).toHaveAttribute("href", "/app/setup");
  });

  it("hides the setup banner once setup is complete", async () => {
    mockCalls({ ...dashboard, setup_progress: { status: "COMPLETE", steps_completed: 4, steps_total: 4 } }, profile);
    render(<CompanyDashboardPage />);

    await screen.findByTestId("overview");
    expect(screen.queryByText(/Finish setting up/)).not.toBeInTheDocument();
  });

  it("shows a permission message on 403", async () => {
    mockCalls(
      new ApiError({ status: 403, code: "FORBIDDEN", message: "Forbidden" }),
      profile,
      "reject",
    );
    render(<CompanyDashboardPage />);

    expect(
      await screen.findByText("You do not have permission to view the company dashboard."),
    ).toBeInTheDocument();
    expect(screen.queryByTestId("overview")).not.toBeInTheDocument();
  });
});
