import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api/client", () => ({
  apiClient: {
    get: vi.fn(),
    post: vi.fn(),
    patch: vi.fn(),
  },
}));

import { apiClient } from "@/lib/api/client";
import { AuthProvider, useAuth } from "@/lib/auth/auth-context";
import { loadSession, SESSION_EXPIRED_EVENT } from "@/lib/auth/token-storage";

const mockedGet = vi.mocked(apiClient.get);
const mockedPost = vi.mocked(apiClient.post);

const SAMPLE_ME = {
  user: {
    id: "user-1",
    email: "user@example.com",
    company_id: "company-1",
    employee_id: null,
    permissions: [],
  },
};
const SAMPLE_TOKEN_RESPONSE = {
  access_token: "a1",
  refresh_token: "r1",
  token_type: "Bearer",
  expires_in_minutes: 15,
  company_id: "company-1",
  companies: [],
};

function TestConsumer() {
  const { status, user, login, logout } = useAuth();
  return (
    <div>
      <p data-testid="status">{status}</p>
      <p data-testid="email">{user?.email ?? "none"}</p>
      <button onClick={() => void login({ email: "user@example.com", password: "secret123" })}>login</button>
      <button onClick={() => void logout()}>logout</button>
    </div>
  );
}

describe("AuthProvider", () => {
  beforeEach(() => {
    window.localStorage.clear();
    mockedGet.mockReset();
    mockedPost.mockReset();
  });

  it("starts unauthenticated when there is no stored session", async () => {
    render(
      <AuthProvider>
        <TestConsumer />
      </AuthProvider>,
    );

    await waitFor(() => expect(screen.getByTestId("status")).toHaveTextContent("unauthenticated"));
  });

  it("logs in, loads /auth/me, and exposes the authenticated user", async () => {
    mockedPost.mockResolvedValueOnce(SAMPLE_TOKEN_RESPONSE);
    mockedGet.mockResolvedValueOnce(SAMPLE_ME);

    const user = userEvent.setup();
    render(
      <AuthProvider>
        <TestConsumer />
      </AuthProvider>,
    );
    await waitFor(() => expect(screen.getByTestId("status")).toHaveTextContent("unauthenticated"));

    await user.click(screen.getByText("login"));

    await waitFor(() => expect(screen.getByTestId("status")).toHaveTextContent("authenticated"));
    expect(screen.getByTestId("email")).toHaveTextContent("user@example.com");
    expect(loadSession()?.accessToken).toBe("a1");
  });

  it("clears the session and flips to unauthenticated on logout", async () => {
    mockedPost.mockResolvedValueOnce(SAMPLE_TOKEN_RESPONSE);
    mockedGet.mockResolvedValueOnce(SAMPLE_ME);
    mockedPost.mockResolvedValueOnce(undefined);

    const user = userEvent.setup();
    render(
      <AuthProvider>
        <TestConsumer />
      </AuthProvider>,
    );
    await user.click(screen.getByText("login"));
    await waitFor(() => expect(screen.getByTestId("status")).toHaveTextContent("authenticated"));

    await user.click(screen.getByText("logout"));

    await waitFor(() => expect(screen.getByTestId("status")).toHaveTextContent("unauthenticated"));
    expect(loadSession()).toBeNull();
  });

  it("flips to unauthenticated when a session-expired event fires (e.g. failed token refresh)", async () => {
    mockedPost.mockResolvedValueOnce(SAMPLE_TOKEN_RESPONSE);
    mockedGet.mockResolvedValueOnce(SAMPLE_ME);

    const user = userEvent.setup();
    render(
      <AuthProvider>
        <TestConsumer />
      </AuthProvider>,
    );
    await user.click(screen.getByText("login"));
    await waitFor(() => expect(screen.getByTestId("status")).toHaveTextContent("authenticated"));

    window.dispatchEvent(new Event(SESSION_EXPIRED_EVENT));

    await waitFor(() => expect(screen.getByTestId("status")).toHaveTextContent("unauthenticated"));
  });
});
