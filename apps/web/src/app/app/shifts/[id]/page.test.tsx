import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({
  useParams: () => ({ id: "shift-1" }),
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
}));

vi.mock("@/lib/auth/auth-context", () => ({
  useAuth: () => ({ session: { companyId: "company-1", accessToken: "token" } }),
}));

const toastMock = vi.fn();
vi.mock("@/components/common/toast", () => ({
  useToast: () => ({ toast: toastMock }),
}));

vi.mock("@/lib/api/client", () => ({
  apiClient: { get: vi.fn(), patch: vi.fn(), delete: vi.fn() },
}));

import ShiftDetailPage from "@/app/app/shifts/[id]/page";
import { apiClient } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import type { Shift } from "@/lib/shift/types";

const mockedGet = vi.mocked(apiClient.get);
const mockedPatch = vi.mocked(apiClient.patch);
const mockedDelete = vi.mocked(apiClient.delete);

const sampleShift: Shift = {
  id: "shift-1",
  company_id: "company-1",
  name: "General Shift",
  code: "GEN",
  start_time: "09:00",
  end_time: "18:00",
  break_minutes_paid: 0,
  break_minutes_unpaid: 30,
  grace_in_minutes: 10,
  grace_out_minutes: 10,
  half_day_threshold_hours: null,
  min_hours_full_day: null,
  is_night_shift: false,
  is_cross_midnight: false,
  is_ot_eligible: false,
  is_active: true,
  version: 1,
  created_at: "2026-08-01T00:00:00Z",
  updated_at: "2026-08-01T00:00:00Z",
};

function mockLoad(shift: Shift) {
  mockedGet.mockImplementation((path: string) => {
    if (path === "/shifts/shift-1") return Promise.resolve(shift);
    return Promise.reject(new Error(`Unexpected path ${path}`));
  });
}

describe("ShiftDetailPage", () => {
  afterEach(() => {
    mockedGet.mockReset();
    mockedPatch.mockReset();
    mockedDelete.mockReset();
    toastMock.mockReset();
  });

  it("loads and renders the shift", async () => {
    mockLoad(sampleShift);
    render(<ShiftDetailPage />);

    expect(await screen.findByRole("heading", { name: "General Shift" })).toBeInTheDocument();
    expect(screen.getByText("Active")).toBeInTheDocument();
  });

  it("shows an error state when not found", async () => {
    mockedGet.mockRejectedValueOnce(new ApiError({ status: 404, code: "NOT_FOUND", message: "Not found" }));
    render(<ShiftDetailPage />);

    expect(await screen.findByText(/could not be found/i)).toBeInTheDocument();
  });

  it("displays the shift timings", async () => {
    mockLoad(sampleShift);
    render(<ShiftDetailPage />);

    await screen.findByRole("heading", { name: "General Shift" });
    expect(screen.getByText("09:00")).toBeInTheDocument();
    expect(screen.getByText("18:00")).toBeInTheDocument();
  });

  it("enters edit mode and restores values on cancel", async () => {
    mockLoad(sampleShift);
    const user = userEvent.setup();
    render(<ShiftDetailPage />);

    await user.click(await screen.findByRole("button", { name: /^edit$/i }));
    const graceInInput = screen.getByLabelText(/grace in/i);
    await user.clear(graceInInput);
    await user.type(graceInInput, "20");
    await user.click(screen.getByRole("button", { name: /cancel/i }));

    expect(screen.queryByLabelText(/grace in/i)).not.toBeInTheDocument();
  });

  it("saves changes with the current If-Match version", async () => {
    mockLoad(sampleShift);
    mockedPatch.mockResolvedValueOnce({ ...sampleShift, grace_in_minutes: 20, version: 2 });
    const user = userEvent.setup();
    render(<ShiftDetailPage />);

    await user.click(await screen.findByRole("button", { name: /^edit$/i }));
    const graceInInput = screen.getByLabelText(/grace in/i);
    await user.clear(graceInInput);
    await user.type(graceInInput, "20");
    await user.click(screen.getByRole("button", { name: /save changes/i }));

    await waitFor(() => expect(mockedPatch).toHaveBeenCalledTimes(1));
    expect(mockedPatch).toHaveBeenCalledWith(
      "/shifts/shift-1",
      { grace_in_minutes: 20 },
      { ifMatch: "1" },
    );
    expect(toastMock).toHaveBeenCalledWith(expect.objectContaining({ variant: "success" }));
  });

  it("shows stale-resource actions on 409 STALE_RESOURCE", async () => {
    mockLoad(sampleShift);
    mockedPatch.mockRejectedValueOnce(new ApiError({ status: 409, code: "STALE_RESOURCE", message: "Stale" }));
    const user = userEvent.setup();
    render(<ShiftDetailPage />);

    await user.click(await screen.findByRole("button", { name: /^edit$/i }));
    const graceInInput = screen.getByLabelText(/grace in/i);
    await user.clear(graceInInput);
    await user.type(graceInInput, "20");
    await user.click(screen.getByRole("button", { name: /save changes/i }));

    expect(await screen.findByText(/changed by someone else/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /reload latest/i })).toBeInTheDocument();
  });

  it("deactivates the shift after confirmation", async () => {
    mockLoad(sampleShift);
    mockedDelete.mockResolvedValueOnce({ ...sampleShift, is_active: false, version: 2 });
    const user = userEvent.setup();
    render(<ShiftDetailPage />);

    await user.click(await screen.findByRole("button", { name: /deactivate/i }));
    const dialog = screen.getByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: /deactivate/i }));

    await waitFor(() => expect(mockedDelete).toHaveBeenCalledTimes(1));
    expect(mockedDelete).toHaveBeenCalledWith("/shifts/shift-1", { ifMatch: "1" });
    expect(toastMock).toHaveBeenCalledWith(expect.objectContaining({ variant: "success" }));
  });

  it("reactivates a deactivated shift", async () => {
    const inactiveShift = { ...sampleShift, is_active: false, version: 2 };
    mockLoad(inactiveShift);
    mockedPatch.mockResolvedValueOnce({ ...inactiveShift, is_active: true, version: 3 });
    const user = userEvent.setup();
    render(<ShiftDetailPage />);

    await user.click(await screen.findByRole("button", { name: /reactivate/i }));
    const dialog = screen.getByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: /reactivate/i }));

    await waitFor(() => expect(mockedPatch).toHaveBeenCalledTimes(1));
    expect(mockedPatch).toHaveBeenCalledWith(
      "/shifts/shift-1",
      { is_active: true },
      { ifMatch: "2" },
    );
    expect(toastMock).toHaveBeenCalledWith(expect.objectContaining({ variant: "success" }));
  });
});
