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

    expect(await screen.findByText(/email or employee id is required/i)).toBeInTheDocument();
    expect(loginMock).not.toHaveBeenCalled();
  });

  it("logs in and redirects to /app/dashboard on success", async () => {
    loginMock.mockResolvedValueOnce(undefined);

    const user = userEvent.setup();
    render(<LoginPage />);
    await user.type(screen.getByLabelText(/email or employee id/i), "user@example.com");
    await user.type(screen.getByLabelText(/^password/i), "secret123");
    await user.click(screen.getByRole("button", { name: /sign in/i }));

    await waitFor(() => expect(pushMock).toHaveBeenCalledWith("/app/dashboard"));
    expect(loginMock).toHaveBeenCalledWith({ email: "user@example.com", password: "secret123" });
  });

  it("shows an invalid-credentials message on a 401 response", async () => {
    loginMock.mockRejectedValueOnce(new ApiError({ status: 401, code: "INVALID_CREDENTIALS", message: "nope" }));

    const user = userEvent.setup();
    render(<LoginPage />);
    await user.type(screen.getByLabelText(/email or employee id/i), "user@example.com");
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
    await user.type(screen.getByLabelText(/email or employee id/i), "unverified@example.com");
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
  it("signs in with an employee ID and company code, and remembers the code", async () => {
    loginMock.mockResolvedValueOnce(undefined);
    window.localStorage.removeItem("hrms.login.companyCode");

    const user = userEvent.setup();
    render(<LoginPage />);
    expect(screen.queryByLabelText(/company code/i)).not.toBeInTheDocument();
    await user.type(screen.getByLabelText(/email or employee id/i), "EMP-0007");
    await user.type(screen.getByLabelText(/company code/i), "acme");
    await user.type(screen.getByLabelText(/^password/i), "secret123");
    await user.click(screen.getByRole("button", { name: /sign in/i }));

    await waitFor(() => expect(pushMock).toHaveBeenCalledWith("/app/dashboard"));
    expect(loginMock).toHaveBeenCalledWith({
      company_code: "acme",
      employee_code: "EMP-0007",
      password: "secret123",
    });
    expect(window.localStorage.getItem("hrms.login.companyCode")).toBe("ACME");
  });

  it("asks for the company code when signing in with an employee ID", async () => {
    window.localStorage.removeItem("hrms.login.companyCode");
    const user = userEvent.setup();
    render(<LoginPage />);
    await user.type(screen.getByLabelText(/email or employee id/i), "EMP-0007");
    await user.type(screen.getByLabelText(/^password/i), "secret123");
    await user.click(screen.getByRole("button", { name: /sign in/i }));

    expect(await screen.findByText(/company code is required/i)).toBeInTheDocument();
    expect(loginMock).not.toHaveBeenCalled();
  });

  it("names the employee-ID fields in the invalid-credentials message", async () => {
    loginMock.mockRejectedValueOnce(new ApiError({ status: 401, code: "INVALID_CREDENTIALS", message: "nope" }));
    window.localStorage.setItem("hrms.login.companyCode", "ACME");

    const user = userEvent.setup();
    render(<LoginPage />);
    await user.type(screen.getByLabelText(/email or employee id/i), "EMP-0007");
    expect(screen.getByLabelText(/company code/i)).toHaveValue("ACME");
    await user.type(screen.getByLabelText(/^password/i), "wrong-password");
    await user.click(screen.getByRole("button", { name: /sign in/i }));

    expect(await screen.findByText(/invalid company code, employee id or password/i)).toBeInTheDocument();
  });
});
