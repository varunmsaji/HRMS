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

const loginMock = vi.fn();
vi.mock("@/lib/auth/auth-context", () => ({
  useAuth: () => ({ login: loginMock }),
}));

vi.mock("@/lib/api/client", () => ({
  apiClient: { post: vi.fn(), get: vi.fn(), patch: vi.fn() },
}));

import LoginPage from "@/app/login/page";
import { apiClient } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";

describe("LoginPage", () => {
  afterEach(() => {
    pushMock.mockReset();
    loginMock.mockReset();
    vi.mocked(apiClient.post).mockReset();
  });

  it("blocks submission and shows validation errors when fields are empty", async () => {
    const user = userEvent.setup();
    render(<LoginPage />);

    await user.click(screen.getByRole("button", { name: /sign in/i }));

    expect(await screen.findByText(/email is required/i)).toBeInTheDocument();
    expect(loginMock).not.toHaveBeenCalled();
  });

  it("logs in and redirects to /app/dashboard on success", async () => {
    loginMock.mockResolvedValueOnce(undefined);

    const user = userEvent.setup();
    render(<LoginPage />);
    await user.type(screen.getByLabelText(/email/i), "user@example.com");
    await user.type(screen.getByLabelText(/^password/i), "secret123");
    await user.click(screen.getByRole("button", { name: /sign in/i }));

    await waitFor(() => expect(pushMock).toHaveBeenCalledWith("/app/dashboard"));
    expect(loginMock).toHaveBeenCalledWith({ email: "user@example.com", password: "secret123" });
  });

  it("shows an invalid-credentials message on a 401 response", async () => {
    loginMock.mockRejectedValueOnce(new ApiError({ status: 401, code: "INVALID_CREDENTIALS", message: "nope" }));

    const user = userEvent.setup();
    render(<LoginPage />);
    await user.type(screen.getByLabelText(/email/i), "user@example.com");
    await user.type(screen.getByLabelText(/^password/i), "wrong-password");
    await user.click(screen.getByRole("button", { name: /sign in/i }));

    expect(await screen.findByText(/invalid email or password/i)).toBeInTheDocument();
    expect(pushMock).not.toHaveBeenCalled();
  });

  it("SEC-09: shows a resend-verification prompt on EMAIL_NOT_VERIFIED and can resend", async () => {
    loginMock.mockRejectedValueOnce(
      new ApiError({ status: 403, code: "EMAIL_NOT_VERIFIED", message: "verify first" }),
    );
    vi.mocked(apiClient.post).mockResolvedValueOnce({ accepted: true });

    const user = userEvent.setup();
    render(<LoginPage />);
    await user.type(screen.getByLabelText(/email/i), "unverified@example.com");
    await user.type(screen.getByLabelText(/^password/i), "correcthorse9");
    await user.click(screen.getByRole("button", { name: /sign in/i }));

    expect(await screen.findByText(/verify your email address/i)).toBeInTheDocument();
    expect(pushMock).not.toHaveBeenCalled();

    await user.click(screen.getByRole("button", { name: /resend verification email/i }));

    expect(apiClient.post).toHaveBeenCalledWith(
      "/auth/email/resend-verification",
      { email: "unverified@example.com" },
      { authenticated: false },
    );
    expect(await screen.findByText(/new verification email is on its way/i)).toBeInTheDocument();
  });
});
