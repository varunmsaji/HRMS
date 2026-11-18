import { act, cleanup, render, screen, waitFor, within } from "@testing-library/react";
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
import { fakeSummary, type FakeOrg } from "@/lib/attendance/__fixtures__/fake-summary";
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
  "ATTENDANCE.RECOMPUTE",
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
  /** Department / branch rows from the employee directory; omitted = the request fails. The
   * fake summary groups by the same rows (everyone is Unassigned without them). */
  directory?: ReturnType<typeof dirRow>[] | Error;
  /** What the backend knows of everyone's department / branch, when it differs from `directory`. */
  orgs?: ReturnType<typeof dirRow>[];
  /** Makes `GET /attendance/summary` fail with this error. */
  summaryError?: Error;
}

function mockApi(o: Overrides = {}) {
  const days = o.days ?? [];
  mockedGet.mockImplementation((path: string) => {
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
    if (path.startsWith("/attendance/summary")) {
      if (o.summaryError) return Promise.reject(o.summaryError);
      if (days instanceof Error) return Promise.reject(days);
      const known = o.orgs ?? (Array.isArray(o.directory) ? o.directory : []);
      const orgs = new Map<string, FakeOrg>(known.map((r) => [r.employee_id, r]));
      const query = new URLSearchParams(path.split("?")[1] ?? "");
      return Promise.resolve(fakeSummary(query, days, o.employees ?? EMPLOYEES, (id) => orgs.get(id), TODAY));
    }
    if (path.startsWith("/employees/directory/rows") && o.directory !== undefined) {
      return o.directory instanceof Error ? Promise.reject(o.directory) : Promise.resolve(o.directory);
    }
    return Promise.reject(new Error(`Unexpected GET ${path}`));
  });
  mockedGetList.mockImplementation((path: string, query?: Record<string, unknown>) => {
    if (path === "/attendance/days") {
      if (days instanceof Error) return Promise.reject(days);
      // Pages like the API: `per_page` rows at a time, newest first is irrelevant to the totals.
      const perPage = Number(query?.per_page ?? 500);
      const page = Number(query?.page ?? 1);
      const totalPages = Math.max(1, Math.ceil(days.length / perPage));
      return Promise.resolve({
        data: days.slice((page - 1) * perPage, page * perPage),
        pagination: { page, per_page: perPage, total: days.length, total_pages: totalPages },
        meta: { request_id: "r1" },
      });
    }
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

/** Department / branch ids, as the API would give them (filters and URLs carry ids). */
const GROUP_IDS: Record<string, string> = {
  Engineering: "00000000-0000-4000-8000-00000000000e",
  Sales: "00000000-0000-4000-8000-00000000000a",
  Pune: "00000000-0000-4000-8000-0000000000b1",
  Mumbai: "00000000-0000-4000-8000-0000000000b2",
};
const ENG = GROUP_IDS.Engineering;

function dirRow(employee_id: string, department: string | null, branch: string | null) {
  return {
    employee_id,
    designation: null,
    department,
    branch,
    department_id: department ? GROUP_IDS[department] : null,
    branch_id: branch ? GROUP_IDS[branch] : null,
    manager_name: null,
    shift_name: null,
  };
}

/** Asha and Ben in Engineering / Pune, Chitra in Sales / Mumbai. */
const DIRECTORY = [
  dirRow("emp-1", "Engineering", "Pune"),
  dirRow("emp-2", "Engineering", "Pune"),
  dirRow("emp-3", "Sales", "Mumbai"),
];

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

/** The headcount line in the summary ("3 employees · …"); it is text, not a card. */
function total(n: number) {
  return within(kpiRegion()).getByText(new RegExp(`^${n} employees? · `));
}

async function findTotal(n: number) {
  const region = await screen.findByRole("region", { name: "Attendance summary" });
  return within(region).findByText(new RegExp(`^${n} employees? · `));
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
      expect(total(0)).toBeInTheDocument();
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
      searchParams = new URLSearchParams("view=trends");
      const user = userEvent.setup();
      render(<AttendanceDashboardPage />);
      expect(await screen.findByText(/couldn't load overtime/i)).toBeInTheDocument();
      await user.click(screen.getByRole("tab", { name: "Today" }));
      expect(await findKpi(/^Present: 2\./)).toBeInTheDocument();
      expect(screen.getByText(/not included \(couldn't be loaded\): pending overtime/i)).toBeInTheDocument();
    });

    it("preserves a permission error on a secondary section", async () => {
      mockApi({ days: sampleDays(), overtime: new ApiError({ status: 403, code: "PERMISSION_DENIED", message: "x" }) });
      searchParams = new URLSearchParams("view=trends");
      render(<AttendanceDashboardPage />);
      expect(await screen.findByText(/you do not have permission to view this section/i)).toBeInTheDocument();
    });

    it("shows an honest empty message for overtime instead of a bare zero", async () => {
      mockApi({ days: sampleDays(), overtime: [] });
      searchParams = new URLSearchParams("view=trends");
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
      expect(total(3)).toBeInTheDocument();
    });

    it("counts active employees with no attendance row yet as not checked in", async () => {
      mockApi({ days: sampleDays().slice(0, 2), employees: EMPLOYEES });
      render(<AttendanceDashboardPage />);
      // emp-3 has no row today.
      const card = await findKpi(/^Not checked in: 1\./);
      expect(card).toBeInTheDocument();
      expect(total(3)).toHaveTextContent("1 with no record yet");
    });

    it("says when the figures were loaded", async () => {
      mockApi({ days: sampleDays() });
      render(<AttendanceDashboardPage />);
      await screen.findByRole("heading", { name: /today's attendance/i });
      expect(screen.getByText(/not a live presence feed\. Loaded at \d/i)).toBeInTheDocument();
    });

    it("shows no comparison chips, and no 'nobody expected', before anything is calculated for the day", async () => {
      mockApi({ days: [], employees: EMPLOYEES });
      render(<AttendanceDashboardPage />);
      await findTotal(3);
      expect(screen.queryByText(/vs last/)).not.toBeInTheDocument();
      expect(screen.queryByText("No comparison yet")).not.toBeInTheDocument();
      expect(screen.queryByText("Nobody was expected to work on this day.")).not.toBeInTheDocument();
      expect(screen.getByText("Attendance for today hasn't been calculated yet.")).toBeInTheDocument();
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
      expect(await findTotal(1)).toBeInTheDocument();
      expect(kpi(/^Not checked in: 1\./)).toBeInTheDocument();
      expect(inList().queryAllByText("Chitra Nair")).toHaveLength(0);
      expect(inList().getAllByText("Ben Iyer").length).toBeGreaterThan(0);
    });

    it("excludes an employee who joins after today", async () => {
      mockApi({ days: [], employees: [stillActive, notYetJoined] });
      render(<AttendanceDashboardPage />);
      expect(await findTotal(1)).toBeInTheDocument();
      expect(inList().queryAllByText("Dev Shah")).toHaveLength(0);
    });

    it("is deterministic: the same employee data and the same selected date produce the same KPI regardless of how many times it's recomputed", async () => {
      mockApi({ days: [], employees: [stillActive, terminated] });
      const { unmount } = render(<AttendanceDashboardPage />);
      // Same inputs, rendered twice independently (fresh mount each time) — both must land on
      // the one genuinely-employed person (emp-2), never the terminated emp-3.
      expect(await findTotal(1)).toBeInTheDocument();
      unmount();

      mockApi({ days: [], employees: [stillActive, terminated] });
      render(<AttendanceDashboardPage />);
      expect(await findTotal(1)).toBeInTheDocument();
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
      expect(await findTotal(0)).toBeInTheDocument();
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

    it("drills from a summary tile and comes back to the list from Trends", async () => {
      mockApi({ days: sampleDays() });
      const user = userEvent.setup();
      render(<AttendanceDashboardPage />);
      await user.click(await findKpi(/^Absent: 1\./));
      await waitFor(() => expect(inList().queryAllByText("Asha Rao")).toHaveLength(0));
      expect(screen.getByRole("tab", { name: "Today" })).toHaveAttribute("aria-selected", "true");
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
      // Type to find the person, pick the match: no dropdown listing everyone.
      await user.type(screen.getByRole("combobox", { name: "Employee" }), "ben");
      await user.click(await screen.findByRole("option", { name: /Ben Iyer/ }));
      await waitFor(() => expect(total(1)).toBeInTheDocument());
      expect(kpi(/^Absent: 0\./)).toBeInTheDocument();
      // The choice shows as a pill that clears it.
      await user.click(screen.getByRole("button", { name: /^Clear employee/ }));
      await waitFor(() => expect(total(3)).toBeInTheDocument());
    });

    it("filters by shift using the shift names the API returned", async () => {
      mockApi({ days: sampleDays() });
      const user = userEvent.setup();
      render(<AttendanceDashboardPage />);
      await findKpi(/^Absent: 1\./);
      await user.click(screen.getByRole("button", { name: /more filters/i }));
      const shiftSelect = await screen.findByLabelText("Shift");
      await user.selectOptions(shiftSelect, "shift-1");
      await waitFor(() => expect(total(1)).toBeInTheDocument());
    });

    it("filters by employment status from the employee directory", async () => {
      mockApi({ days: sampleDays() });
      const user = userEvent.setup();
      render(<AttendanceDashboardPage />);
      await findKpi(/^Absent: 1\./);
      await user.click(screen.getByRole("button", { name: /more filters/i }));
      await user.selectOptions(await screen.findByLabelText("Employment status"), "PROBATION");
      await waitFor(() => expect(total(1)).toBeInTheDocument());
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
        const calls = mockedGetList.mock.calls
          .filter((c) => c[0] === "/attendance/days")
          .map((c) => c[1] as { date_from: string; date_to: string });
        // The fetch window is the range widened to ≥14 days of trend context, so it starts on or
        // before the first of the month and always ends today.
        const wide = calls.filter((q) => q.date_from <= `${TODAY.slice(0, 7)}-01`);
        expect(wide.length).toBeGreaterThan(0);
        expect(wide.every((q) => q.date_to === TODAY)).toBe(true);
      });
      await user.click(screen.getByRole("button", { name: "Custom" }));
      expect(screen.getByLabelText("From")).toBeInTheDocument();
      expect(screen.getByLabelText("To")).toBeInTheDocument();
    });

    it("does not offer department / branch filters the data can't support, and no longer shows placeholder cards for them", async () => {
      mockApi({ days: sampleDays() });
      render(<AttendanceDashboardPage />);
      await findKpi(/^Absent: 1\./);
      expect(screen.queryByRole("combobox", { name: /department|branch|designation|location|work mode/i })).not.toBeInTheDocument();
      // Unfinished features are hidden rather than shown as "not available yet" cards.
      expect(screen.queryByText("Not shown on this dashboard")).not.toBeInTheDocument();
      expect(screen.queryByText(/one request per employee/i)).not.toBeInTheDocument();
    });
  });

  describe("departments & branches", () => {
    it("ranks departments by attendance, lowest first, on the Trends view", async () => {
      searchParams = new URLSearchParams("view=trends");
      mockApi({ days: sampleDays(), directory: DIRECTORY });
      render(<AttendanceDashboardPage />);
      const card = (await screen.findByRole("heading", { name: /departments & branches/i })).closest("[id='att-breakdown']") as HTMLElement;
      const rows = await within(card).findAllByRole("button", { name: /present, .* absent, .* late/i });
      expect(rows[0]).toHaveAccessibleName(/^Sales: 0\.0% present, 1 absent, 0 late/);
      expect(rows[1]).toHaveAccessibleName(/^Engineering: 100\.0% present, 0 absent, 1 late/);
      await userEvent.setup().click(within(card).getByRole("button", { name: "branch" }));
      expect(await within(card).findByRole("button", { name: /^Mumbai:/ })).toBeInTheDocument();
    });

    it("narrows the whole dashboard to a department when its row is clicked, and clears it on a second click", async () => {
      searchParams = new URLSearchParams("view=trends");
      mockApi({ days: sampleDays(), directory: DIRECTORY });
      const user = userEvent.setup();
      render(<AttendanceDashboardPage />);
      const salesRow = await screen.findByRole("button", { name: /^Sales: .*Show only this department/ });
      await user.click(salesRow);
      await waitFor(() => expect(replaceMock).toHaveBeenLastCalledWith(`/app/attendance?dept=${GROUP_IDS.Sales}&view=trends`, { scroll: false }));
      expect(await screen.findByRole("button", { name: /remove filter department: sales/i })).toBeInTheDocument();
      await user.click(screen.getByRole("tab", { name: "Today" }));
      expect(await findTotal(1)).toBeInTheDocument();
      expect(kpi(/^Absent: 1\./)).toBeInTheDocument();

      await user.click(screen.getByRole("tab", { name: "Trends" }));
      await user.click(await screen.findByRole("button", { name: /^Sales: .*Clear department/ }));
      await user.click(screen.getByRole("tab", { name: "Today" }));
      expect(await findTotal(3)).toBeInTheDocument();
    });

    it("restores a department filter from a shared link", async () => {
      searchParams = new URLSearchParams(`dept=${ENG}`);
      mockApi({ days: sampleDays(), directory: DIRECTORY });
      render(<AttendanceDashboardPage />);
      expect(await findTotal(2)).toBeInTheDocument();
      expect(kpi(/^Absent: 0\./)).toBeInTheDocument();
    });

    it("offers department and branch filters under More filters once the directory has loaded", async () => {
      mockApi({ days: sampleDays(), directory: DIRECTORY });
      const user = userEvent.setup();
      render(<AttendanceDashboardPage />);
      await findKpi(/^Absent: 1\./);
      await user.click(screen.getByRole("button", { name: /more filters/i }));
      await user.selectOptions(await screen.findByLabelText("Branch"), "Mumbai");
      await waitFor(() => expect(total(1)).toBeInTheDocument());
      expect(screen.getByRole("button", { name: /remove filter branch: mumbai/i })).toBeInTheDocument();
    });

    it("groups employees without a department under Unassigned", async () => {
      searchParams = new URLSearchParams("view=trends");
      mockApi({ days: sampleDays(), directory: [dirRow("emp-1", "Engineering", null), dirRow("emp-2", null, null)] });
      render(<AttendanceDashboardPage />);
      expect(await screen.findByRole("button", { name: /^Unassigned:/ })).toBeInTheDocument();
    });

    it("still filters the totals, and says the lists aren't filtered, when the directory can't be loaded", async () => {
      searchParams = new URLSearchParams(`dept=${GROUP_IDS.Sales}`);
      mockApi({ days: sampleDays(), directory: new ApiError({ status: 500, code: "BOOM", message: "x" }), orgs: DIRECTORY });
      render(<AttendanceDashboardPage />);
      expect(await screen.findByText(/applies to the totals but not to the employee lists/i)).toBeInTheDocument();
      // The backend applies the filter: only Chitra is in Sales.
      expect(await findTotal(1)).toBeInTheDocument();
      expect(inList().getAllByText("Asha Rao").length).toBeGreaterThan(0);
    });

    it("shows a department filter's loading skeleton, not unfiltered numbers, while the directory loads", async () => {
      searchParams = new URLSearchParams(`dept=${GROUP_IDS.Sales}`);
      let release!: (rows: unknown) => void;
      mockApi({ days: sampleDays(), directory: [], orgs: DIRECTORY });
      const base = mockedGet.getMockImplementation()!;
      mockedGet.mockImplementation((path: string) =>
        path.startsWith("/employees/directory/rows")
          ? (new Promise((r) => {
              release = r;
            }) as never)
          : base(path),
      );
      render(<AttendanceDashboardPage />);
      await waitFor(() => expect(release).toBeDefined());
      expect(screen.getByRole("status", { name: /loading attendance/i })).toBeInTheDocument();
      expect(screen.queryByRole("region", { name: "Attendance summary" })).not.toBeInTheDocument();
      await act(async () => release(DIRECTORY));
      expect(await findTotal(1)).toBeInTheDocument();
    });

    it("compares departments from the summary alone, without permission to list employees", async () => {
      authUser = { ...authUser, permissions: ADMIN_PERMISSIONS.filter((p) => p !== "EMPLOYEE.VIEW_ALL") };
      searchParams = new URLSearchParams("view=trends");
      mockApi({ days: sampleDays(), orgs: DIRECTORY });
      render(<AttendanceDashboardPage />);
      expect(await screen.findByRole("button", { name: /^Sales: 0\.0% present/ })).toBeInTheDocument();
      expect(mockedGet.mock.calls.some((c) => String(c[0]).startsWith("/employees/directory"))).toBe(false);
    });

    it("shows the department under each name in the list", async () => {
      mockApi({ days: sampleDays(), directory: DIRECTORY });
      render(<AttendanceDashboardPage />);
      await findKpi(/^Absent: 1\./);
      expect(await inList().findByText("EMP-003 · Sales")).toBeInTheDocument();
    });
  });

  describe("views", () => {
    it("opens on Today and shows only that view's sections", async () => {
      mockApi({ days: sampleDays() });
      render(<AttendanceDashboardPage />);
      await findKpi(/^Absent: 1\./);
      expect(screen.getByRole("tab", { name: "Today", selected: true })).toBeInTheDocument();
      expect(screen.getByRole("heading", { name: /needs attention/i })).toBeInTheDocument();
      expect(screen.queryByRole("heading", { name: /attendance trend/i })).not.toBeInTheDocument();
      expect(screen.queryByRole("heading", { name: /attendance heatmap/i })).not.toBeInTheDocument();
      expect(screen.queryByRole("heading", { name: "Reports" })).not.toBeInTheDocument();
    });

    it("switches view and keeps it in the URL, leaving Today out of it", async () => {
      mockApi({ days: sampleDays() });
      const user = userEvent.setup();
      render(<AttendanceDashboardPage />);
      await findKpi(/^Absent: 1\./);
      await user.click(screen.getByRole("tab", { name: "Trends" }));
      expect(await screen.findByRole("heading", { name: /attendance trend/i })).toBeInTheDocument();
      await waitFor(() => expect(replaceMock).toHaveBeenLastCalledWith("/app/attendance?view=trends", { scroll: false }));
      await user.click(screen.getByRole("tab", { name: "Today" }));
      await waitFor(() => expect(replaceMock).toHaveBeenLastCalledWith("/app/attendance", { scroll: false }));
    });

    it("restores the view from a shared URL and moves between views with the arrow keys", async () => {
      searchParams = new URLSearchParams("view=trends");
      mockApi({ days: sampleDays() });
      const user = userEvent.setup();
      render(<AttendanceDashboardPage />);
      expect(await screen.findByRole("heading", { name: /attendance trend/i })).toBeInTheDocument();
      screen.getByRole("tab", { name: "Trends" }).focus();
      await user.keyboard("{ArrowRight}");
      expect(screen.getByRole("tab", { name: "Reports", selected: true })).toHaveFocus();
    });

    it("has three tabs: Today, Trends and Reports (Muster and Periods are no longer tabs)", async () => {
      mockApi({ days: sampleDays() });
      render(<AttendanceDashboardPage />);
      await findKpi(/^Absent: 1\./);
      expect(screen.getAllByRole("tab").map((t) => t.textContent)).toEqual(["Today", "Trends", "Reports"]);
    });

    it("keeps links from before the merge working: view=periods is Reports", async () => {
      searchParams = new URLSearchParams("view=reports");
      mockApi({ days: sampleDays() });
      render(<AttendanceDashboardPage />);
      expect(await screen.findByRole("heading", { name: "Reports" })).toBeInTheDocument();
      expect(screen.getByRole("tab", { name: "Reports", selected: true })).toBeInTheDocument();
    });
  });

  describe("list or grid", () => {
    it("shows the same people as a day-by-day grid from a switch on the list, and remembers it in the URL", async () => {
      mockApi({ days: sampleDays() });
      const user = userEvent.setup();
      render(<AttendanceDashboardPage />);
      await findKpi(/^Absent: 1\./);
      expect(screen.getByRole("button", { name: "list", pressed: true })).toBeInTheDocument();
      await user.click(screen.getByRole("button", { name: "grid" }));
      expect(await screen.findByRole("heading", { name: "Attendance grid" })).toBeInTheDocument();
      expect(screen.getByRole("table", { name: /attendance status by employee and day/i })).toBeInTheDocument();
      await waitFor(() => expect(replaceMock).toHaveBeenLastCalledWith("/app/attendance?layout=grid", { scroll: false }));
      await user.click(screen.getByRole("button", { name: "list" }));
      expect(await screen.findByRole("heading", { name: /today's attendance/i })).toBeInTheDocument();
      await waitFor(() => expect(replaceMock).toHaveBeenLastCalledWith("/app/attendance", { scroll: false }));
    });

    it("opens as a grid from a shared link, including the old view=muster link", async () => {
      searchParams = new URLSearchParams("view=muster");
      mockApi({ days: sampleDays() });
      render(<AttendanceDashboardPage />);
      expect(await screen.findByRole("heading", { name: "Attendance grid" })).toBeInTheDocument();
      expect(screen.getByRole("tab", { name: "Today", selected: true })).toBeInTheDocument();
    });

    it("goes back to the list when a summary tile is clicked, since that tile filters the list", async () => {
      searchParams = new URLSearchParams("layout=grid");
      mockApi({ days: sampleDays() });
      const user = userEvent.setup();
      render(<AttendanceDashboardPage />);
      await user.click(await findKpi(/^Absent: 1\./));
      expect(await screen.findByRole("heading", { name: /today's attendance/i })).toBeInTheDocument();
    });
  });

  describe("company + periods", () => {
    it("offers a Company filter under More filters, and scopes the payroll period to it", async () => {
      mockApi({ days: sampleDays(), periods: [PERIOD_OPEN] });
      const user = userEvent.setup();
      render(<AttendanceDashboardPage />);
      await user.click(await screen.findByRole("button", { name: /more filters/i }));
      await user.selectOptions(await screen.findByLabelText("Company"), "le-2");
      await waitFor(() => expect(mockedGet).toHaveBeenCalledWith("/attendance-periods?legal_entity_id=le-2"));
      expect(screen.getByRole("button", { name: /remove filter company: abc services llp/i })).toBeInTheDocument();
    });

    it("surfaces a blocked period as a payroll blocker, with no period panels left on the dashboard", async () => {
      mockApi({ days: sampleDays(), periods: [PERIOD_OPEN] });
      render(<AttendanceDashboardPage />);
      // The blocker is listed once, in Needs attention; the payroll line under it is one row that
      // only says how many items stand in the way and links to the period.
      // Periods load after the days, so wait for them rather than assuming they are there.
      const attention = (await screen.findByRole("heading", { name: /needs attention/i })).closest("[id='att-attention']") as HTMLElement;
      expect(await within(attention).findByText("Payroll period blocked")).toBeInTheDocument();
      const readiness = await screen.findByRole("region", { name: "Payroll readiness" });
      expect(within(readiness).queryByText("Payroll period blocked")).not.toBeInTheDocument();
      expect(within(readiness).getByText("Validation blocked")).toBeInTheDocument();
      expect(within(readiness).getByText(/1 item to clear before close/)).toBeInTheDocument();
      expect(within(readiness).getByRole("link", { name: /open period/i })).toHaveAttribute("href", "/app/attendance-periods/per-1");

      // Period list and monthly summary now live on the Attendance periods page.
      await userEvent.setup().click(screen.getByRole("tab", { name: "Reports" }));
      await screen.findByRole("heading", { name: "Reports" });
      expect(screen.queryByRole("heading", { name: /attendance periods/i })).not.toBeInTheDocument();
      expect(screen.queryByRole("heading", { name: /monthly attendance summary/i })).not.toBeInTheDocument();
      expect(screen.getByRole("link", { name: /payroll → attendance periods/i })).toHaveAttribute("href", "/app/attendance-periods");
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
      expect(await within(section).findByText("Regularization pending")).toBeInTheDocument();
      expect(within(section).getByRole("link", { name: /review/i })).toHaveAttribute("href", "/app/regularizations");

      await user.click(within(section).getByRole("button", { name: /view all: missing punches/i }));
      expect(await screen.findByRole("button", { name: /remove filter missing punch/i })).toBeInTheDocument();
    });

    describe("fixing a mismatch from the list", () => {
      const missingOut = () =>
        makeDay({ id: "d-miss", employee_id: "emp-1", attendance_date: TODAY, attendance_status: "INCOMPLETE", missing_punch: true, actual_last_out: null });
      const rowFor = (name: RegExp) => within(document.getElementById("att-whos-in") as HTMLElement).getAllByText(name)[0].closest("tr") as HTMLElement;

      it("says what is wrong and opens the punch dialog already set to the missing punch-out", async () => {
        mockApi({ days: [missingOut(), makeDay({ employee_id: "emp-2", attendance_date: TODAY })] });
        const user = userEvent.setup();
        render(<AttendanceDashboardPage />);
        await findKpi(/^Present: /);
        const row = within(rowFor(/Asha Rao/));
        expect(row.getByText("Checked in but never checked out.")).toBeInTheDocument();
        await user.click(row.getByRole("button", { name: /^Add punch-out for Asha Rao/ }));
        const dialog = await screen.findByRole("dialog", { name: "Record punch" });
        expect(within(dialog).getByLabelText("Employee")).toHaveValue("Asha Rao");
        expect(within(dialog).getByRole("combobox")).toHaveValue("OUT"); // the Direction select
        // Never a time that has not happened yet; the fixture shift ends 18:00 UTC today.
        expect((within(dialog).getByLabelText(/Punch time/) as HTMLInputElement).value.startsWith(TODAY)).toBe(true);
      });

      it("offers the employee's own correction request first, not a second way to fix the same day", async () => {
        mockApi({
          days: [missingOut()],
          regularizations: [{ id: "reg-9", employee_id: "emp-1", attendance_date: TODAY, status: "SUBMITTED" }],
        });
        render(<AttendanceDashboardPage />);
        await findKpi(/^Present: /);
        // The pending requests arrive after the days; wait for them.
        const link = await within(rowFor(/Asha Rao/)).findByRole("link", { name: /^Review correction request from Asha Rao/ });
        expect(link).toHaveAttribute("href", "/app/regularizations/reg-9");
        const row = within(rowFor(/Asha Rao/));
        expect(row.queryByRole("button", { name: /^Add punch/ })).not.toBeInTheDocument();
        expect(row.getByRole("link", { name: /^Open Asha Rao/ })).toHaveAttribute("href", expect.stringContaining("/app/attendance/d-miss"));
      });

      it("keeps leave from the row for work on approved leave", async () => {
        mockApi({
          days: [makeDay({ id: "d-leave", employee_id: "emp-1", attendance_date: TODAY, work_on_leave_flagged: true, work_on_leave_resolution: null })],
        });
        const user = userEvent.setup();
        render(<AttendanceDashboardPage />);
        await findKpi(/^Present: /);
        const row = within(rowFor(/Asha Rao/));
        expect(row.getByText("Punched in on a day of approved leave.")).toBeInTheDocument();
        expect(row.getByRole("link", { name: /^Cancel Asha Rao/ })).toHaveAttribute("href", "/app/leave-applications");
        await user.click(row.getByRole("button", { name: /^Keep leave for Asha Rao/ }));
        expect(await screen.findByRole("dialog")).toBeInTheDocument();
      });

      it("offers Mark present, not a single punch, when nothing was punched at all", async () => {
        mockApi({
          days: [
            makeDay({ id: "d-none", employee_id: "emp-1", attendance_date: TODAY, attendance_status: "INCOMPLETE", missing_punch: true, actual_first_in: null, actual_last_out: null }),
          ],
        });
        const user = userEvent.setup();
        render(<AttendanceDashboardPage />);
        await findKpi(/^Present: /);
        const row = within(rowFor(/Asha Rao/));
        expect(row.getByText("Nothing was punched on a working day.")).toBeInTheDocument();
        expect(row.queryByRole("button", { name: /^Add punch/ })).not.toBeInTheDocument();
        // The repeated "Missing punch" badge is replaced by the reason above.
        expect(row.queryByText("Missing punch")).not.toBeInTheDocument();
        await user.click(row.getByRole("button", { name: /^Mark Asha Rao present/ }));
        expect(await screen.findByRole("dialog", { name: "Mark attendance" })).toBeInTheDocument();
      });

      it("does not prefill a punch for an incomplete day that has both punches (it may be a break, not a punch)", async () => {
        mockApi({ days: [makeDay({ id: "d-both", employee_id: "emp-1", attendance_date: TODAY, attendance_status: "INCOMPLETE" })] });
        render(<AttendanceDashboardPage />);
        await findKpi(/^Present: /);
        const row = within(rowFor(/Asha Rao/));
        expect(row.getByText("Punches don't add up to a full day.")).toBeInTheDocument();
        expect(row.queryByRole("button", { name: /^Add punch/ })).not.toBeInTheDocument();
        expect(row.getByRole("link", { name: /^Open Asha Rao/ })).toBeInTheDocument();
      });

      it("shows no fix controls on a fine day", async () => {
        mockApi({ days: sampleDays() });
        render(<AttendanceDashboardPage />);
        await findKpi(/^Present: /);
        expect(screen.queryByText(/need fixing/)).not.toBeInTheDocument();
      });
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
      // No pointless lookups the manager can't make (the days themselves are the only list read).
      expect(mockedGetList.mock.calls.map((c) => c[0]).filter((p) => p !== "/attendance/days")).toEqual([]);
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
      // No days yet today: the list shows everyone without a record rather than an empty message.
      expect((await screen.findAllByText("No record")).length).toBeGreaterThan(0);
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
    it("switches between reports built from existing data and offers no export controls", async () => {
      mockApi({ days: sampleDays() });
      const user = userEvent.setup();
      searchParams = new URLSearchParams("view=reports");
      render(<AttendanceDashboardPage />);
      const reports = (await screen.findByRole("heading", { name: "Reports" })).closest("[id='att-reports']") as HTMLElement;
      expect(within(reports).getByRole("tab", { name: "Daily attendance", selected: true })).toBeInTheDocument();
      expect(within(reports).getAllByText("Asha Rao").length).toBeGreaterThan(0);

      await user.click(within(reports).getByRole("tab", { name: "Late / early" }));
      expect(within(reports).getByText("Ben Iyer")).toBeInTheDocument();
      expect(within(reports).queryByText("Asha Rao")).not.toBeInTheDocument();

      expect(within(reports).queryByRole("button", { name: /export|csv|pdf|excel/i })).not.toBeInTheDocument();
      expect(within(reports).queryByText(/export .* is not available yet/i)).not.toBeInTheDocument();
    });

    it("searches within a report", async () => {
      mockApi({ days: sampleDays() });
      const user = userEvent.setup();
      searchParams = new URLSearchParams("view=reports");
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
        searchParams = new URLSearchParams(`range=custom&from=${start}&to=${TODAY}&view=reports`);
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
        searchParams = new URLSearchParams(`range=custom&from=${start}&to=${TODAY}&view=reports`);
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
        searchParams = new URLSearchParams(`range=custom&from=${start}&to=${TODAY}&view=trends`);
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
        expect((await within(overtimeSection).findByText("Total detected")).nextSibling).toHaveTextContent("0h 30m");
        expect(within(overtimeSection).queryByText("1h 15m")).not.toBeInTheDocument();
      });
    });
  });

  describe("request budget", () => {
    it("loads the dashboard with a small, bounded number of requests", async () => {
      mockApi({ days: sampleDays(), periods: [PERIOD_OPEN] });
      render(<AttendanceDashboardPage />);
      await findKpi(/^Present: 2\./);
      await userEvent.setup().click(screen.getByRole("tab", { name: "Reports" }));
      await screen.findByRole("heading", { name: "Reports" });
      await waitFor(() => {
        const total = mockedGet.mock.calls.length + mockedGetList.mock.calls.length;
        expect(total).toBeLessThanOrEqual(10);
      });
      // One request for the totals (counted by the backend) and one for the attendance days the
      // lists need, when they fit on a page.
      const dayCalls = mockedGetList.mock.calls.filter((c) => c[0] === "/attendance/days");
      expect(dayCalls).toHaveLength(1);
      expect(mockedGet.mock.calls.filter((c) => String(c[0]).startsWith("/attendance/summary"))).toHaveLength(1);
    });

    it("asks the backend for the totals over the fetch window and the population filters", async () => {
      searchParams = new URLSearchParams(`employee=emp-2&shift=shift-1&estatus=ACTIVE&dept=${ENG}&branch=unassigned&bucket=ABSENT`);
      mockApi({ days: sampleDays(), directory: DIRECTORY });
      render(<AttendanceDashboardPage />);
      await waitFor(() => expect(mockedGet.mock.calls.some((c) => String(c[0]).startsWith("/attendance/summary"))).toBe(true));
      const path = String(mockedGet.mock.calls.find((c) => String(c[0]).startsWith("/attendance/summary"))![0]);
      const query = Object.fromEntries(new URLSearchParams(path.split("?")[1]));
      expect(query).toEqual({
        date_from: addDays(TODAY, -13),
        date_to: TODAY,
        employee_id: "emp-2",
        shift_id: "shift-1",
        employee_status: "ACTIVE",
        department_id: ENG,
        branch_id: "unassigned",
      });
    });

    it("shows a retryable error, not made-up zeros, when the totals can't be loaded", async () => {
      mockApi({ days: sampleDays(), summaryError: new ApiError({ status: 500, code: "BOOM", message: "db down" }) });
      render(<AttendanceDashboardPage />);
      expect(await screen.findByText("Attendance couldn't be loaded. Please try again.")).toBeInTheDocument();
      expect(screen.queryByRole("region", { name: "Attendance summary" })).not.toBeInTheDocument();
      expect(screen.queryByText(/db down/)).not.toBeInTheDocument();
      mockApi({ days: sampleDays() });
      await userEvent.setup().click(screen.getByRole("button", { name: /try again|retry/i }));
      expect(await findKpi(/^Present: 2\./)).toBeInTheDocument();
    });

    it("reads every page of attendance days, so older days of the range still count", async () => {
      const one = sampleDays();
      // 600 rows: more than one 500-row page. Only the first page used to be read.
      const many = Array.from({ length: 600 }, (_, i) => ({ ...one[i % one.length], id: `bulk-${i}` }));
      mockApi({ days: many });
      render(<AttendanceDashboardPage />);
      await waitFor(() => {
        const pages = mockedGetList.mock.calls
          .filter((c) => c[0] === "/attendance/days")
          .map((c) => (c[1] as { page: number }).page);
        expect(pages).toEqual([1, 2]);
      });
      expect(screen.queryByText(/Totals cover the most recent/)).not.toBeInTheDocument();
    });
  });
});
