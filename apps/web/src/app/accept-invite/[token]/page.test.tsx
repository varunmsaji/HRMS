import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

const pushMock = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: pushMock, replace: vi.fn() }),
  useParams: () => ({ token: "test-token" }),
}));

const applyTokenResponseMock = vi.fn();
vi.mock("@/lib/auth/auth-context", () => ({
  useAuth: () => ({ applyTokenResponse: applyTokenResponseMock }),
}));

vi.mock("@/lib/api/client", () => ({
  apiClient: { get: vi.fn(), post: vi.fn() },
}));

import AcceptInvitePage from "@/app/accept-invite/[token]/page";
import { apiClient } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";

const mockedGet = vi.mocked(apiClient.get);
const mockedPost = vi.mocked(apiClient.post);

describe("AcceptInvitePage", () => {
  afterEach(() => {
    pushMock.mockReset();
    applyTokenResponseMock.mockReset();
    mockedGet.mockReset();
    mockedPost.mockReset();
  });

  it("shows the new-account form (with confirm password) when no account exists yet", async () => {
    mockedGet.mockResolvedValueOnce({
      email: "new@example.com",
      company_name: "Acme",
      expires_at: "2026-12-01T00:00:00Z",
      existing_account: false,
    });

    render(<AcceptInvitePage />);

    expect(await screen.findByText(/set a password for new@example.com/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/^password/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/confirm password/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/first name/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /create account/i })).toBeInTheDocument();
  });

  it("shows the login-style form (no confirm password, no name fields) for an existing account", async () => {
    mockedGet.mockResolvedValueOnce({
      email: "existing@example.com",
      company_name: "Acme",
      expires_at: "2026-12-01T00:00:00Z",
      existing_account: true,
    });

    render(<AcceptInvitePage />);

    expect(
      await screen.findByText(/existing@example.com already has an account/i),
    ).toBeInTheDocument();
    expect(screen.getByLabelText(/^password/i)).toBeInTheDocument();
    expect(screen.queryByLabelText(/confirm password/i)).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/first name/i)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /accept invitation/i })).toBeInTheDocument();
  });

  it("accepts a new account with a strong matching password", async () => {
    mockedGet.mockResolvedValueOnce({
      email: "new@example.com",
      company_name: "Acme",
      expires_at: "2026-12-01T00:00:00Z",
      existing_account: false,
    });
    mockedPost.mockResolvedValueOnce({
      access_token: "at",
      expires_in_minutes: 15,
      company_id: "company-1",
      companies: [],
    });
    applyTokenResponseMock.mockResolvedValueOnce({
      id: "user-1",
      permissions: ["DASHBOARD.COMPANY.VIEW"],
    });

    const user = userEvent.setup();
    render(<AcceptInvitePage />);

    await user.type(await screen.findByLabelText(/^password/i), "GoodPass9");
    await user.type(screen.getByLabelText(/confirm password/i), "GoodPass9");
    await user.click(screen.getByRole("button", { name: /create account/i }));

    await waitFor(() => expect(mockedPost).toHaveBeenCalledTimes(1));
    expect(mockedPost).toHaveBeenCalledWith(
      "/public/account-invites/test-token/accept",
      expect.objectContaining({ password: "GoodPass9" }),
      { authenticated: false },
    );
    await waitFor(() => expect(pushMock).toHaveBeenCalled());
  });

  it("SEC-08: rejects an existing account with the wrong password and never navigates away", async () => {
    mockedGet.mockResolvedValueOnce({
      email: "existing@example.com",
      company_name: "Acme",
      expires_at: "2026-12-01T00:00:00Z",
      existing_account: true,
    });
    mockedPost.mockRejectedValueOnce(
      new ApiError({ status: 401, code: "INVALID_CREDENTIALS", message: "Invalid email or password" }),
    );

    const user = userEvent.setup();
    render(<AcceptInvitePage />);

    await user.type(await screen.findByLabelText(/^password/i), "TotallyWrongPassword9");
    await user.click(screen.getByRole("button", { name: /accept invitation/i }));

    expect(await screen.findByText(/incorrect password/i)).toBeInTheDocument();
    expect(applyTokenResponseMock).not.toHaveBeenCalled();
    expect(pushMock).not.toHaveBeenCalled();
  });

  it("accepts an existing account with the correct password without requiring a confirm field", async () => {
    mockedGet.mockResolvedValueOnce({
      email: "existing@example.com",
      company_name: "Acme",
      expires_at: "2026-12-01T00:00:00Z",
      existing_account: true,
    });
    mockedPost.mockResolvedValueOnce({
      access_token: "at",
      expires_in_minutes: 15,
      company_id: "company-1",
      companies: [],
    });
    applyTokenResponseMock.mockResolvedValueOnce({
      id: "user-1",
      permissions: ["DASHBOARD.COMPANY.VIEW"],
    });

    const user = userEvent.setup();
    render(<AcceptInvitePage />);

    await user.type(await screen.findByLabelText(/^password/i), "TheirRealPassword9");
    await user.click(screen.getByRole("button", { name: /accept invitation/i }));

    await waitFor(() => expect(mockedPost).toHaveBeenCalledTimes(1));
    expect(mockedPost).toHaveBeenCalledWith(
      "/public/account-invites/test-token/accept",
      expect.objectContaining({ password: "TheirRealPassword9" }),
      { authenticated: false },
    );
    await waitFor(() => expect(pushMock).toHaveBeenCalled());
  });

  it("shows an account-locked message on a 423 response", async () => {
    mockedGet.mockResolvedValueOnce({
      email: "existing@example.com",
      company_name: "Acme",
      expires_at: "2026-12-01T00:00:00Z",
      existing_account: true,
    });
    mockedPost.mockRejectedValueOnce(
      new ApiError({ status: 423, code: "ACCOUNT_LOCKED", message: "Account is temporarily locked" }),
    );

    const user = userEvent.setup();
    render(<AcceptInvitePage />);

    await user.type(await screen.findByLabelText(/^password/i), "SomePassword9");
    await user.click(screen.getByRole("button", { name: /accept invitation/i }));

    expect(await screen.findByText(/temporarily locked/i)).toBeInTheDocument();
  });
});
