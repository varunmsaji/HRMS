import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

let mockUser: { company_status?: string } | null = null;
vi.mock("@/lib/auth/auth-context", () => ({
  useAuth: () => ({ session: { companyId: "company-1", accessToken: "token" }, user: mockUser }),
}));

const toastMock = vi.fn();
vi.mock("@/components/common/toast", () => ({
  useToast: () => ({ toast: toastMock }),
}));

vi.mock("@/lib/api/client", () => ({
  apiClient: { get: vi.fn(), patch: vi.fn() },
}));

import CompanyProfilePage from "@/app/app/company/page";
import { apiClient } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import type { CompanyProfile } from "@/lib/company/types";

const mockedGet = vi.mocked(apiClient.get);
const mockedPatch = vi.mocked(apiClient.patch);

const sampleProfile: CompanyProfile = {
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
  industry_code: "MANUFACTURING",
  company_size: "51-200",
  country_code: "IN",
  currency: "INR",
  timezone: "Asia/Kolkata",
  locale: { language_code: "en-IN", date_format: "DD/MM/YYYY" },
  fiscal_year: { start_month: 4 },
  working_days: [
    { day: "MON", is_working: true, is_alternate: false },
    { day: "TUE", is_working: true, is_alternate: false },
    { day: "WED", is_working: true, is_alternate: false },
    { day: "THU", is_working: true, is_alternate: false },
    { day: "FRI", is_working: true, is_alternate: false },
    { day: "SAT", is_working: false, is_alternate: false },
    { day: "SUN", is_working: false, is_alternate: false },
  ],
  business_hours: null,
  branding: { logo_url: null, theme: null },
  status: "TRIAL",
  primary_legal_entity: null,
  onboarded_at: null,
  trial_ends_at: "2026-08-21T00:00:00Z",
  version: 1,
};

