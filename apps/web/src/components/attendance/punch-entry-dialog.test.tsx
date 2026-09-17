import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

// `D1` (staging validation report) — proves the fix at the level that actually matters: the real
// component's form input -> conversion -> request payload path, not just the pure
// `wallTimeToUtcIso` unit. `new Date(datetimeLocalValue).toISOString()` (the pre-fix code) reads
// the VIEWER's own browser/OS zone; these tests run the whole dialog under several different
// process timezones and assert the API receives the SAME `punch_time` every time.

vi.mock("@/components/common/toast", () => ({
  useToast: () => ({ toast: vi.fn() }),
}));

vi.mock("@/lib/api/client", () => ({
  apiClient: { get: vi.fn().mockResolvedValue([]), post: vi.fn().mockResolvedValue({ id: "punch-1" }) },
}));

const mockUser = vi.fn();
vi.mock("@/lib/auth/auth-context", () => ({
  useAuth: () => ({ user: mockUser() }),
}));

import { apiClient } from "@/lib/api/client";
import { PunchEntryDialog } from "@/components/attendance/punch-entry-dialog";

const mockedPost = vi.mocked(apiClient.post);

const PROCESS_TIMEZONES = ["Asia/Kolkata", "UTC", "America/New_York", "Pacific/Kiritimati"];

function withProcessTimezone<T>(tz: string, fn: () => T): T {
  const original = process.env.TZ;
  process.env.TZ = tz;
  try {
    return fn();
  } finally {
    process.env.TZ = original;
  }
}

describe("PunchEntryDialog — on-behalf punch time (D1)", () => {
  afterEach(() => {
    mockedPost.mockClear();
    mockUser.mockReset();
  });

  it.each(PROCESS_TIMEZONES)(
    "sends the same UTC instant for 09:00 IST regardless of the host process timezone (%s)",
    async (processTz) => {
      mockUser.mockReturnValue({ employee_id: "self-emp", company_timezone: "Asia/Kolkata" });

      await withProcessTimezone(processTz, async () => {
        const user = userEvent.setup();
        render(
          <PunchEntryDialog
            open
            onOpenChange={vi.fn()}
            employeeId="target-emp" // not the caller's own -> admin/on-behalf mode
            onRecorded={vi.fn()}
          />,
        );

        const timeField = screen.getByLabelText(/punch time \(ist\)/i);
        await user.clear(timeField);
        await user.type(timeField, "2026-09-15T09:00");

        await user.type(screen.getByLabelText(/reference/i), "on-behalf correction");
        await user.click(screen.getByRole("button", { name: /record punch/i }));

        await waitFor(() => expect(mockedPost).toHaveBeenCalled());
        const [, body] = mockedPost.mock.calls[0];
        expect((body as { punch_time: string }).punch_time).toBe("2026-09-15T03:30:00.000Z");
      });
    },
  );

  it("does not let the browser/process timezone shift a near-midnight IST entry onto the wrong India business date", async () => {
    mockUser.mockReturnValue({ employee_id: "self-emp", company_timezone: "Asia/Kolkata" });

    await withProcessTimezone("Pacific/Kiritimati", async () => {
      const user = userEvent.setup();
      render(
        <PunchEntryDialog open onOpenChange={vi.fn()} employeeId="target-emp" onRecorded={vi.fn()} />,
      );

      const timeField = screen.getByLabelText(/punch time \(ist\)/i);
      await user.clear(timeField);
      await user.type(timeField, "2026-09-15T00:30");
      await user.type(screen.getByLabelText(/reference/i), "midnight boundary check");
      await user.click(screen.getByRole("button", { name: /record punch/i }));

      await waitFor(() => expect(mockedPost).toHaveBeenCalled());
      const [, body] = mockedPost.mock.calls[0];
      // 00:30 IST, 15 Sept == 19:00 UTC, 14 Sept — a naive browser-zone interpretation under
      // Pacific/Kiritimati (+14) would have produced a UTC instant on a different calendar day
      // entirely, silently moving the punch to the wrong India attendance date.
      expect((body as { punch_time: string }).punch_time).toBe("2026-09-14T19:00:00.000Z");
    });
  });

  it("posts to the self-service route with no punch_time field when the target is the caller's own employee", async () => {
    mockUser.mockReturnValue({ employee_id: "self-emp", company_timezone: "Asia/Kolkata" });

    const user = userEvent.setup();
    render(
      <PunchEntryDialog open onOpenChange={vi.fn()} employeeId="self-emp" onRecorded={vi.fn()} />,
    );

    // Self mode: no "Punch time" field is rendered at all.
    expect(screen.queryByLabelText(/punch time/i)).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /record punch/i }));

    await waitFor(() => expect(mockedPost).toHaveBeenCalledWith("/attendance/punches/me", expect.anything()));
    const [, body] = mockedPost.mock.calls[0];
    expect(body as object).not.toHaveProperty("punch_time");
  });
});
