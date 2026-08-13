import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/auth/auth-context", () => ({
  useAuth: () => ({ session: { companyId: "company-1", accessToken: "token", companies: [] } }),
}));

vi.mock("@/lib/api/client", () => ({
  apiClient: { get: vi.fn() },
}));

import CompanyDashboardPage from "@/app/app/dashboard/page";
import { apiClient } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import type { CompanyDashboardSummary, CompanyProfile, SubscriptionSummary } from "@/lib/company/types";

const mockedGet = vi.mocked(apiClient.get);

const dashboard: CompanyDashboardSummary = {
  setup_progress: { status: "IN_PROGRESS", steps_completed: 0, steps_total: 1 },
  subscription: { plan_code: "FREE", status: "TRIALING", trial_ends_at: "2026-08-21T00:00:00Z" },
  branch_count: null,
  department_count: null,
  employee_count: null,
};

const subscription: SubscriptionSummary = {
  plan: { code: "FREE", name: "Free" },
  status: "TRIALING",
  current_period_start: null,
  current_period_end: null,
  trial_ends_at: "2026-08-21T00:00:00Z",
  seat_limit: 5,
  features: [
    { code: "EMPLOYEE_SEATS", is_enabled: true, source: "PLAN", limit_value: 5 },
    { code: "BETA_PAYROLL_V2", is_enabled: true, source: "COMPANY_OVERRIDE", limit_value: null },
  ],
};

const profile: CompanyProfile = {
  id: "company-1",
  name: "Acme Manufacturing",
  legal_name: null,
  registration_number: null,
  subdomain: null,
  contact: { email: null, phone: null, website: null },
  address: {
    line1: null,
    line2: null,
    city: null,
    state: null,
    postal_code: null,
    country_code: null,
  },
  industry_code: null,
  company_size: null,
  country_code: "IN",
  currency: "INR",
  timezone: "Asia/Kolkata",
  locale: { language_code: "en-IN", date_format: "DD/MM/YYYY" },
  fiscal_year: { start_month: 4 },
  working_days: [],
  business_hours: null,
  branding: { logo_url: null, theme: null },
  status: "TRIAL",
  primary_legal_entity: null,
  onboarded_at: null,
  trial_ends_at: "2026-08-21T00:00:00Z",
  version: 1,
};

/** `useApiResource` fires one GET per hook instance in mount order: dashboard, subscription, profile. */
function mockThreeCalls(
  results: [unknown, unknown, unknown],
  behavior: "resolve" | "reject" = "resolve",
) {
  for (const result of results) {
    if (behavior === "reject") {
      mockedGet.mockRejectedValueOnce(result);
    } else {
      mockedGet.mockResolvedValueOnce(result);
    }
  }
}

