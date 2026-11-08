import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

const route = { module: "attendance" };
vi.mock("next/navigation", () => ({
  useParams: () => route,
  notFound: () => {
    throw new Error("NEXT_NOT_FOUND");
  },
}));
const permissions = { codes: new Set<string>() };
vi.mock("@/lib/auth/use-permissions", () => ({
  usePermissions: () => ({ can: (code: string) => permissions.codes.has(code) }),
}));
vi.mock("@/lib/auth/auth-context", () => ({
  useAuth: () => ({ user: { company_timezone: "Asia/Kolkata" } }),
}));
vi.mock("@/lib/dates/use-company-date", () => ({ useCompanyDatePattern: () => "dd/MM/yyyy" }));
vi.mock("@/components/attendance/face-enrollment-policy-card", () => ({
  FaceEnrollmentPolicyCard: () => <p>Face enrollment during onboarding</p>,
}));
vi.mock("@/lib/api/client", () => ({ apiClient: { get: vi.fn() } }));

import SettingsModulePage from "@/app/app/settings/[module]/page";
import { apiClient } from "@/lib/api/client";

const mockedGet = vi.mocked(apiClient.get);

const checklist = {
  items: [
    ["SHIFT", "Create a shift", true, "/app/shifts", true],
    ["WORK_CALENDAR", "Set working days and holidays", true, "/app/work-calendars/setup", true],
    ["ATTENDANCE_POLICY", "Set attendance rules", true, "/app/attendance-policies/new", false],
    ["OVERTIME_POLICY", "Set overtime rules", false, "/app/overtime-policies/new", false],
    ["LEAVE_POLICY", "Set up leave", false, "/app/leave-types", false],
  ].map(([code, label, required, path, done]) => ({
    code,
    label,
    description: "",
    required,
    is_complete: done,
    path,
  })),
  required_total: 3,
  required_complete: 2,
  next_code: "ATTENDANCE_POLICY",
};

function row(kind: string, applied: Record<string, unknown> | null, leaveType?: string) {
  return {
    policy_kind: kind,
    leave_type_id: leaveType ?? null,
    leave_type_name: leaveType ? "Casual Leave" : null,
    own: null,
    applied: applied
      ? {
          scope_type: "COMPANY",
          scope_id: null,
          scope_name: null,
          effective_from: "2026-01-01",
          effective_to: null,
          has_rules: true,
          ...applied,
        }
      : null,
  };
}

function serve() {
  mockedGet.mockImplementation(((path: string) => {
    if (path === "/companies/current/setup-checklist") return Promise.resolve(checklist);
    if (path.startsWith("/policy-assignments/coverage")) {
      return Promise.resolve({
        scope_type: "COMPANY",
        scope_id: null,
        as_of: "2026-06-15",
        rows: [
          row("WORK_CALENDAR", { policy_id: "wc1", policy_name: "Standard week" }),
          row("WEEKLY_OFF", null),
          row("ATTENDANCE_POLICY", null),
          row("OVERTIME_POLICY", null),
          row("REGULARIZATION_POLICY", { policy_id: "r1", policy_name: "Corrections" }),
          row("LEAVE_POLICY", { policy_id: "l1", policy_name: "Casual rules" }, "lt1"),
        ],
      });
    }
    return Promise.reject(new Error(`unexpected ${path}`));
  }) as never);
}

