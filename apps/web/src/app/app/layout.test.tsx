import { render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

const replaceMock = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: replaceMock, push: vi.fn() }),
}));

const useAuthMock = vi.fn();
vi.mock("@/lib/auth/auth-context", () => ({
  useAuth: () => useAuthMock(),
}));

vi.mock("@/components/layout/app-shell", () => ({
  AppShell: ({ children }: { children: ReactNode }) => <div data-testid="shell">{children}</div>,
}));

import AppLayout from "@/app/app/layout";

describe("AppLayout (protected route)", () => {
  afterEach(() => {
    replaceMock.mockReset();
    useAuthMock.mockReset();
  });

  it("redirects to /login and renders nothing when unauthenticated", async () => {
    useAuthMock.mockReturnValue({ status: "unauthenticated" });
    render(
      <AppLayout>
        <div>secret</div>
      </AppLayout>,
    );

    await waitFor(() => expect(replaceMock).toHaveBeenCalledWith("/login"));
    expect(screen.queryByText("secret")).not.toBeInTheDocument();
  });

  it("shows a loading state and does not redirect while auth status is resolving", () => {
    useAuthMock.mockReturnValue({ status: "loading" });
    render(
      <AppLayout>
        <div>secret</div>
      </AppLayout>,
    );

    expect(screen.getByRole("status")).toBeInTheDocument();
    expect(replaceMock).not.toHaveBeenCalled();
    expect(screen.queryByText("secret")).not.toBeInTheDocument();
  });

  it("renders the app shell and children once authenticated", () => {
    useAuthMock.mockReturnValue({ status: "authenticated" });
    render(
      <AppLayout>
        <div>secret</div>
      </AppLayout>,
    );

    expect(screen.getByTestId("shell")).toBeInTheDocument();
    expect(screen.getByText("secret")).toBeInTheDocument();
    expect(replaceMock).not.toHaveBeenCalled();
  });
});