describe("CompanyProfilePage", () => {
  afterEach(() => {
    mockedGet.mockReset();
    mockedPatch.mockReset();
    toastMock.mockReset();
    mockUser = null;
  });

  it("loads and renders the company profile", async () => {
    mockedGet.mockResolvedValueOnce(sampleProfile);

    render(<CompanyProfilePage />);

    expect(await screen.findByText("Acme Manufacturing")).toBeInTheDocument();
    expect(screen.getAllByText("Not configured").length).toBeGreaterThan(0);
    expect(screen.getByText("TRIAL")).toBeInTheDocument();
  });

  it("shows empty-state labels for null profile fields", async () => {
    mockedGet.mockResolvedValueOnce(sampleProfile);
    render(<CompanyProfilePage />);
    await screen.findByText("Acme Manufacturing");
    expect(screen.getAllByText("Not configured").length).toBeGreaterThan(0);
  });

  it("enters edit mode and restores values on cancel", async () => {
    mockedGet.mockResolvedValueOnce(sampleProfile);
    const user = userEvent.setup();
    render(<CompanyProfilePage />);

    await user.click(await screen.findByRole("button", { name: /edit/i }));
    const legalNameInput = screen.getByLabelText(/legal name/i);
    await user.clear(legalNameInput);
    await user.type(legalNameInput, "Acme Private Limited");
    await user.click(screen.getByRole("button", { name: /cancel/i }));

    expect(screen.queryByLabelText(/legal name/i)).not.toBeInTheDocument();
    expect(screen.getByText("Acme Manufacturing")).toBeInTheDocument();
  });

  it("saves changes with the current If-Match version", async () => {
    mockedGet.mockResolvedValueOnce(sampleProfile);
    mockedPatch.mockResolvedValueOnce({ ...sampleProfile, legal_name: "Acme Private Limited", version: 2 });

    const user = userEvent.setup();
    render(<CompanyProfilePage />);

    await user.click(await screen.findByRole("button", { name: /edit/i }));
    await user.type(screen.getByLabelText(/legal name/i), "Acme Private Limited");
    await user.click(screen.getByRole("button", { name: /save changes/i }));

    await waitFor(() => expect(mockedPatch).toHaveBeenCalledTimes(1));
    expect(mockedPatch).toHaveBeenCalledWith(
      "/companies/current",
      { legal_name: "Acme Private Limited" },
      { ifMatch: "1" },
    );
    expect(toastMock).toHaveBeenCalledWith(expect.objectContaining({ variant: "success" }));
  });

  it("shows stale-resource actions on 409 STALE_RESOURCE", async () => {
    mockedGet.mockResolvedValueOnce(sampleProfile);
    mockedPatch.mockRejectedValueOnce(
      new ApiError({
        status: 409,
        code: "STALE_RESOURCE",
        message: "Stale",
        details: [
          {
            code: "STALE_RESOURCE",
            message: "Stale",
            context: { current: { ...sampleProfile, version: 2 } },
          },
        ],
      }),
    );

    const user = userEvent.setup();
    render(<CompanyProfilePage />);

    await user.click(await screen.findByRole("button", { name: /edit/i }));
    await user.type(screen.getByLabelText(/legal name/i), "Changed");
    await user.click(screen.getByRole("button", { name: /save changes/i }));

    expect(
      await screen.findByText(/company profile was changed by someone else/i),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /reload latest profile/i })).toBeInTheDocument();
  });

  it("shows an error state when loading fails with forbidden", async () => {
    mockedGet.mockRejectedValueOnce(
      new ApiError({ status: 403, code: "PERMISSION_DENIED", message: "Forbidden" }),
    );

    render(<CompanyProfilePage />);

    expect(
      await screen.findByText(/do not have permission to view this company profile/i),
    ).toBeInTheDocument();
  });

  it("shows the company code up front with a copy button", async () => {
    mockedGet.mockResolvedValueOnce({ ...sampleProfile, login_code: "ACME42" });
    render(<CompanyProfilePage />);

    expect(await screen.findByText("ACME42")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /copy code/i })).toBeInTheDocument();
    expect(screen.getByText(/employees who sign in with their employee id/i)).toBeInTheDocument();
  });

  it("switches Edit off while the company is awaiting approval", async () => {
    mockUser = { company_status: "PENDING_APPROVAL" };
    mockedGet.mockResolvedValueOnce(sampleProfile);
    render(<CompanyProfilePage />);

    expect(await screen.findByRole("button", { name: /edit/i })).toBeDisabled();
  });

  it("puts each server validation error on its own field, including contact and address", async () => {
    mockedGet.mockResolvedValueOnce(sampleProfile);
    mockedPatch.mockRejectedValueOnce(
      new ApiError({
        status: 422,
        code: "VALIDATION_ERROR",
        message: "Invalid",
        details: [
          { code: "x", field: "body.contact.website", message: "Website must be a URL." },
          { code: "x", field: "body.address.postal_code", message: "Postal code is too long." },
        ],
      }),
    );
    const user = userEvent.setup();
    render(<CompanyProfilePage />);

    await user.click(await screen.findByRole("button", { name: /edit/i }));
    await user.type(screen.getByLabelText(/legal name/i), "Changed");
    await user.click(screen.getByRole("button", { name: /save changes/i }));

    expect(await screen.findByText("Website must be a URL.")).toBeInTheDocument();
    expect(screen.getByText("Postal code is too long.")).toBeInTheDocument();
    expect(screen.getByText(/some details need fixing/i)).toBeInTheDocument();
  });

  it("shows the server's message when a validation error maps to no field", async () => {
    mockedGet.mockResolvedValueOnce(sampleProfile);
    mockedPatch.mockRejectedValueOnce(
      new ApiError({
        status: 422,
        code: "VALIDATION_ERROR",
        message: "Something about the plan limit.",
        details: [{ code: "x", field: "body.unknown_thing", message: "Nope" }],
      }),
    );
    const user = userEvent.setup();
    render(<CompanyProfilePage />);

    await user.click(await screen.findByRole("button", { name: /edit/i }));
    await user.type(screen.getByLabelText(/legal name/i), "Changed");
    await user.click(screen.getByRole("button", { name: /save changes/i }));

    expect(await screen.findByRole("alert")).toBeInTheDocument();
  });

  it("checks the email address before sending", async () => {
    mockedGet.mockResolvedValueOnce(sampleProfile);
    const user = userEvent.setup();
    render(<CompanyProfilePage />);

    await user.click(await screen.findByRole("button", { name: /edit/i }));
    await user.type(screen.getByLabelText(/^email$/i), "not-an-email");
    await user.click(screen.getByRole("button", { name: /save changes/i }));

    expect(await screen.findByText("Enter a valid email address.")).toBeInTheDocument();
    expect(mockedPatch).not.toHaveBeenCalled();
  });

  it("keeps the profile on screen when a save is refused with 403", async () => {
    mockedGet.mockResolvedValueOnce(sampleProfile);
    mockedPatch.mockRejectedValueOnce(
      new ApiError({
        status: 403,
        code: "COMPANY_PENDING_APPROVAL",
        message: "Your company is awaiting approval.",
      }),
    );
    const user = userEvent.setup();
    render(<CompanyProfilePage />);

    await user.click(await screen.findByRole("button", { name: /edit/i }));
    await user.type(screen.getByLabelText(/legal name/i), "Changed");
    await user.click(screen.getByRole("button", { name: /save changes/i }));

    await waitFor(() =>
      expect(toastMock).toHaveBeenCalledWith(
        expect.objectContaining({ title: "Changes are switched off for this company" }),
      ),
    );
    expect(screen.getByLabelText(/legal name/i)).toBeInTheDocument();
    expect(screen.queryByText(/do not have permission to view this company profile/i)).not.toBeInTheDocument();
  });
});
