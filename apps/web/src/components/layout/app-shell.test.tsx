import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({
  usePathname: () => "/app/dashboard",
  useRouter: () => ({ push: vi.fn() }),
}));

vi.mock("@/lib/auth/auth-context", () => ({
  useAuth: () => ({ user: null, session: null, logout: vi.fn() }),
}));

vi.mock("@/components/common/toast", () => ({
  useToast: () => ({ toast: vi.fn() }),
  useOptionalToast: () => null,
}));

vi.mock("@/lib/api/client", () => ({
  apiClient: { get: vi.fn() },
}));

import { AppShell } from "@/components/layout/app-shell";

describe("AppShell skip link", () => {
  it("moves keyboard focus to the main landmark", () => {
    render(
      <AppShell>
        <h1>Dashboard</h1>
      </AppShell>,
    );

    const main = screen.getByRole("main");
    expect(main).toHaveAttribute("tabindex", "-1");

    fireEvent.click(screen.getByRole("link", { name: "Skip to main content" }));

    expect(document.activeElement).toBe(main);
  });
});
