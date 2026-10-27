import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({ useParams: () => ({ id: "case-1" }) }));
vi.mock("next/link", () => ({
  default: ({ href, children }: { href: string; children: React.ReactNode }) => <a href={href}>{children}</a>,
}));
vi.mock("@/components/common/toast", () => ({ useToast: () => ({ toast: vi.fn() }) }));
vi.mock("@/lib/api/client", () => ({ apiClient: { get: vi.fn(), post: vi.fn() } }));

let permissions: string[] = [];
vi.mock("@/lib/auth/use-permissions", () => ({
  usePermissions: () => ({ can: (c: string) => permissions.includes(c), canAny: () => false, permissions: new Set() }),
}));
vi.mock("@/lib/auth/auth-context", () => ({ useAuth: () => ({ user: { id: "u1" } }) }));

import OnboardingCaseDetailPage from "@/app/app/onboarding/[id]/page";
import { apiClient } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";

const detail = {
  id: "case-1", company_id: "co", status: "DRAFT", candidate_first_name: "Asha", candidate_last_name: "Rao",
  personal_email: "asha@personal.example", personal_mobile: null, designation_id: null, department_id: null,
  branch_id: null, legal_entity_id: null, proposed_joining_date: "2027-01-15", created_by_user_id: "u1",
  employee_id: null, version: 1, created_at: "", updated_at: "", token_status: null, token_expires_at: null,
  section_reviews: [], personal_info: {}, address_info: {}, emergency_contact: {}, bank_info: {},
  statutory_info: {}, compensation_info: {}, previous_employment_info: {}, education_info: {}, nominee_info: {},
};

function route(overrides: Record<string, unknown> = {}) {
  vi.mocked(apiClient.get).mockImplementation(async (url: string) => {
    if (url in overrides) {
      const v = overrides[url];
      if (v instanceof Error) throw v;
      return v;
    }
    if (url === "/onboarding-cases/case-1") return detail;
    if (url.endsWith("/messages") || url.endsWith("/documents")) return [];
    return [];
  });
}

beforeEach(() => route());
afterEach(() => {
  vi.mocked(apiClient.get).mockReset();
  vi.mocked(apiClient.post).mockReset();
  permissions = [];
});

describe("Onboarding case detail - invitation", () => {
  it("shows Compose Invitation only to users who can create onboarding", async () => {
    permissions = ["ONBOARDING.CREATE", "ONBOARDING.VIEW"];
    const { unmount } = render(<OnboardingCaseDetailPage />);
    expect(await screen.findByRole("button", { name: "Compose Invitation" })).toBeInTheDocument();
    unmount();

    permissions = ["ONBOARDING.VIEW"];
    render(<OnboardingCaseDetailPage />);
    await screen.findByText(/invitation emails/i);
    expect(screen.queryByRole("button", { name: /compose invitation|resend invitation/i })).not.toBeInTheDocument();
  });

  it("never sends an invitation just because the page was opened", async () => {
    permissions = ["ONBOARDING.CREATE", "ONBOARDING.VIEW"];
    render(<OnboardingCaseDetailPage />);
    await screen.findByRole("button", { name: "Compose Invitation" });
    await waitFor(() => expect(apiClient.get).toHaveBeenCalled());
    expect(apiClient.post).not.toHaveBeenCalled();
  });

  it("shows an error, not another tenant's data, when the case is not found", async () => {
    permissions = ["ONBOARDING.CREATE", "ONBOARDING.VIEW"];
    route({ "/onboarding-cases/case-1": new ApiError({ status: 404, code: "NOT_FOUND", message: "Resource not found" }) });
    render(<OnboardingCaseDetailPage />);
    expect(await screen.findByText(/could not be found/i)).toBeInTheDocument();
    expect(screen.queryByText("asha@personal.example")).not.toBeInTheDocument();
  });

  it("keeps review actions gated by their own permissions", async () => {
    permissions = ["ONBOARDING.VIEW", "ONBOARDING.CREATE"];
    route({ "/onboarding-cases/case-1": { ...detail, status: "VERIFIED" } });
    render(<OnboardingCaseDetailPage />);
    await screen.findByText(/invitation emails/i);
    expect(screen.queryByRole("button", { name: "Activate" })).not.toBeInTheDocument();
  });
});
