import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api/client", () => ({ apiClient: { get: vi.fn(), post: vi.fn() } }));

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

function setup(over: Partial<InvitationCompose> = {}) {
  vi.mocked(apiClient.get).mockResolvedValue({ ...compose, ...over });
  const onSent = vi.fn();
  const onOpenChange = vi.fn();
  render(<InvitationComposer open onOpenChange={onOpenChange} caseId="c1" onSent={onSent} />);
  return { onSent, onOpenChange, user: userEvent.setup() };
}

describe("InvitationComposer", () => {
  beforeEach(() => vi.mocked(apiClient.post).mockReset());
  afterEach(() => vi.mocked(apiClient.get).mockReset());

  it("shows candidate, recipient and company and starts from the server defaults", async () => {
    setup();
    expect(await screen.findByText(/asha@personal.example/)).toBeInTheDocument();
    expect(screen.getByText("Acme")).toBeInTheDocument();
    expect(screen.getByLabelText(/subject/i)).toHaveValue("Welcome to {{company_name}}");
    expect(screen.getByLabelText("Message")).toHaveValue(compose.default_body);
    expect(screen.getAllByText("—").length).toBe(2); // optional designation/department not assumed
  });

  it("lets HR edit the subject and insert a placeholder from the menu", async () => {
    const { user } = setup();
    const subject = await screen.findByLabelText(/subject/i);
    await user.clear(subject);
    await user.type(subject, "Hello");
    expect(subject).toHaveValue("Hello");
    await user.selectOptions(screen.getByLabelText("Insert field"), "designation");
    expect((screen.getByLabelText("Message") as HTMLTextAreaElement).value).toContain("{{designation}}");
  });

  it("shows the server-rendered preview and sends nothing until confirmed", async () => {
    const { user } = setup();
    vi.mocked(apiClient.post).mockResolvedValueOnce(preview);
    await user.click(await screen.findByRole("button", { name: "Preview" }));
    expect(await screen.findByText("Welcome to Acme")).toBeInTheDocument();
    expect(screen.getByTitle("Email preview")).toHaveAttribute("sandbox", "");
    expect(apiClient.post).toHaveBeenCalledTimes(1);
    expect(vi.mocked(apiClient.post).mock.calls[0][0]).toBe("/onboarding-cases/c1/invitation/preview");
  });

  it("shows a clear validation error and stays on the edit step", async () => {
    const { user } = setup();
    vi.mocked(apiClient.post).mockRejectedValueOnce(
      new ApiError({ status: 422, code: "VALIDATION_ERROR", message: "Unsupported placeholder {{nope}}." }),
    );
    await user.click(await screen.findByRole("button", { name: "Preview" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/unsupported placeholder/i);
    expect(screen.queryByRole("button", { name: /confirm & send/i })).not.toBeInTheDocument();
  });

  it("sends with explicit confirmation; a double-click issues one request", async () => {
    const { user, onSent } = setup();
    vi.mocked(apiClient.post).mockResolvedValueOnce(preview);
    await user.click(await screen.findByRole("button", { name: "Preview" }));
    let resolveSend: (v: OnboardingInvite) => void = () => {};
    vi.mocked(apiClient.post).mockReturnValueOnce(new Promise((r) => { resolveSend = r; }));
    const confirm = await screen.findByRole("button", { name: /confirm & send/i });
    await user.dblClick(confirm);
    resolveSend(sent);
    await waitFor(() => expect(onSent).toHaveBeenCalledWith(sent));
    const sends = vi.mocked(apiClient.post).mock.calls.filter((c) => c[0].endsWith("/send-invite"));
    expect(sends).toHaveLength(1);
    expect(sends[0][1]).toMatchObject({ subject: compose.default_subject, send_request_id: expect.any(String) });
  });

  it("warns that sending revokes an existing live link", async () => {
    setup({ has_active_link: true, active_link_expires_at: "2027-01-01T00:00:00Z" });
    expect(await screen.findByText(/revokes the previous one/i)).toBeInTheDocument();
  });

  it("explains a permission-denied load and offers no preview", async () => {
    vi.mocked(apiClient.get).mockRejectedValue(new ApiError({ status: 403, code: "PERMISSION_DENIED", message: "no" }));
    render(<InvitationComposer open onOpenChange={vi.fn()} caseId="c1" onSent={vi.fn()} />);
    expect(await screen.findByText(/don't have permission to send invitations/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Preview" })).toBeDisabled();
  });

  it("surfaces a send failure and lets HR try again with the same request id", async () => {
    const { user } = setup();
    vi.mocked(apiClient.post).mockResolvedValueOnce(preview);
    await user.click(await screen.findByRole("button", { name: "Preview" }));
    vi.mocked(apiClient.post).mockRejectedValueOnce(new ApiError({ status: 500, code: "INTERNAL_ERROR", message: "Server error" }));
    await user.click(await screen.findByRole("button", { name: /confirm & send/i }));
    expect(await screen.findByText(/server error/i)).toBeInTheDocument();
    vi.mocked(apiClient.post).mockResolvedValueOnce(sent);
    await user.click(screen.getByRole("button", { name: /confirm & send/i }));
    const ids = vi.mocked(apiClient.post).mock.calls.filter((c) => c[0].endsWith("/send-invite")).map((c) => (c[1] as { send_request_id: string }).send_request_id);
    expect(ids).toHaveLength(2);
    expect(ids[0]).toBe(ids[1]);
  });
});
