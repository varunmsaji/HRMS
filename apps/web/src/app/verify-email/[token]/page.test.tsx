import { render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({
  useParams: () => ({ token: "sample-token" }),
}));

vi.mock("next/link", () => ({
  default: ({ href, children }: { href: string; children: ReactNode }) => <a href={href}>{children}</a>,
}));

vi.mock("@/lib/api/client", () => ({
  apiClient: { post: vi.fn(), get: vi.fn(), patch: vi.fn() },
}));

import VerifyEmailPage from "@/app/verify-email/[token]/page";
import { apiClient } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";

describe("VerifyEmailPage", () => {
  afterEach(() => {
    vi.mocked(apiClient.post).mockReset();
  });

  it("shows a success message once the token verifies", async () => {
    vi.mocked(apiClient.post).mockResolvedValueOnce({ verified: true });

    render(<VerifyEmailPage />);

    expect(await screen.findByText(/email verified/i)).toBeInTheDocument();
    expect(apiClient.post).toHaveBeenCalledWith(
      "/auth/email/verify",
      { token: "sample-token" },
      { authenticated: false },
    );
    expect(screen.getByRole("link", { name: /go to sign in/i })).toHaveAttribute("href", "/login");
  });

  it("shows an expired/invalid message on a 401 response", async () => {
    vi.mocked(apiClient.post).mockRejectedValueOnce(
      new ApiError({ status: 401, code: "INVALID_TOKEN", message: "bad token" }),
    );

    render(<VerifyEmailPage />);

    expect(await screen.findByText(/invalid or has expired/i)).toBeInTheDocument();
  });

  it("calls the verify endpoint exactly once even under React's double-invoke", async () => {
    vi.mocked(apiClient.post).mockResolvedValueOnce({ verified: true });

    render(<VerifyEmailPage />);

    await screen.findByText(/email verified/i);
    expect(apiClient.post).toHaveBeenCalledTimes(1);
  });
});
