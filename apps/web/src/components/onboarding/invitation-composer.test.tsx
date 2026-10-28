import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api/client", () => ({ apiClient: { get: vi.fn(), post: vi.fn() } }));
vi.mock("@/lib/auth/auth-context", () => ({
  useAuth: () => ({ user: { company_timezone: "Asia/Kolkata" } }),
}));

import { InvitationComposer } from "@/components/onboarding/invitation-composer";
import { apiClient } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import type { InvitationCompose, OnboardingInvite } from "@/lib/onboarding/types";

const compose: InvitationCompose = {
  case_id: "c1",
  recipient_email: "asha@personal.example",
  candidate_name: "Asha Rao",
  company_name: "Acme",
  designation: null,
  department: null,
  proposed_joining_date: "2027-01-15",
  invitable: true,
  has_active_link: false,
  active_link_expires_at: null,
  link_valid_days: 7,
  default_subject: "Welcome to {{company_name}}",
  default_body: "Dear {{candidate_name}},\n\n{{onboarding_url}}",
  subject_max_length: 150,
  body_max_length: 5000,
  placeholders: [
    { key: "candidate_name", label: "Candidate full name", description: "", required: true, example: "" },
    { key: "designation", label: "Designation", description: "", required: false, example: "" },
    { key: "onboarding_url", label: "Secure onboarding link", description: "", required: true, example: "" },
  ],
};
const preview = { recipient_email: "asha@personal.example", subject: "Welcome to Acme", html_body: "<p>Dear Asha Rao,</p>", text_body: "x", link_is_placeholder: true };
const sent = { invite_url: "https://x/onboarding/T", email_queued: true } as unknown as OnboardingInvite;

const filled = {
  ...preview,
  subject: "Welcome to Acme",
  editable_body: "Dear Asha Rao,\n\n{{onboarding_url}}",
};

function setup(over: Partial<InvitationCompose> = {}) {
  vi.mocked(apiClient.get).mockResolvedValue({ ...compose, ...over });
  vi.mocked(apiClient.post).mockResolvedValue(filled);
  const onSent = vi.fn();
  const onOpenChange = vi.fn();
  render(<InvitationComposer open onOpenChange={onOpenChange} caseId="c1" onSent={onSent} />);
  return { onSent, onOpenChange, user: userEvent.setup() };
}

describe("InvitationComposer", () => {
  beforeEach(() => vi.mocked(apiClient.post).mockReset());
  afterEach(() => vi.mocked(apiClient.get).mockReset());

  it("shows the filled-in message to edit when there is no template choice", async () => {
    setup();
    expect(await screen.findByText(/asha@personal.example/)).toBeInTheDocument();
    expect(await screen.findByLabelText(/subject/i)).toHaveValue("Welcome to Acme");
    expect(screen.getByLabelText("Message")).toHaveValue(filled.editable_body);
    expect(vi.mocked(apiClient.post).mock.calls[0][0]).toBe("/onboarding-cases/c1/invitation/preview");
    expect(vi.mocked(apiClient.post).mock.calls.some((c) => c[0].endsWith("/send-invite"))).toBe(false);
  });

  it("sends the edited text once even on a double-click", async () => {
    const { user, onSent } = setup();
    const message = await screen.findByLabelText("Message");
    await user.type(message, " EDITED");
    let resolveSend: (v: OnboardingInvite) => void = () => {};
    vi.mocked(apiClient.post).mockReturnValueOnce(new Promise((r) => { resolveSend = r; }));
    await user.dblClick(screen.getByRole("button", { name: /send invitation/i }));
    resolveSend(sent);
    await waitFor(() => expect(onSent).toHaveBeenCalledWith(sent));
    const sends = vi.mocked(apiClient.post).mock.calls.filter((c) => c[0].endsWith("/send-invite"));
    expect(sends).toHaveLength(1);
    expect(sends[0][1]).toMatchObject({
      subject: "Welcome to Acme",
      body: `${filled.editable_body} EDITED`,
      send_request_id: expect.any(String),
    });
  });

  it("warns that sending revokes an existing live link", async () => {
    setup({ has_active_link: true, active_link_expires_at: "2027-01-01T00:00:00Z" });
    expect(await screen.findByText(/revokes the previous one/i)).toBeInTheDocument();
  });

  it("explains a permission-denied load and offers no send", async () => {
    vi.mocked(apiClient.get).mockRejectedValue(new ApiError({ status: 403, code: "PERMISSION_DENIED", message: "no" }));
    render(<InvitationComposer open onOpenChange={vi.fn()} caseId="c1" onSent={vi.fn()} />);
    expect(await screen.findByText(/don't have permission to send invitations/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /send invitation/i })).toBeDisabled();
  });

  it("surfaces a send failure and retries with the same request id", async () => {
    const { user } = setup();
    await screen.findByLabelText("Message");
    vi.mocked(apiClient.post).mockRejectedValueOnce(new ApiError({ status: 500, code: "INTERNAL_ERROR", message: "Server error" }));
    await user.click(await screen.findByRole("button", { name: /send invitation/i }));
    expect(await screen.findByText(/server error/i)).toBeInTheDocument();
    vi.mocked(apiClient.post).mockResolvedValueOnce(sent);
    await user.click(screen.getByRole("button", { name: /send invitation/i }));
    const ids = vi.mocked(apiClient.post).mock.calls.filter((c) => c[0].endsWith("/send-invite")).map((c) => (c[1] as { send_request_id: string }).send_request_id);
    expect(ids).toHaveLength(2);
    expect(ids[0]).toBe(ids[1]);
  });

  describe("template selection", () => {
    const templates = [
      { key: "standard", name: "Standard (detailed)", description: "Full guide.", subject: "Welcome to {{company_name}}", body: compose.default_body },
      { key: "short", name: "Short & friendly", description: "Brief.", subject: "Hi from {{company_name}}", body: "Hi {{candidate_first_name}}\n\n{{onboarding_url}}" },
    ];

    it("asks for a template first, then shows that template filled in to edit, sending nothing", async () => {
      const { user } = setup({ templates });
      expect(await screen.findByRole("radio", { name: /standard/i })).toBeChecked();
      expect(apiClient.post).not.toHaveBeenCalled();
      await user.click(screen.getByRole("radio", { name: /short/i }));
      await user.click(screen.getByRole("button", { name: "Next" }));
      expect(await screen.findByLabelText("Message")).toHaveValue(filled.editable_body);
      expect(apiClient.post).toHaveBeenCalledWith("/onboarding-cases/c1/invitation/preview", {
        subject: "Hi from {{company_name}}",
        body: templates[1].body,
      });
      expect(vi.mocked(apiClient.post).mock.calls.some((c) => c[0].endsWith("/send-invite"))).toBe(false);
    });

    it("Back returns to the template step", async () => {
      const { user } = setup({ templates });
      await user.click(await screen.findByRole("button", { name: "Next" }));
      await user.click(await screen.findByRole("button", { name: "Back" }));
      expect(screen.getByRole("radio", { name: /standard/i })).toBeInTheDocument();
    });
  });
});
