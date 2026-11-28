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

// Covered by welcome-setup-dialog.test.tsx; it needs the app router, which this page test lacks.
vi.mock("@/components/company/welcome-setup-dialog", () => ({
  WelcomeSetupDialog: () => null,
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

const checklist = (complete: number) => ({
  items: [],
  required_total: 4,
  required_complete: complete,
  next_code: complete < 4 ? "SHIFT" : null,
});

/** Answers by path so the order the hooks fire in does not matter. */
function mockCalls(
  dash: unknown,
  prof: unknown,
  behavior: "resolve" | "reject" = "resolve",
  setup: unknown = checklist(1),
) {
  mockedGet.mockImplementation(((path: string) => {
    if (path === "/companies/current/setup-checklist") return Promise.resolve(setup);
    const result = path === "/dashboards/company" ? dash : prof;
    return behavior === "reject" ? Promise.reject(result) : Promise.resolve(result);
  }) as never);
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
    expect(await screen.findByText("1 of 4 essentials done")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open setup" })).toHaveAttribute("href", "/app/setup");
  });

  it("hides the setup banner once setup is complete", async () => {
    mockCalls(dashboard, profile, "resolve", checklist(4));
    render(<CompanyDashboardPage />);

    await screen.findByTestId("overview");
    await new Promise((resolve) => setTimeout(resolve, 20));
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
