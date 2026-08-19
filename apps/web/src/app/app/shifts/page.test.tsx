import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({
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
  apiClient: { get: vi.fn(), post: vi.fn() },
}));

import ShiftsPage from "@/app/app/shifts/page";
import { apiClient } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import type { Shift } from "@/lib/shift/types";

const mockedGet = vi.mocked(apiClient.get);
const mockedPost = vi.mocked(apiClient.post);

const sampleShift: Shift = {
  id: "shift-1",
  company_id: "company-1",
  name: "General Shift",
  code: "GEN",
  start_time: "00:00",
  end_time: "00:00",
  break_minutes_paid: 0,
  break_minutes_unpaid: 0,
  grace_in_minutes: 0,
  grace_out_minutes: 0,
  half_day_threshold_hours: null,
  min_hours_full_day: null,
  is_night_shift: false,
  is_cross_midnight: false,
  is_ot_eligible: false,
  is_active: true,
  version: 1,
  created_at: "2026-08-01T00:00:00Z",
  updated_at: "2026-08-01T00:00:00Z",
  current_version_id: "version-1",
  draft_version_id: null,
};

function mockLoad(shifts: Shift[]) {
  mockedGet.mockImplementation((path: string) => {
    if (path === "/shifts") return Promise.resolve(shifts);
    return Promise.reject(new Error(`Unexpected path ${path}`));
  });
}

describe("ShiftsPage", () => {
  afterEach(() => {
    mockedGet.mockReset();
    mockedPost.mockReset();
    toastMock.mockReset();
  });

  it("shows a loading state before data resolves", () => {
    mockedGet.mockReturnValue(new Promise(() => {}));
    render(<ShiftsPage />);
    expect(screen.getByRole("status")).toBeInTheDocument();
  });

  it("shows the empty state with guidance when there are no shifts", async () => {
    mockLoad([]);
    render(<ShiftsPage />);

    expect(await screen.findByText(/no shifts have been configured yet/i)).toBeInTheDocument();
  });

  it("renders the list of shifts with schedule status", async () => {
    mockLoad([sampleShift]);
    render(<ShiftsPage />);

    expect(await screen.findByText(/General Shift/)).toBeInTheDocument();
    expect(screen.getByText("Active")).toBeInTheDocument();
    expect(screen.getByText(/published schedule/i)).toBeInTheDocument();
  });

  it("shows a draft-in-progress marker when a shift has an open draft", async () => {
    mockLoad([{ ...sampleShift, current_version_id: null, draft_version_id: "version-2" }]);
    render(<ShiftsPage />);

    expect(await screen.findByText(/no published schedule/i)).toBeInTheDocument();
    expect(screen.getByText(/draft in progress/i)).toBeInTheDocument();
  });

  it("shows an error state when loading fails with forbidden", async () => {
    mockedGet.mockRejectedValueOnce(
      new ApiError({ status: 403, code: "PERMISSION_DENIED", message: "Forbidden" }),
    );
    render(<ShiftsPage />);

    expect(await screen.findByText(/do not have permission to view shifts/i)).toBeInTheDocument();
  });

  it("creates a shift from the empty state and refreshes the list", async () => {
    let shifts: Shift[] = [];
    mockedGet.mockImplementation((path: string) => {
      if (path === "/shifts") return Promise.resolve(shifts);
      return Promise.reject(new Error(`Unexpected path ${path}`));
    });
    mockedPost.mockImplementationOnce(async () => {
      shifts = [sampleShift];
      return sampleShift;
    });
    const user = userEvent.setup();
    render(<ShiftsPage />);

    await user.click(await screen.findByRole("button", { name: /add shift/i }));
    const dialog = await screen.findByRole("dialog");
    await user.type(within(dialog).getByLabelText(/shift name/i), "General Shift");
    await user.click(within(dialog).getByRole("button", { name: /^add shift$/i }));

    await waitFor(() => expect(mockedPost).toHaveBeenCalledTimes(1));
    expect(mockedPost).toHaveBeenCalledWith("/shifts", { name: "General Shift", code: null });
    expect(toastMock).toHaveBeenCalledWith(expect.objectContaining({ variant: "success" }));
  });

  it("shows a validation error when name is missing", async () => {
    mockLoad([]);
    const user = userEvent.setup();
    render(<ShiftsPage />);

    await user.click(await screen.findByRole("button", { name: /add shift/i }));
    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: /^add shift$/i }));

    expect(await within(dialog).findByText(/shift name is required/i)).toBeInTheDocument();
    expect(mockedPost).not.toHaveBeenCalled();
  });

  it("surfaces an API error toast when creation fails", async () => {
    mockLoad([]);
    mockedPost.mockRejectedValueOnce(
      new ApiError({ status: 500, code: "INTERNAL_ERROR", message: "Something broke" }),
    );
    const user = userEvent.setup();
    render(<ShiftsPage />);

    await user.click(await screen.findByRole("button", { name: /add shift/i }));
    const dialog = await screen.findByRole("dialog");
    await user.type(within(dialog).getByLabelText(/shift name/i), "General Shift");
    await user.click(within(dialog).getByRole("button", { name: /^add shift$/i }));

    await waitFor(() =>
      expect(toastMock).toHaveBeenCalledWith(
        expect.objectContaining({ title: "Could not add shift", variant: "danger" }),
      ),
    );
  });
});
