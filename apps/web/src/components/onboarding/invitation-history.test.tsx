import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api/client", () => ({ apiClient: { get: vi.fn() } }));
vi.mock("@/lib/auth/auth-context", () => ({
  useAuth: () => ({ user: { company_timezone: "Asia/Kolkata" } }),
}));

import { InvitationHistory } from "@/components/onboarding/invitation-history";
import { apiClient } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import type { OnboardingMessage } from "@/lib/onboarding/types";

const msg = (over: Partial<OnboardingMessage>): OnboardingMessage => ({
  id: "m1", message_type: "INVITATION", recipient_email: "a@x.test", subject: "Welcome", body_text: "b",
  created_by_user_id: "u1", created_at: "2027-01-01T00:00:00Z", queued_at: "2027-01-01T00:00:00Z",
  status: "QUEUED", attempts: 0, last_attempt_at: null, provider_accepted_at: null, failed_at: null,
  failure_class: null, ...over,
});

afterEach(() => vi.mocked(apiClient.get).mockReset());

describe("InvitationHistory", () => {
  it("labels queued as Queued, never as delivered", async () => {
    vi.mocked(apiClient.get).mockResolvedValue([msg({})]);
    render(<InvitationHistory caseId="c" refreshKey={0} canResend onResend={vi.fn()} />);
    expect(await screen.findByTestId("message-status")).toHaveTextContent("Queued");
    expect(screen.queryByText(/delivered/i)).not.toBeInTheDocument();
  });

  it("provider acceptance does not claim inbox delivery", async () => {
    vi.mocked(apiClient.get).mockResolvedValue([msg({ status: "PROVIDER_ACCEPTED", provider_accepted_at: "2027-01-01T00:01:00Z" })]);
    render(<InvitationHistory caseId="c" refreshKey={0} canResend onResend={vi.fn()} />);
    expect(await screen.findByTestId("message-status")).toHaveTextContent("Accepted by mail provider");
    expect(screen.getByText(/does not confirm it reached the inbox/i)).toBeInTheDocument();
  });

  it("failed delivery offers a new invitation (not a silent retry); retrying does not", async () => {
    vi.mocked(apiClient.get).mockResolvedValue([msg({ id: "a", status: "FAILED" }), msg({ id: "b", status: "RETRYING", attempts: 1 })]);
    const onResend = vi.fn();
    render(<InvitationHistory caseId="c" refreshKey={0} canResend onResend={onResend} />);
    const buttons = await screen.findAllByRole("button", { name: /send new invitation/i });
    expect(buttons).toHaveLength(1);
    await userEvent.click(buttons[0]);
    expect(onResend).toHaveBeenCalled();
    expect(screen.getByText(/retried automatically with the same link/i)).toBeInTheDocument();
  });

  it("hides the resend action without permission", async () => {
    vi.mocked(apiClient.get).mockResolvedValue([msg({ status: "FAILED" })]);
    render(<InvitationHistory caseId="c" refreshKey={0} canResend={false} onResend={vi.fn()} />);
    await screen.findByTestId("message-status");
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it("handles empty, loading and error/permission states", async () => {
    vi.mocked(apiClient.get).mockResolvedValueOnce([]);
    const { unmount } = render(<InvitationHistory caseId="c" refreshKey={0} canResend onResend={vi.fn()} />);
    expect(screen.getByRole("status")).toHaveTextContent("Loading");
    expect(await screen.findByText(/no invitation has been sent yet/i)).toBeInTheDocument();
    unmount();
    vi.mocked(apiClient.get).mockRejectedValueOnce(new ApiError({ status: 403, code: "PERMISSION_DENIED", message: "x" }));
    render(<InvitationHistory caseId="c" refreshKey={0} canResend onResend={vi.fn()} />);
    expect(await screen.findByRole("alert")).toHaveTextContent(/don't have permission/i);
  });
});