describe("Settings module page", () => {
  afterEach(() => {
    mockedGet.mockReset();
    permissions.codes = new Set();
    route.module = "attendance";
  });

  it("puts every attendance setting on one page, in setup order", async () => {
    serve();
    render(<SettingsModulePage />);

    const headings = screen.getAllByRole("heading", { level: 2 }).map((h) => h.textContent);
    expect(headings).toEqual([
      "When people work",
      "Where people punch",
      "Attendance rules",
      "Who follows which rules",
      "Closing the month",
    ]);
    for (const name of [/Shifts/, /Work Calendars/, /Workplace Geofences/, /Attendance Policies/, /Attendance Periods/]) {
      expect(screen.getByRole("link", { name })).toBeInTheDocument();
    }
    expect(screen.getByRole("link", { name: /Settings/ })).toHaveAttribute("href", "/app/settings");
    expect(await screen.findByText("2 of 4 setup steps done")).toBeInTheDocument();
  });

  it("shows what the whole company follows, and links each policy to where its followers change", async () => {
    serve();
    render(<SettingsModulePage />);

    const follows = screen
      .getByRole("heading", { name: "Who follows which rules" })
      .closest("section")!;
    const table = await within(follows).findByRole("table");
    expect(within(table).getByRole("link", { name: "Standard week" })).toHaveAttribute(
      "href",
      "/app/work-calendars/wc1?tab=followers",
    );
    expect(within(table).getByRole("link", { name: "Corrections" })).toHaveAttribute(
      "href",
      "/app/regularization-policies/r1?tab=followers",
    );
    // A missing attendance policy is a gap; missing overtime or weekly-off is a normal choice.
    const attendanceRow = within(table).getByText("Attendance Policy").closest("tr")!;
    expect(within(attendanceRow).getByText("Not set")).toBeInTheDocument();
    expect(within(table).getByText(/Skip this if you don't pay overtime/)).toBeInTheDocument();
    expect(within(table).getByText(/work calendar's own weekly offs apply/)).toBeInTheDocument();
    // Leave isn't part of the attendance summary.
    expect(within(table).queryByText(/Casual/)).toBeNull();
    expect(within(follows).getByRole("link", { name: /Rules by Group/ })).toHaveAttribute(
      "href",
      "/app/policy-assignments",
    );
  });

  it("shows the face enrollment setting with the attendance rules for those allowed to change it", async () => {
    serve();
    permissions.codes = new Set(["ATTENDANCE.FACE_ENROLLMENT_MANAGE"]);
    render(<SettingsModulePage />);
    const rules = screen.getByRole("heading", { name: "Attendance rules" }).closest("section")!;
    expect(within(rules).getByText("Face enrollment during onboarding")).toBeInTheDocument();
  });

  it("tucks rarely needed leave settings away until asked", async () => {
    serve();
    route.module = "leave";
    const user = userEvent.setup();
    render(<SettingsModulePage />);

    expect(screen.getByRole("link", { name: /Leave Policies/ })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Leave Year/ })).toBeNull();
    await user.click(screen.getByRole("button", { name: "Show 3 more" }));
    expect(screen.getByRole("link", { name: /Leave Year/ })).toBeInTheDocument();
    expect(await screen.findByRole("link", { name: "Casual rules" })).toHaveAttribute(
      "href",
      "/app/leave-policies/l1?tab=followers",
    );
  });

  it("says how each screen stands, and flags what still needs doing", async () => {
    serve();
    const base = mockedGet.getMockImplementation()!;
    mockedGet.mockImplementation(((path: string) => {
      if (path === "/shifts") return Promise.resolve([]);
      if (path === "/attendance-policies") {
        return Promise.resolve([
          { id: "p1", is_active: true, live_from: "2026-01-01", assigned_company_wide: true },
          { id: "p2", is_active: true, live_from: "2026-01-01", assigned_group_count: 0 },
          { id: "p3", is_active: false, live_from: "2026-01-01" },
        ]);
      }
      if (path === "/holiday-calendars") return Promise.resolve([{ id: "h1", is_active: true }]);
      return base(path);
    }) as never);
    render(<SettingsModulePage />);

    expect(
      await within(screen.getByRole("link", { name: /^Shifts/ })).findByText("None yet: needed"),
    ).toBeInTheDocument();
    expect(
      await within(screen.getByRole("link", { name: /^Attendance Policies/ })).findByText(
        "2 policies · 1 not assigned",
      ),
    ).toBeInTheDocument();
    expect(
      await within(screen.getByRole("link", { name: /^Holiday Calendars/ })).findByText("1 calendar"),
    ).toBeInTheDocument();
  });

  it("is a not-found page for an unknown area", () => {
    route.module = "nope";
    serve();
    vi.spyOn(console, "error").mockImplementation(() => {});
    expect(() => render(<SettingsModulePage />)).toThrow("NEXT_NOT_FOUND");
  });
});
