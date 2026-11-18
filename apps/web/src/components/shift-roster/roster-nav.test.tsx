import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

let mockPathname = "/app/rosters/schedule/week";
let mockCanManage = true;
vi.mock("next/navigation", () => ({ usePathname: () => mockPathname }));
vi.mock("@/lib/auth/use-permissions", () => ({ usePermissions: () => ({ can: () => mockCanManage }) }));
vi.mock("@/lib/auth/auth-context", () => ({ useAuth: () => ({ user: { company_timezone: "Asia/Kolkata" } }) }));
vi.mock("@/lib/api/client", () => ({
  apiClient: { get: vi.fn().mockResolvedValue([{ id: "s1" }, { id: "s2" }]) },
}));

import { RosterProvider } from "./roster-context";
import { RosterNav } from "./roster-nav";

function renderNav() {
  return render(
    <RosterProvider>
      <RosterNav />
    </RosterProvider>,
  );
}

describe("RosterNav", () => {
  beforeEach(() => {
    mockPathname = "/app/rosters/schedule/week";
    mockCanManage = true;
    window.localStorage.clear();
  });

  it("offers Coverage and Schedule, and the four schedule views inside Schedule", () => {
    renderNav();
    expect(screen.getByRole("link", { name: /^coverage/i })).toHaveAttribute("href", "/app/rosters/coverage");
    expect(screen.getByRole("link", { name: "Schedule" })).toHaveAttribute("aria-current", "page");
    const views = screen.getByRole("navigation", { name: "Schedule views" });
    expect(views.textContent).toMatch(/Week.*Month.*Day.*List/);
    expect(screen.getByRole("link", { name: "Week" })).toHaveAttribute("aria-current", "page");
  });

  it("hides the view switcher on Coverage", () => {
    mockPathname = "/app/rosters/coverage";
    renderNav();
    expect(screen.queryByRole("navigation", { name: "Schedule views" })).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: /^coverage/i })).toHaveAttribute("aria-current", "page");
  });

  it("remembers the last view, so Schedule reopens there", () => {
    mockPathname = "/app/rosters/schedule/day";
    const first = renderNav();
    first.unmount();
    mockPathname = "/app/rosters/coverage";
    renderNav();
    expect(screen.getByRole("link", { name: "Schedule" })).toHaveAttribute("href", "/app/rosters/schedule/day");
  });

  it("shows how many swap requests are waiting", async () => {
    mockPathname = "/app/rosters/schedule/list";
    renderNav();
    expect(await screen.findByText(/swap requests waiting/i)).toBeInTheDocument();
  });

  it("shows nothing to staff who cannot manage rosters", () => {
    mockCanManage = false;
    mockPathname = "/app/rosters/coverage";
    const { container } = renderNav();
    expect(container).toBeEmptyDOMElement();
  });
});