describe("CompanyDashboardPage", () => {
  afterEach(() => {
    mockedGet.mockReset();
  });

  it("shows a loading state before the responses resolve", async () => {
    mockedGet.mockImplementation(() => new Promise(() => {}));
    render(<CompanyDashboardPage />);
    expect(screen.getByRole("status")).toBeInTheDocument();
  });

  it("renders plan, status, trial, seat limit, and features on success", async () => {
    mockThreeCalls([dashboard, subscription, profile]);
    render(<CompanyDashboardPage />);

    const expectedTrialDate = new Date(subscription.trial_ends_at as string).toLocaleDateString(
      undefined,
      { year: "numeric", month: "short", day: "numeric" },
    );

    expect(await screen.findByText("Acme Manufacturing")).toBeInTheDocument();
    expect(screen.getByText("Free (FREE)")).toBeInTheDocument();
    expect(screen.getAllByText("TRIALING").length).toBeGreaterThan(0);
    expect(screen.getByText(expectedTrialDate)).toBeInTheDocument();
    expect(screen.getAllByText("5").length).toBeGreaterThan(0);
  });

  it("renders effective feature flags with their source and state", async () => {
    mockThreeCalls([dashboard, subscription, profile]);
    render(<CompanyDashboardPage />);

    await screen.findByText("Acme Manufacturing");
    expect(screen.getByText("EMPLOYEE_SEATS")).toBeInTheDocument();
    expect(screen.getByText("BETA_PAYROLL_V2")).toBeInTheDocument();
    expect(screen.getByText("company override")).toBeInTheDocument();
    // EMPLOYEE_SEATS has a limit value appended to its enabled state in the same node.
    expect(screen.getByText("On · 5")).toBeInTheDocument();
    expect(screen.getByText("On")).toBeInTheDocument();
  });

  it("shows the empty-subscription message when the company has no live subscription", async () => {
    const dashboardNoSub: CompanyDashboardSummary = { ...dashboard, subscription: null };
    mockedGet.mockResolvedValueOnce(dashboardNoSub);
    mockedGet.mockRejectedValueOnce(
      new ApiError({ status: 404, code: "NOT_FOUND", message: "Not found" }),
    );
    mockedGet.mockResolvedValueOnce(profile);

    render(<CompanyDashboardPage />);

    expect(await screen.findByText("Acme Manufacturing")).toBeInTheDocument();
    expect(screen.getByText("No live subscription is available.")).toBeInTheDocument();
    expect(screen.getByText("No live subscription")).toBeInTheDocument();
  });

  it("shows an error state when the dashboard request fails", async () => {
    mockedGet.mockRejectedValueOnce(
      new ApiError({ status: 500, code: "INTERNAL_ERROR", message: "Boom" }),
    );
    mockedGet.mockResolvedValueOnce(subscription);
    mockedGet.mockResolvedValueOnce(profile);

    render(<CompanyDashboardPage />);

    expect(await screen.findByText("Boom")).toBeInTheDocument();
  });

  it("shows a permission-specific message on 403", async () => {
    mockThreeCalls(
      [
        new ApiError({ status: 403, code: "PERMISSION_DENIED", message: "Forbidden" }),
        new ApiError({ status: 403, code: "PERMISSION_DENIED", message: "Forbidden" }),
        new ApiError({ status: 403, code: "PERMISSION_DENIED", message: "Forbidden" }),
      ],
      "reject",
    );

    render(<CompanyDashboardPage />);

    expect(
      await screen.findByText(/do not have permission to view the company dashboard/i),
    ).toBeInTheDocument();
  });

  it("retries all three resources (dashboard, subscription, profile) after an error", async () => {
    mockedGet.mockRejectedValueOnce(
      new ApiError({ status: 500, code: "INTERNAL_ERROR", message: "Boom" }),
    );
    mockedGet.mockResolvedValueOnce(subscription);
    mockedGet.mockResolvedValueOnce(profile);

    render(<CompanyDashboardPage />);
    await screen.findByText(/try again/i);

    mockThreeCalls([dashboard, subscription, profile]);
    screen.getByRole("button", { name: /try again/i }).click();

    // 3 initial calls (dashboard, subscription, profile) + 3 retried (all three).
    await waitFor(() => expect(mockedGet).toHaveBeenCalledTimes(6));
    expect(await screen.findByText("Acme Manufacturing")).toBeInTheDocument();
  });

  it("retries and recovers when only the profile request failed", async () => {
    // Dashboard and subscription succeed on the first attempt; only profile fails — this is
    // the regression case for the retry handler previously not retrying `profile` at all.
    mockedGet.mockResolvedValueOnce(dashboard);
    mockedGet.mockResolvedValueOnce(subscription);
    mockedGet.mockRejectedValueOnce(
      new ApiError({ status: 500, code: "INTERNAL_ERROR", message: "Profile boom" }),
    );

    render(<CompanyDashboardPage />);
    await screen.findByText(/profile boom/i);

    mockThreeCalls([dashboard, subscription, profile]);
    screen.getByRole("button", { name: /try again/i }).click();

    await waitFor(() => expect(mockedGet).toHaveBeenCalledTimes(6));
    expect(await screen.findByText("Acme Manufacturing")).toBeInTheDocument();
    expect(screen.queryByText(/profile boom/i)).not.toBeInTheDocument();
  });
});
