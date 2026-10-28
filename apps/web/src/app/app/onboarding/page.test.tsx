import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const push = vi.fn();
vi.mock("next/navigation", () => ({
  useParams: () => ({ id: "case-1" }),
  useRouter: () => ({ push }),
}));
vi.mock("next/link", () => ({
  default: ({ href, children }: { href: string; children: React.ReactNode }) => <a href={href}>{children}</a>,
}));
vi.mock("@/components/common/toast", () => ({ useToast: () => ({ toast: vi.fn() }) }));
vi.mock("@/lib/api/client", () => ({
  apiClient: { get: vi.fn(), getList: vi.fn(), post: vi.fn() },
}));
vi.mock("@/lib/auth/use-permissions", () => ({
  usePermissions: () => ({
    can: (c: string) => ["ONBOARDING.CREATE", "ONBOARDING.VIEW"].includes(c),
    canAny: () => false,
    permissions: new Set(),
  }),
}));
vi.mock("@/lib/auth/auth-context", () => ({ useAuth: () => ({ user: { id: "u1" } }) }));

import OnboardingCaseDetailPage from "@/app/app/onboarding/[id]/page";
import OnboardingPage from "@/app/app/onboarding/page";
import { apiClient } from "@/lib/api/client";

const detail = {
  id: "case-1", company_id: "co", status: "DRAFT", candidate_first_name: "Asha", candidate_last_name: null,
  personal_email: "asha@personal.example", personal_mobile: null, designation_id: null, department_id: null,
  branch_id: null, legal_entity_id: null, proposed_joining_date: "2027-01-15", created_by_user_id: "u1",
  employee_id: null, version: 1, created_at: "", updated_at: "", token_status: null, token_expires_at: null,
  section_reviews: [], personal_info: {}, address_info: {}, emergency_contact: {}, bank_info: {},
  statutory_info: {}, compensation_info: {}, previous_employment_info: {}, education_info: {}, nominee_info: {},
};
const compose = {
  candidate_name: "Asha", recipient_email: "asha@personal.example", company_name: "Acme", designation: null,
  department: null, proposed_joining_date: "2027-01-15", link_valid_days: 7, has_active_link: false,
  active_link_expires_at: null, invitable: true, default_subject: "Welcome", default_body: "Hello", placeholders: [],
};

beforeEach(() => {
  push.mockReset();
  vi.mocked(apiClient.getList).mockResolvedValue({
    data: [{ ...detail }],
    pagination: { page: 1, per_page: 20, total: 1, total_pages: 1 },
  } as never);
  vi.mocked(apiClient.get).mockImplementation(async (url: string) => {
    if (url === "/onboarding-cases/case-1") return detail;
    if (url === "/onboarding-cases/case-1/invitation/compose") return compose;
    return [];
  });
  vi.mocked(apiClient.post).mockResolvedValue(detail);
});
afterEach(() => {
  window.history.replaceState(null, "", "/");
  vi.mocked(apiClient.get).mockReset();
  vi.mocked(apiClient.getList).mockReset();
  vi.mocked(apiClient.post).mockReset();
});

describe("Onboarding create flow", () => {
  it("create → navigate with compose=1 → composer opens; only the create request is posted", async () => {
    const { unmount } = render(<OnboardingPage />);
    fireEvent.click((await screen.findAllByRole("button", { name: /start onboarding/i }))[0]);
    fireEvent.change(await screen.findByLabelText(/first name/i), { target: { value: "Asha" } });
    fireEvent.change(screen.getByLabelText(/personal email/i), { target: { value: "asha@personal.example" } });
    fireEvent.change(screen.getByLabelText(/proposed joining date/i), { target: { value: "2027-01-15" } });
    fireEvent.click(screen.getByRole("button", { name: "Start onboarding" }));

    await waitFor(() => expect(push).toHaveBeenCalledWith("/app/onboarding/case-1?compose=1"));
    expect(apiClient.post).toHaveBeenCalledTimes(1);
    expect(vi.mocked(apiClient.post).mock.calls[0][0]).toBe("/onboarding-cases");
    unmount();

    // The router would now render the detail route at the pushed URL.
    window.history.replaceState(null, "", "/app/onboarding/case-1?compose=1");
    render(<OnboardingCaseDetailPage />);
    expect(await screen.findByText(/no email has been sent yet/i)).toBeInTheDocument();
    // nothing is sent just because the composer opened
    expect(
      vi.mocked(apiClient.post).mock.calls.some(([url]) => String(url).includes("send-invite")),
    ).toBe(false);
  });
});
