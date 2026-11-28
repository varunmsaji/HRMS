import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api/client", () => ({ apiClient: { get: vi.fn(), put: vi.fn() } }));

import AttendanceDigestsPage from "@/app/app/attendance-digests/page";
import { apiClient } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import type { DigestSettings } from "@/lib/attendance/digest-settings";

const get = vi.mocked(apiClient.get);
const put = vi.mocked(apiClient.put);

const SETTINGS: DigestSettings = {
  manager_daily_enabled: true,
  hr_weekly_enabled: true,
  deployment_enabled: true,
  updated_at: null,
};

beforeEach(() => {
  get.mockReset();
  put.mockReset();
});
afterEach(cleanup);

describe("Attendance emails settings", () => {
  it("shows both emails as on by default, with nothing to save until something changes", async () => {
    get.mockResolvedValue(SETTINGS);
    render(<AttendanceDigestsPage />);
    expect(await screen.findByLabelText("Daily team note to managers")).toBeChecked();
    expect(screen.getByLabelText("Weekly summary to HR")).toBeChecked();
    expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
    expect(screen.queryByRole("status")).not.toBeInTheDocument(); // no "switched off" warning
  });

  it("saves an opt-out and says so", async () => {
    get.mockResolvedValue(SETTINGS);
    put.mockResolvedValue({ ...SETTINGS, manager_daily_enabled: false, updated_at: "2026-11-25T09:00:00Z" });
    const user = userEvent.setup();
    render(<AttendanceDigestsPage />);
    await user.click(await screen.findByLabelText("Daily team note to managers"));
    await user.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() =>
      expect(put).toHaveBeenCalledWith("/attendance/digest-settings", { manager_daily_enabled: false, hr_weekly_enabled: true }),
    );
    expect(await screen.findByText("Saved.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Save" })).toBeDisabled(); // saved: nothing left to save
  });

  it("warns when the deployment sends no emails at all, while still letting the choice be saved", async () => {
    get.mockResolvedValue({ ...SETTINGS, deployment_enabled: false });
    render(<AttendanceDigestsPage />);
    expect(await screen.findByText(/switched off for this whole deployment/i)).toBeInTheDocument();
    expect(screen.getByLabelText("Weekly summary to HR")).toBeEnabled();
  });

  it("shows a failed save without losing the choice", async () => {
    get.mockResolvedValue(SETTINGS);
    put.mockRejectedValue(new ApiError({ status: 500, code: "BOOM", message: "x" }));
    const user = userEvent.setup();
    render(<AttendanceDigestsPage />);
    await user.click(await screen.findByLabelText("Weekly summary to HR"));
    await user.click(screen.getByRole("button", { name: "Save" }));
    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(screen.getByLabelText("Weekly summary to HR")).not.toBeChecked();
    expect(screen.getByRole("button", { name: "Save" })).toBeEnabled(); // can try again
  });

  it("shows the refusal, with a retry, instead of a form when the caller may not manage it", async () => {
    get.mockRejectedValue(
      new ApiError({ status: 403, code: "PERMISSION_DENIED", message: "You do not have permission to manage attendance policy." }),
    );
    render(<AttendanceDigestsPage />);
    expect(await screen.findByText("Access restricted")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Try again" })).toBeInTheDocument();
    expect(screen.queryByLabelText("Daily team note to managers")).not.toBeInTheDocument();
  });
});
