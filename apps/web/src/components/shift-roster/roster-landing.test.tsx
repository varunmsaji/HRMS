import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const replace = vi.fn();
let mockCanManage = true;
vi.mock("next/navigation", () => ({ useRouter: () => ({ replace }) }));
vi.mock("@/lib/auth/use-permissions", () => ({ usePermissions: () => ({ can: () => mockCanManage }) }));

import { RosterLanding } from "./roster-landing";

describe("RosterLanding", () => {
  beforeEach(() => {
    replace.mockClear();
    mockCanManage = true;
    window.localStorage.clear();
  });

  it("opens Coverage by default, even when a schedule view was used last", async () => {
    window.localStorage.setItem("roster:last-view", "month");
    render(<RosterLanding />);
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/app/rosters/coverage"));
    expect(screen.getByRole("status", { name: /opening shift rosters/i })).toBeInTheDocument();
  });

  it("opens Coverage the first time too", async () => {
    render(<RosterLanding />);
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/app/rosters/coverage"));
  });

  it("opens Coverage for staff who cannot manage rosters", async () => {
    mockCanManage = false;
    render(<RosterLanding />);
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/app/rosters/coverage"));
  });

  it("keeps the old schedule address opening the last schedule view", async () => {
    window.localStorage.setItem("roster:last-view", "day");
    render(<RosterLanding to="schedule" />);
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/app/rosters/schedule/day"));
  });

  it("opens Week on the old schedule address the first time", async () => {
    render(<RosterLanding to="schedule" />);
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/app/rosters/schedule/week"));
  });

  it("sends staff who cannot manage rosters from the old schedule address to Coverage", async () => {
    mockCanManage = false;
    render(<RosterLanding to="schedule" />);
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/app/rosters/coverage"));
  });
});
