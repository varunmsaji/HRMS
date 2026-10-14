import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const replaceMock = vi.fn();
let searchParams = new URLSearchParams();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: replaceMock }),
  usePathname: () => "/app/attendance",
  useSearchParams: () => searchParams,
  useParams: () => ({}),
}));

let authUser: Record<string, unknown> = {};
vi.mock("@/lib/auth/auth-context", () => ({
  useAuth: () => ({
    session: { companyId: "company-1", accessToken: "token" },
    user: authUser,
  }),
}));

const toastMock = vi.fn();
vi.mock("@/components/common/toast", () => ({
  useToast: () => ({ toast: toastMock }),
}));

vi.mock("@/lib/api/client", () => ({
  apiClient: { get: vi.fn(), getList: vi.fn(), post: vi.fn() },
}));

import AttendanceDashboardPage from "@/app/app/attendance/page";
import { apiClient } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import { makeAbsentDay, makeDay } from "@/lib/attendance/__fixtures__/day";
import { addDays, type EmployeeLite } from "@/lib/attendance/dashboard";
import { businessToday } from "@/lib/attendance/format";
import type { AttendanceDay } from "@/lib/attendance/types";

const mockedGet = vi.mocked(apiClient.get);
const mockedGetList = vi.mocked(apiClient.getList);

const TODAY = businessToday("UTC");

const ADMIN_PERMISSIONS = [
  "ATTENDANCE.VIEW",
  "ATTENDANCE.VIEW_ALL",
  "ATTENDANCE.PUNCH_ON_BEHALF",
  "EMPLOYEE.VIEW_ALL",
  "ORG.SHIFT.MANAGE",
  "ORG.LEGAL_ENTITY.MANAGE",
  "ATTENDANCE.REGULARIZATION_APPROVE",
  "ATTENDANCE.OVERTIME_APPROVE",
];

// `employment_joining_date`/`employment_last_working_day` (F-1 remediation) — all three joined
// well before `TODAY` and are still employed (no `last_working_day`), so they are in scope for
// every test below unless a test overrides `employees` to add/remove someone explicitly.
const EMPLOYEES = [
  { id: "emp-1", first_name: "Asha", last_name: "Rao", display_name: null, employee_code: "EMP-001", status: "ACTIVE", is_active: true, employment_joining_date: "2020-01-01", employment_last_working_day: null },
  { id: "emp-2", first_name: "Ben", last_name: "Iyer", display_name: null, employee_code: "EMP-002", status: "ACTIVE", is_active: true, employment_joining_date: "2020-01-01", employment_last_working_day: null },
  { id: "emp-3", first_name: "Chitra", last_name: "Nair", display_name: null, employee_code: "EMP-003", status: "PROBATION", is_active: true, employment_joining_date: "2020-01-01", employment_last_working_day: null },
];

const PERIOD_OPEN = {
  id: "per-1",
  company_id: "company-1",
  legal_entity_id: "le-1",
  period_start: `${TODAY.slice(0, 7)}-01`,
  period_end: `${TODAY.slice(0, 7)}-28`,
  label: "Current month",
  status: "OPEN",
  last_validation_status: "BLOCKED",
  last_validated_at: null,
  reopened_at: null,
};

interface Overrides {
  days?: AttendanceDay[] | Error;
  employees?: EmployeeLite[];
  overtime?: unknown[] | Error;
  periods?: unknown[];
  regularizations?: unknown[];
  summary?: unknown[];
}

function mockApi(o: Overrides = {}) {
  const days = o.days ?? [];
  mockedGet.mockImplementation((path: string) => {
    if (path.startsWith("/attendance/days?")) return days instanceof Error ? Promise.reject(days) : Promise.resolve(days);
    if (path.startsWith("/regularizations")) return Promise.resolve(o.regularizations ?? []);
    if (path.startsWith("/overtime")) {
      return o.overtime instanceof Error ? Promise.reject(o.overtime) : Promise.resolve(o.overtime ?? []);
    }
    if (/^\/attendance-periods\/[^/]+\/summary/.test(path)) return Promise.resolve(o.summary ?? []);
    if (path.startsWith("/attendance-periods")) return Promise.resolve(o.periods ?? []);
    if (path === "/legal-entities") {
      return Promise.resolve([
        { id: "le-1", name: "ABC India Pvt Ltd" },
        { id: "le-2", name: "ABC Services LLP" },
      ]);
    }
    if (path === "/shifts") return Promise.resolve([{ id: "shift-1", name: "General" }]);
    return Promise.reject(new Error(`Unexpected GET ${path}`));
  });
  mockedGetList.mockImplementation((path: string) => {
    if (path === "/employees") {
      const data = o.employees ?? EMPLOYEES;
      return Promise.resolve({
        data,
        pagination: { page: 1, per_page: 100, total: data.length, total_pages: 1 },
        meta: { request_id: "r1" },
      });
    }
    return Promise.reject(new Error(`Unexpected getList ${path}`));
  });
}

