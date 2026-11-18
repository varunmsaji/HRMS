import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

let mockPathname = "/app/dashboard";
let mockEmployeeMode = false;

vi.mock("next/navigation", () => ({
  usePathname: () => mockPathname,
}));

vi.mock("@/lib/auth/auth-context", () => ({
  useAuth: () => ({ user: { employee_id: "emp-1" } }),
}));

vi.mock("@/lib/auth/use-employee-mode", () => ({
  useEmployeeMode: () => mockEmployeeMode,
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
    expect(findActiveHref("/app/rosters/schedule/week", ["/app/rosters", "/app/rosters/schedule/week"])).toBe(
      "/app/rosters/schedule/week",
    );
    expect(findActiveHref("/app/rosters", ["/app/rosters", "/app/rosters/schedule/week"])).toBe("/app/rosters");
    expect(findActiveHref("/app/rosters/123", ["/app/rosters", "/app/rosters/schedule/week"])).toBe("/app/rosters");
  });

  it("matches nothing for an unrelated path", () => {
    expect(findActiveHref("/app/elsewhere", ["/app/rosters"])).toBeUndefined();
    expect(findActiveHref(null, ["/app/rosters"])).toBeUndefined();
  });
});

describe("SidebarNav active state", () => {
  beforeEach(() => {
    mockPathname = "/app/dashboard";
    mockEmployeeMode = false;
  });

  it.each([
    ["/app/rosters", "Shift Rosters"],
    ["/app/rosters/schedule/week", "Shift Rosters"],
    ["/app/rosters/coverage", "Shift Rosters"],
    ["/app/me/calendar", "My Calendar"],
    ["/app/payroll/pay-runs/abc", "Payroll"],
  ])("highlights exactly one item on %s", (path, label) => {
    mockPathname = path;
    render(<SidebarNav />);
    expect(activeLabels()).toEqual([label]);
  });

  it("sends Shift Rosters to its entry address, which opens Coverage", () => {
    render(<SidebarNav />);
    expect(screen.getByRole("link", { name: /shift rosters/i })).toHaveAttribute("href", "/app/rosters");
  });

  it("highlights only Settings on a settings screen, even under a primary route's prefix", () => {
    mockPathname = "/app/payroll/salary-components";
    render(<SidebarNav />);
    expect(activeLabels()).toEqual(["Settings"]);
  });
});

describe("SidebarNav for an employee", () => {
  beforeEach(() => {
    mockEmployeeMode = true;
  });

  it("offers Shift Swaps after Overtime, as mobile does, opening the coverage page that holds the swaps", () => {
    mockPathname = "/app/dashboard";
    render(<SidebarNav />);
    const labels = screen.getAllByRole("link").map((link) => link.textContent);
    expect(labels.indexOf("Shift Swaps")).toBe(labels.indexOf("Overtime") + 1);
    expect(screen.getByRole("link", { name: "Shift Swaps" })).toHaveAttribute("href", "/app/rosters/coverage");
  });

  it("highlights Shift Swaps on the coverage page", () => {
    mockPathname = "/app/rosters/coverage";
    render(<SidebarNav />);
    expect(activeLabels()).toEqual(["Shift Swaps"]);
  });
});
