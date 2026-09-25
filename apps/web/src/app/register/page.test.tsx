import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

const pushMock = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: pushMock, replace: vi.fn() }),
}));

vi.mock("next/link", () => ({
  default: ({ href, children }: { href: string; children: ReactNode }) => <a href={href}>{children}</a>,
}));

const applyTokenResponseMock = vi.fn();
vi.mock("@/lib/auth/auth-context", () => ({
  useAuth: () => ({ applyTokenResponse: applyTokenResponseMock }),
}));

vi.mock("@/lib/api/client", () => ({
  apiClient: { post: vi.fn(), get: vi.fn(), patch: vi.fn() },
}));

import RegisterPage from "@/app/register/page";
import { apiClient } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";

const mockedPost = vi.mocked(apiClient.post);

async function fillValidForm(user: ReturnType<typeof userEvent.setup>) {
  await user.type(screen.getByLabelText(/company name/i), "Acme Manufacturing");
  await user.type(screen.getByLabelText(/first name/i), "Priya");
  await user.type(screen.getByLabelText(/last name/i), "Sharma");
  await user.type(screen.getByLabelText(/work email/i), "priya@acme.example");
  await user.type(screen.getByLabelText(/^password/i), "letmein1");
  await user.type(screen.getByLabelText(/confirm password/i), "letmein1");
}

describe("RegisterPage", () => {
  afterEach(() => {
    pushMock.mockReset();
    applyTokenResponseMock.mockReset();
    mockedPost.mockReset();
  });

  it("blocks submission and shows validation errors when required fields are empty", async () => {
    const user = userEvent.setup();
    render(<RegisterPage />);

    await user.click(screen.getByRole("button", { name: /create workspace/i }));

    expect(await screen.findByText(/company name is required/i)).toBeInTheDocument();
    expect(mockedPost).not.toHaveBeenCalled();
  });

  it("submits the CompanyRegistrationRequest payload and redirects on success", async () => {
    mockedPost.mockResolvedValueOnce({
      access_token: "a1",
      token_type: "Bearer",
      expires_in_minutes: 15,
      company_id: "company-1",
      companies: [],
    });

    const user = userEvent.setup();
    render(<RegisterPage />);
    await fillValidForm(user);

    await user.click(screen.getByRole("button", { name: /create workspace/i }));

    await waitFor(() => expect(applyTokenResponseMock).toHaveBeenCalledTimes(1));
    expect(pushMock).toHaveBeenCalledWith("/app/setup");

    const [path, payload] = mockedPost.mock.calls[0];
    expect(path).toBe("/companies/register");
    expect(payload).toMatchObject({
      name: "Acme Manufacturing",
      admin_first_name: "Priya",
      admin_last_name: "Sharma",
      admin_email: "priya@acme.example",
      admin_password: "letmein1",
    });
  });

  it("shows a duplicate-account message on a 409 CONFLICT response", async () => {
    mockedPost.mockRejectedValueOnce(
      new ApiError({ status: 409, code: "CONFLICT", message: "An account with this email already exists" }),
    );

    const user = userEvent.setup();
    render(<RegisterPage />);
    await fillValidForm(user);

    await user.click(screen.getByRole("button", { name: /create workspace/i }));

    expect(await screen.findByText(/already exists/i)).toBeInTheDocument();
    expect(pushMock).not.toHaveBeenCalled();
  });

  it("maps 422 VALIDATION_ERROR field details onto the matching form field", async () => {
    mockedPost.mockRejectedValueOnce(
      new ApiError({
        status: 422,
        code: "VALIDATION_ERROR",
        message: "Password does not meet minimum strength requirements",
        details: [{ field: "admin_password", code: "WEAK_PASSWORD", message: "Too weak, try again." }],
      }),
    );

    const user = userEvent.setup();
    render(<RegisterPage />);
    await fillValidForm(user);

    await user.click(screen.getByRole("button", { name: /create workspace/i }));

    expect(await screen.findByText(/too weak, try again/i)).toBeInTheDocument();
  });
});