const sampleDays = (): AttendanceDay[] => [
  makeDay({ employee_id: "emp-1", attendance_date: TODAY, shift_id: "shift-1" }),
  makeDay({ employee_id: "emp-2", attendance_date: TODAY, is_late: true, late_minutes: 15 }),
  makeAbsentDay({ employee_id: "emp-3", attendance_date: TODAY }),
];

function kpiRegion() {
  return screen.getByRole("region", { name: "Attendance summary" });
}

/** KPI cards only — the status chart reuses "Label: n." names for its own drill-down rows. */
function kpi(name: RegExp) {
  return within(kpiRegion()).getByRole("button", { name });
}

/** The Who's In list — the same names also appear in the heatmap and reports, so scope to it. */
function inList() {
  return within(document.getElementById("att-whos-in") as HTMLElement);
}

async function findKpi(name: RegExp) {
  const region = await screen.findByRole("region", { name: "Attendance summary" });
  return within(region).findByRole("button", { name });
}

describe("AttendanceDashboardPage", () => {
  beforeEach(() => {
    searchParams = new URLSearchParams();
    authUser = { employee_id: "emp-admin", company_timezone: "UTC", permissions: ADMIN_PERMISSIONS };
  });
  afterEach(() => {
    // Unmount first: pending effects must not fire into a freshly reset mock.
    cleanup();
    mockedGet.mockReset();
    mockedGetList.mockReset();
    toastMock.mockReset();
    replaceMock.mockReset();
  });

  describe("states", () => {
    it("shows a loading state before data resolves", () => {
      mockedGet.mockReturnValue(new Promise(() => {}));
      mockedGetList.mockReturnValue(new Promise(() => {}));
      render(<AttendanceDashboardPage />);
      expect(screen.getByRole("status")).toBeInTheDocument();
      expect(screen.getByText(/loading attendance/i)).toBeInTheDocument();
    });

    it("shows the empty state when there are no attendance days for the date", async () => {
      mockApi({ days: [], employees: [] });
      render(<AttendanceDashboardPage />);
      expect(await screen.findByText(/no attendance days match these filters/i)).toBeInTheDocument();
      expect(kpi(/^Total employees: 0\./)).toBeInTheDocument();
    });

    it("shows the permission-denied message on a 403", async () => {
      mockApi({ days: new ApiError({ status: 403, code: "PERMISSION_DENIED", message: "nope" }) });
      render(<AttendanceDashboardPage />);
      expect(await screen.findByText(/you do not have permission to view attendance/i)).toBeInTheDocument();
      expect(screen.queryByRole("button", { name: /try again/i })).not.toBeInTheDocument();
    });

    it("distinguishes a failure from 'no data': generic message, retry, never the raw backend text", async () => {
      mockApi({ days: new ApiError({ status: 500, code: "BOOM", message: "psycopg2 stack trace" }) });
      render(<AttendanceDashboardPage />);
      expect(await screen.findByText(/couldn't be loaded/i)).toBeInTheDocument();
      expect(screen.queryByText(/psycopg2/)).not.toBeInTheDocument();
      expect(screen.getByRole("button", { name: /try again/i })).toBeInTheDocument();
      expect(screen.queryByText(/no attendance days match/i)).not.toBeInTheDocument();
    });

    it("isolates a failing section: the rest of the dashboard still renders and offers a retry", async () => {
      mockApi({ days: sampleDays(), overtime: new ApiError({ status: 500, code: "BOOM", message: "x" }) });
      render(<AttendanceDashboardPage />);
      expect(await screen.findByText(/couldn't load overtime/i)).toBeInTheDocument();
      expect(kpi(/^Present: 2\./)).toBeInTheDocument();
      expect(screen.getByText(/not included \(couldn't be loaded\): pending overtime/i)).toBeInTheDocument();
    });

    it("preserves a permission error on a secondary section", async () => {
      mockApi({ days: sampleDays(), overtime: new ApiError({ status: 403, code: "PERMISSION_DENIED", message: "x" }) });
      render(<AttendanceDashboardPage />);
      expect(await screen.findByText(/you do not have permission to view this section/i)).toBeInTheDocument();
    });

    it("shows an honest empty message for overtime instead of a bare zero", async () => {
      mockApi({ days: sampleDays(), overtime: [] });
      render(<AttendanceDashboardPage />);
      expect(await screen.findByText(/no overtime recorded for this period/i)).toBeInTheDocument();
    });
  });

  describe("KPIs", () => {
    it("computes counts and percentages from the loaded rows", async () => {
      mockApi({ days: sampleDays() });
      render(<AttendanceDashboardPage />);
      const present = await findKpi(/^Present: 2\./);
      expect(present).toHaveTextContent("66.7% of workforce");
      expect(kpi(/^Absent: 1\./)).toHaveTextContent("33.3% of workforce");
      expect(kpi(/^Late: 1\./)).toHaveTextContent("33.3% of checked-in employees".replace("33.3", "50.0"));
      expect(kpi(/^Total employees: 3\./)).toBeInTheDocument();
    });

    it("counts active employees with no attendance row yet as not checked in", async () => {
      mockApi({ days: sampleDays().slice(0, 2), employees: EMPLOYEES });
      render(<AttendanceDashboardPage />);
      // emp-3 has no row today.
      const card = await findKpi(/^Not checked in: 1\./);
      expect(card).toBeInTheDocument();
      expect(kpi(/^Total employees: 3\./)).toHaveTextContent("1 with no record yet");
    });

    it("labels the list as today's attendance, never 'live'", async () => {
      mockApi({ days: sampleDays() });
      render(<AttendanceDashboardPage />);
      expect(await screen.findByRole("heading", { name: /today's attendance/i })).toBeInTheDocument();
      expect(screen.getByText(/not a live presence feed/i)).toBeInTheDocument();
      expect(screen.queryByText(/^live/i)).not.toBeInTheDocument();
    });
  });

  describe("F-1 — 'Total employees'/'Not checked in' are a pure function of the selected date", () => {
    const stillActive = {
      id: "emp-2",
      first_name: "Ben",
      last_name: "Iyer",
      display_name: null,
      employee_code: "EMP-002",
      status: "ACTIVE",
      is_active: true,
      employment_joining_date: "2020-01-01",
      employment_last_working_day: null,
    };
    // Terminated well before TODAY. `status`/`is_active` are deliberately left exactly as an
    // active employee's (the backend does not keep these in sync with termination — D-1) so this
    // fixture only passes if the fix reads `employment_last_working_day`, not `status`/`is_active`.
    const terminated = {
      id: "emp-3",
      first_name: "Chitra",
      last_name: "Nair",
      display_name: null,
      employee_code: "EMP-003",
      status: "PROBATION",
      is_active: true,
      employment_joining_date: "2020-01-01",
      employment_last_working_day: addDays(TODAY, -15),
    };
    const notYetJoined = {
      id: "emp-4",
      first_name: "Dev",
      last_name: "Shah",
      display_name: null,
      employee_code: "EMP-004",
      status: "PRE_JOINING",
      is_active: true,
      employment_joining_date: addDays(TODAY, 3),
      employment_last_working_day: null,
    };

    it("excludes a terminated employee from 'no record yet' on today's view, even though status/is_active still look active", async () => {
      mockApi({ days: [], employees: [stillActive, terminated] });
      render(<AttendanceDashboardPage />);
      // Only emp-2 (still employed) should inflate the count — terminated emp-3 must not.
      expect(await findKpi(/^Total employees: 1\./)).toBeInTheDocument();
      expect(kpi(/^Not checked in: 1\./)).toBeInTheDocument();
      expect(inList().queryAllByText("Chitra Nair")).toHaveLength(0);
      expect(inList().getAllByText("Ben Iyer").length).toBeGreaterThan(0);
    });

    it("excludes an employee who joins after today", async () => {
      mockApi({ days: [], employees: [stillActive, notYetJoined] });
      render(<AttendanceDashboardPage />);
      expect(await findKpi(/^Total employees: 1\./)).toBeInTheDocument();
      expect(inList().queryAllByText("Dev Shah")).toHaveLength(0);
    });

    it("is deterministic: the same employee data and the same selected date produce the same KPI regardless of how many times it's recomputed", async () => {
      mockApi({ days: [], employees: [stillActive, terminated] });
      const { unmount } = render(<AttendanceDashboardPage />);
      // Same inputs, rendered twice independently (fresh mount each time) — both must land on
      // the one genuinely-employed person (emp-2), never the terminated emp-3.
      expect(await findKpi(/^Total employees: 1\./)).toBeInTheDocument();
      unmount();

      mockApi({ days: [], employees: [stillActive, terminated] });
      render(<AttendanceDashboardPage />);
      expect(await findKpi(/^Total employees: 1\./)).toBeInTheDocument();
    });

    it("does not apply the 'no record yet' inference to a historical date (yesterday)", async () => {
      // Selecting yesterday as a custom range must NOT invoke the today-only inference — a
      // terminated employee with no row on a historical date simply isn't in the row set, and a
      // still-active employee with genuinely no row that day must NOT be inflated into the count
      // the way "today" deliberately is.
      const yesterday = addDays(TODAY, -1);
      searchParams = new URLSearchParams({ range: "custom", from: yesterday, to: yesterday });
      mockApi({ days: [], employees: [stillActive, terminated] });
      render(<AttendanceDashboardPage />);
      expect(await findKpi(/^Total employees: 0\./)).toBeInTheDocument();
      expect(kpi(/^Not checked in: 0\./)).toBeInTheDocument();
    });
  });

  describe("drill-down and filters", () => {
    it("narrows the employee list from a KPI card, shows a chip, writes the URL, and toggles off", async () => {
      mockApi({ days: sampleDays() });
      const user = userEvent.setup();
      render(<AttendanceDashboardPage />);
      await findKpi(/^Absent: 1\./);
      expect(inList().getAllByText("Ben Iyer").length).toBeGreaterThan(0);

      await user.click(kpi(/^Absent: 1\./));

      await waitFor(() => expect(inList().queryAllByText("Ben Iyer")).toHaveLength(0));
      expect(inList().getAllByText("Chitra Nair").length).toBeGreaterThan(0);
      expect(screen.getByRole("button", { name: /remove filter status: absent/i })).toBeInTheDocument();
      await waitFor(() => expect(replaceMock).toHaveBeenLastCalledWith("/app/attendance?bucket=ABSENT", { scroll: false }));

      await user.click(kpi(/^Absent: 1\./));
      await waitFor(() => expect(inList().getAllByText("Ben Iyer").length).toBeGreaterThan(0));
    });

    it("drills from the late KPI to late employees only", async () => {
      mockApi({ days: sampleDays() });
      const user = userEvent.setup();
      render(<AttendanceDashboardPage />);
      await user.click(await findKpi(/^Late: 1\./));
      await waitFor(() => expect(inList().queryAllByText("Asha Rao")).toHaveLength(0));
      expect(inList().getAllByText("Ben Iyer").length).toBeGreaterThan(0);
      expect(screen.getByRole("button", { name: /remove filter late arrivals/i })).toBeInTheDocument();
    });

    it("drills from a status-chart row", async () => {
      mockApi({ days: sampleDays() });
      const user = userEvent.setup();
      render(<AttendanceDashboardPage />);
      const chart = await screen.findByRole("heading", { name: /status distribution/i });
      const card = chart.closest("[id='att-status']") as HTMLElement;
      await user.click(within(card).getByRole("button", { name: /^Absent: 1\./ }));
      await waitFor(() => expect(inList().queryAllByText("Asha Rao")).toHaveLength(0));
    });

    // F5-1 regression: a KPI-card drill must stay scoped to the focus date even when a
    // multi-day range is selected — only F5-1's Needs Attention drill gets the whole range.
    it("keeps a focus-date KPI drill scoped to the focus date, not the whole selected range", async () => {
      const earlier = addDays(TODAY, -3);
      const days = [
        makeDay({ employee_id: "emp-1", attendance_date: earlier, is_late: true, late_minutes: 20 }),
        makeDay({ employee_id: "emp-2", attendance_date: TODAY, is_late: true, late_minutes: 10 }),
      ];
      searchParams = new URLSearchParams(`range=custom&from=${earlier}&to=${TODAY}`);
      mockApi({ days });
      const user = userEvent.setup();
      render(<AttendanceDashboardPage />);
      // Only emp-2's row falls on the focus date (range.to === TODAY), so the KPI itself reads 1.
      await user.click(await findKpi(/^Late: 1\./));
      await waitFor(() => expect(inList().getAllByText("Ben Iyer").length).toBeGreaterThan(0));
      expect(inList().queryAllByText("Asha Rao")).toHaveLength(0);
    });

    it("filters by the attendance-status select and resets everything", async () => {
      mockApi({ days: sampleDays() });
      const user = userEvent.setup();
      render(<AttendanceDashboardPage />);
      await findKpi(/^Absent: 1\./);

      await user.selectOptions(screen.getByLabelText("Attendance status"), "ABSENT");
      await waitFor(() => expect(inList().queryAllByText("Asha Rao")).toHaveLength(0));
      expect(screen.getByRole("button", { name: /reset filters/i })).toBeEnabled();

      await user.click(screen.getByRole("button", { name: /reset filters/i }));
      await waitFor(() => expect(inList().getAllByText("Asha Rao").length).toBeGreaterThan(0));
      expect(screen.queryByRole("list", { name: /active filters/i })).not.toBeInTheDocument();
    });

    it("filters to one employee, scoping the KPIs to them", async () => {
      mockApi({ days: sampleDays() });
      const user = userEvent.setup();
      render(<AttendanceDashboardPage />);
      await findKpi(/^Absent: 1\./);
      await user.selectOptions(screen.getByLabelText("Employee"), "emp-2");
      await waitFor(() => expect(kpi(/^Total employees: 1\./)).toBeInTheDocument());
      expect(kpi(/^Absent: 0\./)).toBeInTheDocument();
    });

    it("filters by shift using the shift names the API returned", async () => {
      mockApi({ days: sampleDays() });
      const user = userEvent.setup();
      render(<AttendanceDashboardPage />);
      await findKpi(/^Absent: 1\./);
      const shiftSelect = await screen.findByLabelText("Shift");
      await user.selectOptions(shiftSelect, "shift-1");
      await waitFor(() => expect(kpi(/^Total employees: 1\./)).toBeInTheDocument());
    });

    it("filters by employment status from the employee directory", async () => {
      mockApi({ days: sampleDays() });
      const user = userEvent.setup();
      render(<AttendanceDashboardPage />);
      await findKpi(/^Absent: 1\./);
      await user.selectOptions(await screen.findByLabelText("Employment status"), "PROBATION");
      await waitFor(() => expect(kpi(/^Total employees: 1\./)).toBeInTheDocument());
      expect(kpi(/^Absent: 1\./)).toBeInTheDocument();
    });

    it("restores filters from a shared URL", async () => {
      searchParams = new URLSearchParams("bucket=ABSENT");
      mockApi({ days: sampleDays() });
      render(<AttendanceDashboardPage />);
      expect(await screen.findByRole("button", { name: /remove filter status: absent/i })).toBeInTheDocument();
      await waitFor(() => expect(inList().queryAllByText("Asha Rao")).toHaveLength(0));
    });

    it("requests a custom range from the server", async () => {
      mockApi({ days: sampleDays() });
      const user = userEvent.setup();
      render(<AttendanceDashboardPage />);
      await findKpi(/^Absent: 1\./);
      await user.click(screen.getByRole("button", { name: "This month" }));
      await waitFor(() => {
        const calls = mockedGet.mock.calls.map((c) => c[0]).filter((p) => p.startsWith("/attendance/days?"));
        // The fetch window is the range widened to ≥14 days of trend context, so it starts on or
        // before the first of the month and always ends today.
        const wide = calls.filter((p) => new URLSearchParams(p.split("?")[1]).get("date_from")! <= `${TODAY.slice(0, 7)}-01`);
        expect(wide.length).toBeGreaterThan(0);
        expect(wide.every((p) => new URLSearchParams(p.split("?")[1]).get("date_to") === TODAY)).toBe(true);
      });
      await user.click(screen.getByRole("button", { name: "Custom" }));
      expect(screen.getByLabelText("From")).toBeInTheDocument();
      expect(screen.getByLabelText("To")).toBeInTheDocument();
    });

    it("does not offer department / branch filters the data can't support, and says why", async () => {
      mockApi({ days: sampleDays() });
      render(<AttendanceDashboardPage />);
      await findKpi(/^Absent: 1\./);
      expect(screen.queryByRole("combobox", { name: /department|branch|designation|location|work mode/i })).not.toBeInTheDocument();
      // Both the breakdown card and the coverage notice explain the gap.
      expect(screen.getByText("Not shown on this dashboard")).toBeInTheDocument();
      expect(screen.getAllByText(/one request per employee/i).length).toBeGreaterThanOrEqual(2);
    });
  });

  describe("company + periods", () => {
    it("scopes the attendance periods to the chosen company", async () => {
      mockApi({ days: sampleDays(), periods: [PERIOD_OPEN] });
      const user = userEvent.setup();
      render(<AttendanceDashboardPage />);
      const select = await screen.findByLabelText("Company (periods)");
      await user.selectOptions(select, "le-2");
      await waitFor(() =>
        expect(mockedGet).toHaveBeenCalledWith("/attendance-periods?legal_entity_id=le-2"),
      );
      expect(screen.getByRole("button", { name: /remove filter company: abc services llp/i })).toBeInTheDocument();
    });

    it("shows period state with its entity, and surfaces a blocked period as a payroll blocker", async () => {
      mockApi({ days: sampleDays(), periods: [PERIOD_OPEN] });
      render(<AttendanceDashboardPage />);
      const section = (await screen.findByRole("heading", { name: /attendance periods/i })).closest("[id='att-periods']") as HTMLElement;
      expect(await within(section).findByText("Current month")).toBeInTheDocument();
      expect(within(section).getByText(/ABC India Pvt Ltd/)).toBeInTheDocument();
      expect(within(section).getByText("Validation blocked")).toBeInTheDocument();
      expect(within(section).getByRole("link", { name: /current month/i })).toHaveAttribute("href", "/app/attendance-periods/per-1");
      expect(await screen.findByText("Payroll period blocked")).toBeInTheDocument();
    });

    it("totals the period summary for the monthly view", async () => {
      mockApi({
        days: sampleDays(),
        periods: [PERIOD_OPEN],
        summary: [
          { employee_id: "emp-1", present_days: "20", absent_days: "1", leave_days: "2", holiday_days: "1", weekly_off_days: "4", half_days: "0", lop_days: "1", on_duty_days: "0", incomplete_days: "0", not_employed_days: "0", unpaid_off_days: "0", paid_days: "29", payable_days: "29", ot_minutes_normal: 60, ot_minutes_weekly_off: 0, ot_minutes_holiday: 0, ot_minutes_night: 0, comp_off_minutes_earned: 0, late_count: 2, worked_minutes_total: 9000, generated_at: "x", frozen: false },
        ],
      });
      render(<AttendanceDashboardPage />);
      const section = (await screen.findByRole("heading", { name: /monthly attendance summary/i })).closest("[id='att-monthly']") as HTMLElement;
      expect(await within(section).findByText("Live preview")).toBeInTheDocument();
      expect(within(section).getByText("Payable days").nextSibling).toHaveTextContent("29");
      expect(within(section).getByText("LOP").nextSibling).toHaveTextContent("1");
    });
  });

  describe("needs attention", () => {
    it("lists exceptions with severity, counts and a working action", async () => {
      const days = [
        ...sampleDays(),
        makeDay({ employee_id: "emp-1", attendance_date: TODAY, id: "d-missing", attendance_status: "INCOMPLETE", missing_punch: true, actual_last_out: null }),
      ];
      mockApi({ days, regularizations: [{ id: "r1", employee_id: "emp-1" }] });
      const user = userEvent.setup();
      render(<AttendanceDashboardPage />);
      const section = (await screen.findByRole("heading", { name: /needs attention/i })).closest("[id='att-attention']") as HTMLElement;
      expect(await within(section).findByText("Missing punches")).toBeInTheDocument();
      expect(within(section).getByText("Regularization pending")).toBeInTheDocument();
      expect(within(section).getByRole("link", { name: /review/i })).toHaveAttribute("href", "/app/regularizations");

      await user.click(within(section).getByRole("button", { name: /view all: missing punches/i }));
      expect(await screen.findByRole("button", { name: /remove filter missing punch/i })).toBeInTheDocument();
    });

    // F5-1: Needs Attention counts a whole-range item ("missing punches") across the whole
    // selected range, so its "View all" must drill into that same range — not silently narrow to
    // the focus date (range.to) alone, which would drop every affected employee/day outside it.
    it("drills a whole-range item into the full selected range, not just the focus date (F5-1)", async () => {
      const earlier = addDays(TODAY, -3);
      const days = [
        makeDay({ employee_id: "emp-1", attendance_date: earlier, id: "d-early", missing_punch: true, actual_last_out: null }),
        makeDay({ employee_id: "emp-2", attendance_date: TODAY, id: "d-focus", missing_punch: true, actual_last_out: null }),
      ];
      searchParams = new URLSearchParams(`range=custom&from=${earlier}&to=${TODAY}`);
      mockApi({ days });
      const user = userEvent.setup();
      render(<AttendanceDashboardPage />);
      const section = (await screen.findByRole("heading", { name: /needs attention/i })).closest("[id='att-attention']") as HTMLElement;
      expect(await within(section).findByText(/2 employees affected/i)).toBeInTheDocument();

      await user.click(within(section).getByRole("button", { name: /view all: missing punches/i }));

      // Both employees must appear — the one on the first day of the range AND the one on the
      // last day — not only the employee whose row happens to fall on the focus date.
      await waitFor(() => expect(inList().getAllByText("Asha Rao").length).toBeGreaterThan(0));
      expect(inList().getAllByText("Ben Iyer").length).toBeGreaterThan(0);
      expect(screen.getByRole("button", { name: /remove filter missing punch/i })).toBeInTheDocument();
    });

    it("says so when nothing needs attention", async () => {
      mockApi({ days: [makeDay({ employee_id: "emp-1", attendance_date: TODAY })] });
      render(<AttendanceDashboardPage />);
      expect(await screen.findByText(/nothing needs attention/i)).toBeInTheDocument();
    });
  });

  describe("role-based views", () => {
    it("shows an employee only their own dashboard — no organisation panels, no org requests", async () => {
      authUser = { employee_id: "emp-1", company_timezone: "UTC", permissions: ["ATTENDANCE.VIEW", "ATTENDANCE.PUNCH"] };
      mockApi({ days: [makeDay({ employee_id: "emp-1", attendance_date: TODAY })] });
      render(<AttendanceDashboardPage />);

      expect(await screen.findByRole("heading", { name: "This month" })).toBeInTheDocument();
      expect(screen.getByRole("heading", { name: "Today" })).toBeInTheDocument();
      expect(screen.getByRole("button", { name: /record punch/i })).toBeInTheDocument();
      expect(screen.queryByRole("heading", { name: /needs attention/i })).not.toBeInTheDocument();
      expect(screen.queryByRole("heading", { name: /attendance periods/i })).not.toBeInTheDocument();
      expect(screen.queryByLabelText("Company (periods)")).not.toBeInTheDocument();

      const paths = [...mockedGet.mock.calls.map((c) => c[0]), ...mockedGetList.mock.calls.map((c) => c[0])];
      expect(paths.some((p) => p.startsWith("/attendance-periods"))).toBe(false);
      expect(paths).not.toContain("/employees");
      expect(paths.some((p) => p.startsWith("/overtime"))).toBe(false);
    });

    it("gives a manager the team dashboard without the organisation-only period panels", async () => {
      authUser = { employee_id: "emp-mgr", company_timezone: "UTC", permissions: ["ATTENDANCE.VIEW", "ATTENDANCE.OVERTIME_APPROVE"] };
      mockApi({ days: sampleDays() });
      render(<AttendanceDashboardPage />);
      expect(await findKpi(/^Present: 2\./)).toBeInTheDocument();
      expect(screen.getByRole("heading", { name: /needs attention/i })).toBeInTheDocument();
      expect(screen.queryByRole("heading", { name: /attendance periods/i })).not.toBeInTheDocument();
      expect(screen.queryByLabelText("Company (periods)")).not.toBeInTheDocument();
      // No pointless lookups the manager can't make.
      expect(mockedGetList).not.toHaveBeenCalled();
    });

    it("only offers Record punch to a caller who can punch", async () => {
      authUser = { employee_id: "emp-mgr", company_timezone: "UTC", permissions: ["ATTENDANCE.VIEW", "ATTENDANCE.VIEW_ALL"] };
      mockApi({ days: sampleDays() });
      render(<AttendanceDashboardPage />);
      await findKpi(/^Present: 2\./);
      expect(screen.queryByRole("button", { name: /record punch/i })).not.toBeInTheDocument();
    });

    it("opens the punch entry dialog from the header action", async () => {
      mockApi({ days: [] });
      const user = userEvent.setup();
      render(<AttendanceDashboardPage />);
      await screen.findByText(/no attendance days match these filters/i);
      await user.click(screen.getByRole("button", { name: /record punch/i }));
      expect(await screen.findByLabelText(/punch time/i)).toBeInTheDocument();
    });
  });

  describe("responsive", () => {
    it("moves the filters into a drawer on small screens", async () => {
      mockApi({ days: sampleDays() });
      const user = userEvent.setup();
      render(<AttendanceDashboardPage />);
      await findKpi(/^Absent: 1\./);
      await user.click(screen.getByRole("button", { name: /^filters/i }));
      const drawer = await screen.findByRole("dialog");
      expect(within(drawer).getByText("Filters")).toBeInTheDocument();
      expect(within(drawer).getAllByLabelText("Attendance status").length).toBeGreaterThan(0);
      expect(within(drawer).getByRole("button", { name: /done/i })).toBeInTheDocument();
    });

    it("renders KPI cards in a horizontally scrollable strip and the list as cards for narrow screens", async () => {
      mockApi({ days: sampleDays() });
      const { container } = render(<AttendanceDashboardPage />);
      await findKpi(/^Absent: 1\./);
      expect(container.querySelector(".overflow-x-auto.snap-x")).not.toBeNull();
      // Desktop table + mobile cards are both rendered; CSS (`md:hidden` / `hidden md:block`) picks one.
      expect(container.querySelector("ul.md\\:hidden")).not.toBeNull();
      expect(container.querySelector(".hidden.md\\:block table")).not.toBeNull();
    });
  });

  describe("reports", () => {
    it("switches between reports built from existing data and states that export is unavailable", async () => {
      mockApi({ days: sampleDays() });
      const user = userEvent.setup();
      render(<AttendanceDashboardPage />);
      const reports = (await screen.findByRole("heading", { name: "Reports" })).closest("[id='att-reports']") as HTMLElement;
      expect(within(reports).getByRole("tab", { name: "Daily attendance", selected: true })).toBeInTheDocument();
      expect(within(reports).getAllByText("Asha Rao").length).toBeGreaterThan(0);

      await user.click(within(reports).getByRole("tab", { name: "Late / early" }));
      expect(within(reports).getByText("Ben Iyer")).toBeInTheDocument();
      expect(within(reports).queryByText("Asha Rao")).not.toBeInTheDocument();

      expect(within(reports).queryByRole("button", { name: /export|csv|pdf|excel/i })).not.toBeInTheDocument();
      expect(within(reports).getByText(/export .* is not available yet/i)).toBeInTheDocument();
    });

    it("searches within a report", async () => {
      mockApi({ days: sampleDays() });
      const user = userEvent.setup();
      render(<AttendanceDashboardPage />);
      const reports = (await screen.findByRole("heading", { name: "Reports" })).closest("[id='att-reports']") as HTMLElement;
      await user.type(within(reports).getByLabelText("Search report"), "chitra");
      expect(within(reports).getByText("Chitra Nair")).toBeInTheDocument();
      expect(within(reports).queryByText("Asha Rao")).not.toBeInTheDocument();
    });

    // F6-1: the Overtime report read `data.overtime` directly — fetched over the widened 14-day
    // trend-context window, not the selected range — so for any selected range narrower than 14
    // days it silently included overtime rows from before the range start.
    describe("Overtime report date-range scoping (F6-1)", () => {
      const overtimeBase = {
        company_id: "company-1",
        attendance_day_id: "d",
        overtime_policy_version_id: "p",
        day_class: "NORMAL" as const,
        classification_code: null,
        configured_multiplier: null,
        minutes_approved: 0,
        status: "PENDING" as const,
      };

      it("excludes an overtime row before the selected range even though it falls inside the wider trend window", async () => {
        const start = addDays(TODAY, -3);
        const outOfRange = addDays(TODAY, -10); // before `start`, but inside the ≥14-day trend window
        searchParams = new URLSearchParams(`range=custom&from=${start}&to=${TODAY}`);
        mockApi({
          days: sampleDays(),
          overtime: [
            { ...overtimeBase, id: "ot-out", employee_id: "emp-1", attendance_date: outOfRange, minutes_detected: 45 },
            { ...overtimeBase, id: "ot-in", employee_id: "emp-2", attendance_date: TODAY, minutes_detected: 30 },
          ],
        });
        const user = userEvent.setup();
        render(<AttendanceDashboardPage />);
        const reports = (await screen.findByRole("heading", { name: "Reports" })).closest("[id='att-reports']") as HTMLElement;
        await user.click(within(reports).getByRole("tab", { name: "Overtime" }));

        expect(await within(reports).findByText("Ben Iyer")).toBeInTheDocument();
        expect(within(reports).queryByText("Asha Rao")).not.toBeInTheDocument();
      });

      it("includes both range boundary dates (inclusive start and end)", async () => {
        const start = addDays(TODAY, -3);
        searchParams = new URLSearchParams(`range=custom&from=${start}&to=${TODAY}`);
        mockApi({
          days: sampleDays(),
          overtime: [
            { ...overtimeBase, id: "ot-start", employee_id: "emp-1", attendance_date: start, minutes_detected: 15 },
            { ...overtimeBase, id: "ot-end", employee_id: "emp-2", attendance_date: TODAY, minutes_detected: 20 },
          ],
        });
        const user = userEvent.setup();
        render(<AttendanceDashboardPage />);
        const reports = (await screen.findByRole("heading", { name: "Reports" })).closest("[id='att-reports']") as HTMLElement;
        await user.click(within(reports).getByRole("tab", { name: "Overtime" }));

        expect(await within(reports).findByText("Asha Rao")).toBeInTheDocument();
        expect(within(reports).getByText("Ben Iyer")).toBeInTheDocument();
      });

      it("leaves the dashboard's own Overtime panel unaffected — it already scoped to the range before this fix", async () => {
        const start = addDays(TODAY, -3);
        const outOfRange = addDays(TODAY, -10);
        searchParams = new URLSearchParams(`range=custom&from=${start}&to=${TODAY}`);
        mockApi({
          days: sampleDays(),
          overtime: [
            { ...overtimeBase, id: "ot-out", employee_id: "emp-1", attendance_date: outOfRange, minutes_detected: 45 },
            { ...overtimeBase, id: "ot-in", employee_id: "emp-2", attendance_date: TODAY, minutes_detected: 30 },
          ],
        });
        render(<AttendanceDashboardPage />);
        const overtimeSection = (await screen.findByRole("heading", { name: "Overtime" })).closest("[id='att-overtime']") as HTMLElement;
        // Only the 30m in-range record counts — the 45m out-of-range record was already excluded
        // by `overtimeSummary`'s own range filter, both before and after the F6-1 fix.
        expect(within(overtimeSection).getByText("Total detected").nextSibling).toHaveTextContent("0h 30m");
        expect(within(overtimeSection).queryByText("1h 15m")).not.toBeInTheDocument();
      });
    });
  });

  describe("request budget", () => {
    it("loads the dashboard with a small, bounded number of requests", async () => {
      mockApi({ days: sampleDays(), periods: [PERIOD_OPEN] });
      render(<AttendanceDashboardPage />);
      await findKpi(/^Present: 2\./);
      await screen.findByText("Current month");
      await waitFor(() => {
        const total = mockedGet.mock.calls.length + mockedGetList.mock.calls.length;
        expect(total).toBeLessThanOrEqual(10);
      });
      // Exactly one request for the attendance days — every KPI/chart/list derives from it.
      const dayCalls = mockedGet.mock.calls.filter((c) => c[0].startsWith("/attendance/days?"));
      expect(dayCalls).toHaveLength(1);
    });
  });
});
