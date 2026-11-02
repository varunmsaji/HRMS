import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

let mockPathname = "/app/dashboard";

vi.mock("next/navigation", () => ({
  usePathname: () => mockPathname,
}));

vi.mock("@/lib/auth/auth-context", () => ({
  useAuth: () => ({ user: { employee_id: "emp-1" } }),
}));

vi.mock("@/lib/auth/use-employee-mode", () => ({
  useEmployeeMode: () => false,
}));

import { findActiveHref, SidebarNav } from "@/components/layout/sidebar-nav";

function activeLabels(): string[] {
  return screen
    .getAllByRole("link")
    .filter((link) => link.getAttribute("aria-current") === "page")
    .map((link) => link.textContent ?? "");
}

describe("findActiveHref", () => {
  it("prefers the most specific route over its parent", () => {
    expect(findActiveHref("/app/rosters/grid", ["/app/rosters", "/app/rosters/grid"])).toBe(
      "/app/rosters/grid",
    );
    expect(findActiveHref("/app/rosters", ["/app/rosters", "/app/rosters/grid"])).toBe("/app/rosters");
    expect(findActiveHref("/app/rosters/123", ["/app/rosters", "/app/rosters/grid"])).toBe("/app/rosters");
  });

  it("matches nothing for an unrelated path", () => {
    expect(findActiveHref("/app/elsewhere", ["/app/rosters"])).toBeUndefined();
    expect(findActiveHref(null, ["/app/rosters"])).toBeUndefined();
  });
});

describe("SidebarNav active state", () => {
  beforeEach(() => {
    mockPathname = "/app/dashboard";
  });

  it.each([
    ["/app/rosters", "Shift Rosters"],
    ["/app/rosters/grid", "Team Roster Grid"],
    ["/app/rosters/calendar", "Roster Calendar"],
    ["/app/me/calendar", "My Calendar"],
    ["/app/payroll/pay-runs/abc", "Payroll"],
  ])("highlights exactly one item on %s", (path, label) => {
    mockPathname = path;
    render(<SidebarNav />);
    expect(activeLabels()).toEqual([label]);
  });

  it("highlights only Settings on a settings screen, even under a primary route's prefix", () => {
    mockPathname = "/app/payroll/salary-components";
    render(<SidebarNav />);
    expect(activeLabels()).toEqual(["Settings"]);
  });
});
