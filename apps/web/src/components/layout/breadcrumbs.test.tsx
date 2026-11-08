import { render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

const location = { pathname: "/app/shifts" };
vi.mock("next/navigation", () => ({ usePathname: () => location.pathname }));

import { AppBreadcrumbs } from "@/components/layout/breadcrumbs";

function crumbs(pathname: string) {
  location.pathname = pathname;
  const { unmount } = render(<AppBreadcrumbs />);
  const trail = within(screen.getByRole("navigation", { name: "Breadcrumb" }))
    .getAllByRole("listitem")
    .map((item) => {
      const link = item.querySelector("a");
      return link ? `${item.textContent}→${link.getAttribute("href")}` : item.textContent;
    });
  unmount();
  return trail;
}

describe("AppBreadcrumbs", () => {
  it("places a settings screen under its area", () => {
    expect(crumbs("/app/shifts")).toEqual([
      "Settings→/app/settings",
      "Attendance→/app/settings/attendance",
      "Shifts",
    ]);
    expect(crumbs("/app/leave-policies/p1")).toEqual([
      "Settings→/app/settings",
      "Leave→/app/settings/leave",
      "Leave Policies→/app/leave-policies",
      "Details",
    ]);
  });

  it("names the area on its own page, and keeps shared screens directly under Settings", () => {
    expect(crumbs("/app/settings/attendance")).toEqual(["Settings→/app/settings", "Attendance"]);
    expect(crumbs("/app/policy-assignments")).toEqual([
      "Settings→/app/settings",
      "Rules by Group",
    ]);
  });
});
