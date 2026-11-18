import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/components/common/toast", () => ({
  useToast: () => ({ toast: vi.fn() }),
}));

vi.mock("@/lib/api/client", () => ({
  apiClient: { get: vi.fn().mockResolvedValue([]), post: vi.fn() },
  newIdempotencyKey: vi.fn(() => "key-0001-abcdef"),
}));

vi.mock("@/lib/auth/auth-context", () => ({
  useAuth: () => ({ user: { employee_id: "hr-self", company_timezone: "Asia/Kolkata" } }),
}));

import { apiClient } from "@/lib/api/client";
import { MarkDayDialog } from "@/components/attendance/mark-day-dialog";

const mockedPost = vi.mocked(apiClient.post);

const EMPLOYEES = [
  { id: "emp-a", label: "Asha (E1)" },
  { id: "emp-b", label: "Ravi (E2)" },
];

function result(employee_id: string, outcome: string, code: string | null = null) {
  return { employee_id, outcome, code, message: null, replayed: false, existing_punches: [], punches: [] };
}

function renderDialog(onRecorded = vi.fn()) {
  render(
    <MarkDayDialog
      open
      onOpenChange={vi.fn()}
      initialEmployees={EMPLOYEES}
      lockEmployees
      initialDate="2026-08-10"
      onRecorded={onRecorded}
    />,
  );
  return onRecorded;
}

describe("MarkDayDialog", () => {
  beforeEach(() => {
    mockedPost.mockImplementation(async (path: string, body: unknown) => {
      const ids = (body as { employee_ids: string[] }).employee_ids;
      if (path.endsWith("/preview")) {
        return {
          punch_in_at: "",
          punch_out_at: "",
          ready_count: 1,
          recorded_count: 0,
          blocked_count: 1,
          results: [result("emp-a", "READY"), result("emp-b", "BLOCKED", "ATTENDANCE_PERIOD_CLOSED")],
        };
      }
      return {
        punch_in_at: "",
        punch_out_at: "",
        ready_count: 0,
        recorded_count: ids.length,
        blocked_count: 0,
        results: ids.map((id) => result(id, "RECORDED")),
      };
    });
  });
  afterEach(() => mockedPost.mockReset());

  it("reviews first, then confirms only the ready employees under one idempotency key", async () => {
    const user = userEvent.setup();
    const onRecorded = renderDialog();

    await user.type(screen.getByLabelText(/reason/i), "Device offline");
    await user.click(screen.getByRole("button", { name: /review/i }));

    // nothing has been written yet — only the preview was called
    await screen.findByText(/period for this date is closed/i);
    expect(mockedPost).toHaveBeenCalledTimes(1);
    const [previewPath, previewBody] = mockedPost.mock.calls[0];
    expect(previewPath).toBe("/attendance/punches/day-entries/preview");
    // 09:00 and 18:00 IST, whatever the test process's own zone is
    expect(previewBody).toMatchObject({
      employee_ids: ["emp-a", "emp-b"],
      punch_in_at: "2026-08-10T03:30:00.000Z",
      punch_out_at: "2026-08-10T12:30:00.000Z",
      reason: "Device offline",
    });

    await user.click(screen.getByRole("button", { name: /confirm for 1 employee/i }));
    await waitFor(() => expect(mockedPost).toHaveBeenCalledTimes(2));
    const [path, body] = mockedPost.mock.calls[1];
    expect(path).toBe("/attendance/punches/day-entries");
    expect(body).toMatchObject({ employee_ids: ["emp-a"], idempotency_key: "key-0001-abcdef" });
    expect(onRecorded).toHaveBeenCalled();
    expect(await screen.findByText(/marked for 1 employee/i)).toBeInTheDocument();
  });

  it("an edit after review discards it, so stale results can never be confirmed", async () => {
    const user = userEvent.setup();
    renderDialog();
    await user.type(screen.getByLabelText(/reason/i), "Device offline");
    await user.click(screen.getByRole("button", { name: /review/i }));
    await screen.findByRole("button", { name: /confirm/i });

    await user.type(screen.getByLabelText(/reason/i), "!");
    expect(screen.queryByRole("button", { name: /confirm/i })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /review/i })).toBeInTheDocument();
  });

  it("treats an OUT time before the IN time as the next day", async () => {
    const user = userEvent.setup();
    renderDialog();
    const inField = screen.getByLabelText(/^in \(ist\)/i);
    const outField = screen.getByLabelText(/^out \(ist\)/i);
    await user.clear(inField);
    await user.type(inField, "22:00");
    await user.clear(outField);
    await user.type(outField, "06:00");
    expect(screen.getByText(/out is next day/i)).toBeInTheDocument();

    await user.type(screen.getByLabelText(/reason/i), "Night shift");
    await user.click(screen.getByRole("button", { name: /review/i }));
    await waitFor(() => expect(mockedPost).toHaveBeenCalled());
    expect(mockedPost.mock.calls[0][1]).toMatchObject({
      punch_in_at: "2026-08-10T16:30:00.000Z",
      punch_out_at: "2026-08-11T00:30:00.000Z",
    });
  });

  it("refuses a missing reason without calling the server", async () => {
    const user = userEvent.setup();
    renderDialog();
    await user.click(screen.getByRole("button", { name: /review/i }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/give a reason/i);
    expect(mockedPost).not.toHaveBeenCalled();
  });
});
