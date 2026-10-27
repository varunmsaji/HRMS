import type { Browser, BrowserContext, Page } from "@playwright/test";
import { expect, test } from "@playwright/test";

import {
  api,
  createEmployeeWorld,
  dataOf,
  login,
  registerTenant,
  rowHashes,
  stackCmd,
  submitLeave,
  watchFailures,
  type Hashes,
} from "./support";

const PROTECTED = [
  "leave_application",
  "leave_application_day",
  "leave_ledger",
  "attendance_day",
  "attendance_period",
  "pay_run",
] as const;

let adminEmail = "";
let adminToken = "";
let companyId = "";
let holidayCalendarId = "";
let workCalendarId = "";
let patternId = "";
let employeeId = "";
let employeeEmail = "";
let legalEntityId = "";
let adminState: Awaited<ReturnType<BrowserContext["storageState"]>> | undefined;
let effectiveFrom = "";

function expectSame(before: Hashes, after: Hashes, tables: readonly string[]): void {
  for (const table of tables) {
    expect(after[table], table).toEqual(before[table]);
  }
}

async function openAdmin(
  browser: Browser,
  timezoneId = "America/Los_Angeles",
): Promise<{ context: BrowserContext; page: Page; problems: string[] }> {
  if (!adminState) throw new Error("admin session was not captured");
  const context = await browser.newContext({ storageState: adminState, timezoneId });
  const page = await context.newPage();
  const problems = watchFailures(page);
  return { context, page, problems };
}

test.describe.configure({ mode: "serial" });

test.describe("work calendar", () => {
  test("guided setup shows an unconfirmed suggestion and activates only on confirm", async ({
    page,
  }) => {
    const problems = watchFailures(page);
    const tenant = await registerTenant("setup");
    adminEmail = tenant.email;
    adminToken = tenant.token;
    companyId = tenant.companyId;

    const holiday = await api("/v1/holiday-calendars", {
      token: adminToken,
      companyId,
      body: { name: "Browser Holidays" },
    });
    expect(holiday.status).toBe(201);
    holidayCalendarId = dataOf<{ id: string }>(holiday.body).id;

    const before = rowHashes(companyId);
    expect(before.holiday?.count ?? 0).toBe(0);

    await login(page, adminEmail);
    await page.goto("/app/work-calendars/setup");
    await expect(page.getByText("Unconfirmed suggestion")).toBeVisible();
    await expect(page.getByText("Nothing below is saved until you confirm.")).toBeVisible();
    await expect(page.getByText("Public holidays have not been added automatically.")).toBeVisible();
    await expect(page.getByRole("checkbox", { name: "Saturday" })).toBeChecked();
    await expect(page.getByRole("checkbox", { name: "Sunday" })).toBeChecked();
    await expect(page.getByRole("checkbox", { name: "Monday" })).not.toBeChecked();
    await expect(page.getByRole("checkbox", { name: "Browser Holidays" })).not.toBeChecked();

    const calendars = await api("/v1/work-calendars", { method: "GET", token: adminToken, companyId });
    expect(calendars.status).toBe(200);
    expect(dataOf<unknown[]>(calendars.body)).toEqual([]);

    effectiveFrom = await page.locator("#setup-effective-from").inputValue();
    await page.getByRole("checkbox", { name: "Browser Holidays" }).check();
    await page.getByRole("button", { name: "Preview calendar" }).click();
    await expect(page.getByText("Not saved")).toBeVisible();
    await expect(page.getByRole("grid", { name: "Calendar days" })).toBeVisible();
    const previewCells = page.getByRole("gridcell");
    await expect(previewCells.filter({ hasText: "Weekly off" }).first()).toBeVisible();
    await expect(previewCells.filter({ hasText: "Working" }).first()).toBeVisible();

    await page.getByRole("button", { name: "Review and activate" }).click();
    const dialog = page.getByRole("dialog", { name: "Activate this work calendar?" });
    await expect(dialog).toBeVisible();
    await dialog.getByRole("button", { name: "Cancel" }).click();
    await expect(page.getByText("Unconfirmed suggestion")).toBeVisible();
    expect(dataOf<unknown[]>((await api("/v1/work-calendars", { method: "GET", token: adminToken, companyId })).body)).toEqual(
      [],
    );
    expectSame(before, rowHashes(companyId), ["holiday", "calendar_exception"]);

    await page.getByRole("button", { name: "Review and activate" }).click();
    await dialog.getByRole("checkbox").check();
    await dialog.getByRole("button", { name: "Activate calendar" }).click();
    await expect(page.getByText("The work calendar has been activated.")).toBeVisible();
    await page.reload();
    await expect(page.getByText("A company-wide work calendar is already active.")).toBeVisible();
    await expect(page.getByRole("button", { name: "Activate calendar" })).toHaveCount(0);

    const listed = await api("/v1/work-calendars", { method: "GET", token: adminToken, companyId });
    const rows = dataOf<Array<{ id: string; weekly_off_pattern_id: string }>>(listed.body);
    expect(rows).toHaveLength(1);
    workCalendarId = rows[0].id;
    patternId = rows[0].weekly_off_pattern_id;

    const again = await api("/v1/work-calendar-setup/confirm", {
      token: adminToken,
      companyId,
      body: {
        name: "Default work calendar",
        weekly_off_weekdays: [5, 6],
        holiday_calendar_ids: [holidayCalendarId],
        effective_from: effectiveFrom,
        confirm: true,
      },
    });
    expect(again.status).toBe(409);
    expect(JSON.stringify(again.body)).toContain("WORK_CALENDAR_ALREADY_CONFIGURED");
    expect(
      dataOf<unknown[]>((await api("/v1/work-calendars", { method: "GET", token: adminToken, companyId })).body),
    ).toHaveLength(1);

    adminState = await page.context().storageState();
    expect(problems, problems.join("\n")).toEqual([]);
  });

  test("month navigation keeps date-only labels and classifies the working week", async ({ browser }) => {
    const { context, page, problems } = await openAdmin(browser, "Pacific/Kiritimati");
    await page.goto(`/app/work-calendars/${workCalendarId}`);
    await page.getByRole("tab", { name: "Calendar" }).click();
    await expect(page.getByRole("gridcell", { name: /^2026-10-04: Weekly off/ })).toBeVisible();
    await expect(page.getByRole("gridcell", { name: /^2026-10-05: Working/ })).toBeVisible();
    await page.getByRole("button", { name: "Next month" }).click();
    await expect(page.getByRole("heading", { name: "November 2026" })).toBeVisible();
    await expect(page.getByRole("gridcell", { name: /^2026-11-01: Weekly off/ })).toBeVisible();
    await page.getByRole("button", { name: "Previous month" }).click();
    await expect(page.getByRole("heading", { name: "October 2026" })).toBeVisible();
    await expect(page.getByRole("gridcell", { name: /^2026-10-04: Weekly off/ })).toBeVisible();
    expect(problems, problems.join("\n")).toEqual([]);
    await context.close();
  });

  test("an employee with no applicable calendar is told it is not set up", async ({ browser }) => {
    const world = await createEmployeeWorld(adminToken, companyId);
    employeeId = world.employeeId;
    legalEntityId = world.legalEntityId;
    employeeEmail = `asha-${Date.now()}@example.com`;
    // The company assignment starts today, so earlier October dates stay unconfigured.
    // Re-point it only after this assertion, in the assignment test below.
    stackCmd("link-employee", companyId, employeeId, employeeEmail);

    const context = await browser.newContext({ timezoneId: "Pacific/Kiritimati" });
    const page = await context.newPage();
    const problems = watchFailures(page);
    await login(page, employeeEmail);
    await page.goto("/app/me/calendar");
    await expect(
      page.getByText("Dates marked “Not set up” have no calendar yet.").or(
        page.getByText("Your work calendar is not set up yet"),
      ),
    ).toBeVisible();
    const early = page.locator('[data-date="2026-10-01"]');
    if ((await early.count()) > 0) {
      await expect(early).toHaveAttribute("data-day-kind", "UNCONFIGURED");
      await expect(early).toHaveAttribute("data-date", "2026-10-01");
    }
    await page.goto(`/app/work-calendars/${workCalendarId}`);
    await expect(page.getByText("You do not have permission to view this calendar.")).toBeVisible();
    await expect(page.getByRole("button", { name: "Deactivate" })).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Add Holiday" })).toHaveCount(0);
    expect(problems, problems.join("\n")).toEqual([]);
    await context.close();
  });

  test("holiday preview shows current and proposed days, cancel leaves rows unchanged, confirm matches", async ({
    browser,
  }) => {
    await submitLeave(adminToken, companyId, employeeId, await leaveTypeId(), "2026-10-28");
    await submitLeave(adminToken, companyId, employeeId, await leaveTypeId(), "2026-10-30");
    const pending = stackCmd("mark-pending", companyId, "2026-10-30");
    expect(pending).toContain("pending_rows=1");

    const before = rowHashes(companyId);
    const { context, page, problems } = await openAdmin(browser);
    await page.goto(`/app/holiday-calendars/${holidayCalendarId}`);
    await page.getByRole("button", { name: "Add Holiday" }).click();
    const add = page.getByRole("dialog", { name: "Add Holiday" });
    await expect(add.getByText("always follows the type")).toBeVisible();
    await add.locator("#holiday-date").fill("2026-10-28");
    await add.locator("#holiday-name").fill("Founders Day");
    await add.getByRole("button", { name: "Add holiday" }).click();

    const impact = page.getByRole("dialog", { name: /review impact/ });
    await expect(impact.getByRole("columnheader", { name: "Currently" })).toBeVisible();
    await expect(impact.getByRole("columnheader", { name: "After this change" })).toBeVisible();
    await expect(impact.getByText("private medical detail")).toHaveCount(0);
    await impact.getByRole("button", { name: "Back" }).click();
    await add.getByRole("button", { name: "Cancel" }).click();
    expectSame(before, rowHashes(companyId), ["holiday", "leave_application", "leave_application_day"]);

    await page.getByRole("button", { name: "Add Holiday" }).click();
    await add.locator("#holiday-date").fill("2026-10-28");
    await add.locator("#holiday-name").fill("Founders Day");
    await add.getByRole("button", { name: "Add holiday" }).click();
    await expect(impact.getByText("Approved leave, day becomes HOLIDAY")).toBeVisible();
    await expect(impact.getByText("private medical detail")).toHaveCount(0);
    await impact.getByRole("checkbox").check();
    await expect(impact.getByRole("button", { name: "Confirm change" })).toBeEnabled();
    const during = rowHashes(companyId);
    stackCmd("insert-protected", companyId, legalEntityId, "2026-10-01", "2026-10-31");
    await impact.getByRole("button", { name: "Confirm change" }).click();
    await expect(impact.getByText("This preview is out of date.")).toBeVisible();
    expectSame(during, rowHashes(companyId), ["holiday"]);
    const withPeriod = rowHashes(companyId);
    expect(withPeriod.attendance_period.count).toBe(during.attendance_period.count + 1);
    expect(withPeriod.pay_run.count).toBe(during.pay_run.count + 1);

    await impact.getByRole("button", { name: "Refresh preview" }).click();
    await expect(impact.getByTestId("protected-periods")).toBeVisible();
    await expect(impact.getByRole("button", { name: "Confirm change" })).toBeDisabled();
    await impact.getByRole("checkbox").check();
    await expect(impact.getByRole("button", { name: "Confirm change" })).toBeEnabled();
    const confirmedFrom = rowHashes(companyId);
    await impact.getByRole("button", { name: "Confirm change" }).click();
    await expect(page.getByText("Founders Day")).toBeVisible();
    const after = rowHashes(companyId);
    expect(after.holiday.count).toBe(confirmedFrom.holiday.count + 1);
    expectSame(confirmedFrom, after, PROTECTED);

    await page.goto(`/app/work-calendars/${workCalendarId}`);
    await page.getByRole("tab", { name: "Calendar" }).click();
    await expect(page.getByRole("gridcell", { name: /^2026-10-28: Holiday/ })).toBeVisible();

    const conflict = await api(`/v1/holiday-calendars/${holidayCalendarId}/holidays`, {
      token: adminToken,
      companyId,
      body: {
        date: "2026-11-04",
        name: "Contradictory",
        holiday_type: "PUBLIC",
        is_working: true,
      },
    });
    expect(conflict.status).toBe(422);
    expect(JSON.stringify(conflict.body)).toContain("HOLIDAY_IS_WORKING_CONFLICT");
    expectSame(after, rowHashes(companyId), ["holiday"]);

    expect(problems, problems.join("\n")).toEqual([]);
    await context.close();
  });

  test("a holiday on a weekly off does not create a substitute, and an explicit exception does", async ({
    browser,
  }) => {
    const before = rowHashes(companyId);
    const { context, page, problems } = await openAdmin(browser);
    await page.goto(`/app/holiday-calendars/${holidayCalendarId}`);
    await page.getByRole("button", { name: "Add Holiday" }).click();
    const add = page.getByRole("dialog", { name: "Add Holiday" });
    await add.locator("#holiday-date").fill("2026-11-01");
    await add.locator("#holiday-name").fill("Sunday Festival");
    await add.getByRole("button", { name: "Add holiday" }).click();
    const impact = page.getByRole("dialog", { name: /review impact/ });
    await expect(impact.getByRole("cell", { name: "Weekly off — Sunday Festival" })).toBeVisible();
    await acknowledgeAndConfirm(impact);
    await page.goto(`/app/work-calendars/${workCalendarId}`);
    await page.getByRole("tab", { name: "Calendar" }).click();
    await page.getByRole("button", { name: "Next month" }).click();
    await expect(page.getByRole("gridcell", { name: /2026-11-01: Weekly off.*on weekly off/ })).toBeVisible();
    await page.getByRole("tab", { name: "Exceptions" }).click();
    await expect(page.getByText("SUBSTITUTE HOLIDAY")).toHaveCount(0);

    await page.getByRole("button", { name: "Add exception" }).click();
    const exception = page.getByRole("dialog", { name: "Add Calendar Exception" });
    await exception.locator("#exception-date").fill("2026-11-02");
    await exception.locator("#exception-type").selectOption("SUBSTITUTE_HOLIDAY");
    await exception.locator("#exception-name").fill("In lieu of Sunday");
    await exception.getByRole("button", { name: "Add exception" }).click();
    const exceptionImpact = page.getByRole("dialog", { name: /review impact/ });
    await expect(exceptionImpact.getByText(/Holiday/)).toBeVisible();
    await acknowledgeAndConfirm(exceptionImpact);
    await page.getByRole("tab", { name: "Calendar" }).click();
    await expect(page.getByRole("gridcell", { name: /^2026-11-02: Holiday/ })).toBeVisible();
    const after = rowHashes(companyId);
    expect(after.calendar_exception.count).toBe(before.calendar_exception.count + 1);
    expectSame(before, after, PROTECTED);
    expect(problems, problems.join("\n")).toEqual([]);
    await context.close();
  });

  test("weekly-off half day is previewed and then shown on the calendar", async ({
    browser,
  }) => {
    const { context, page, problems } = await openAdmin(browser);
    await page.goto(`/app/weekly-off-patterns/${patternId}`);
    await expect(page.getByText("full day").first()).toBeVisible();
    await page.getByRole("button", { name: "Edit" }).click();
    const saturday = await page.locator("select[id$='-weekday']").evaluateAll((nodes) => {
      const selects = nodes as HTMLSelectElement[];
      return selects.findIndex((node) => node.value === "5");
    });
    expect(saturday).toBeGreaterThanOrEqual(0);
    await page.locator(`#rule-${saturday}-fraction`).selectOption("0.50");
    await page.getByRole("button", { name: "Save changes" }).click();
    const impact = page.getByRole("dialog", { name: /review impact/ });
    await expect(impact.getByText("Weekly off (half day)").first()).toBeVisible();
    const before = rowHashes(companyId);
    await acknowledgeAndConfirm(impact);
    await expect(page.getByText("half day off")).toBeVisible();
    await page.goto(`/app/work-calendars/${workCalendarId}`);
    await page.getByRole("tab", { name: "Calendar" }).click();
    await expect(page.getByRole("gridcell", { name: /^2026-10-31: Half-day weekly off/ })).toBeVisible();
    expectSame(before, rowHashes(companyId), PROTECTED);
    expect(problems, problems.join("\n")).toEqual([]);
    await context.close();
  });

  test("deactivation is blocked while an assignment applies, and an inactive calendar cannot be assigned", async ({
    browser,
  }) => {
    const { context, page, problems } = await openAdmin(browser);
    await page.goto(`/app/work-calendars/${workCalendarId}`);
    await page.getByRole("button", { name: "Deactivate" }).click();
    await page.getByRole("dialog").getByRole("button", { name: "Deactivate" }).click();
    await expect(page.getByText("Cannot deactivate")).toBeVisible();
    await expect(page.getByText(/active or future assignment/)).toBeVisible();
    const still = await api(`/v1/work-calendars/${workCalendarId}`, {
      method: "GET",
      token: adminToken,
      companyId,
    });
    expect(dataOf<{ is_active: boolean }>(still.body).is_active).toBe(true);

    const spare = await api("/v1/work-calendars", {
      token: adminToken,
      companyId,
      body: { name: "Spare calendar", weekly_off_pattern_id: patternId },
    });
    expect(spare.status).toBe(201);
    const spareId = dataOf<{ id: string; version: number }>(spare.body).id;
    const version = dataOf<{ version: number }>(spare.body).version;
    const removed = await api(`/v1/work-calendars/${spareId}`, {
      method: "DELETE",
      token: adminToken,
      companyId,
      ifMatch: String(version),
    });
    expect(removed.status).toBe(200);
    const assigned = await api("/v1/policy-assignments", {
      token: adminToken,
      companyId,
      body: {
        policy_kind: "WORK_CALENDAR",
        policy_id: spareId,
        scope_type: "EMPLOYEE",
        scope_id: employeeId,
        effective_from: "2027-01-01",
      },
    });
    expect(assigned.status).toBe(422);
    expect(JSON.stringify(assigned.body)).toContain("INVALID_POLICY_REFERENCE");
    expect(problems, problems.join("\n")).toEqual([]);
    await context.close();
  });

  test("holiday-calendar validity is applied, and the employee sees only their own calendar", async ({
    browser,
  }) => {
    const { context, page, problems } = await openAdmin(browser);
    await page.goto(`/app/holiday-calendars/${holidayCalendarId}`);
    await page.getByRole("button", { name: "Edit" }).first().click();
    await page.getByLabel("Valid to").fill("2026-10-27");
    await page.getByRole("button", { name: "Save changes" }).click();
    const impact = page.getByRole("dialog", { name: /review impact/ });
    await acknowledgeAndConfirm(impact);
    await page.goto(`/app/work-calendars/${workCalendarId}`);
    await page.getByRole("tab", { name: "Calendar" }).click();
    await expect(page.getByRole("gridcell", { name: /^2026-10-28: Working/ })).toBeVisible();
    expect(problems, problems.join("\n")).toEqual([]);
    await context.close();

    const employeeContext = await browser.newContext({ timezoneId: "America/Los_Angeles" });
    const employeePage = await employeeContext.newPage();
    const employeeProblems = watchFailures(employeePage);
    await login(employeePage, employeeEmail);
    await employeePage.goto("/app/me/calendar");
    await expect(employeePage.getByText(/part of this month|Not set up/)).toBeVisible();
    const holiday = employeePage.locator('[data-date="2026-10-28"]');
    await expect(holiday).toHaveAttribute("data-date", "2026-10-28");
    await expect(employeePage.locator('[data-date="2026-10-30"]')).toContainText("Pending leave");
    await expect(employeePage.getByText("private medical detail")).toHaveCount(0);
    await employeePage.goto(`/app/work-calendars/${workCalendarId}`);
    await expect(employeePage.getByText(/do not have permission/)).toBeVisible();
    expect(employeeProblems, employeeProblems.join("\n")).toEqual([]);
    await employeeContext.close();

    const other = await registerTenant("other");
    const otherContext = await browser.newContext();
    const otherPage = await otherContext.newPage();
    await login(otherPage, other.email);
    const cross = await otherPage.request.get(`${process.env.E2E_API_URL}/v1/work-calendars/${workCalendarId}`, {
      headers: {
        Authorization: `Bearer ${other.token}`,
        "X-Company-Id": other.companyId,
      },
    });
    expect(cross.status()).toBe(404);
    await otherPage.goto(`/app/work-calendars/${workCalendarId}`);
    await expect(otherPage.getByText("This work calendar could not be found.")).toBeVisible();
    await otherContext.close();
  });
});

async function leaveTypeId(): Promise<string> {
  const listed = await api("/v1/leave-types", { method: "GET", token: adminToken, companyId });
  const rows = dataOf<Array<{ id: string; code: string }>>(listed.body);
  const match = rows.find((row) => row.code === "EL");
  if (!match) throw new Error("leave type EL was not created");
  return match.id;
}

async function acknowledgeAndConfirm(dialog: ReturnType<Page["getByRole"]>): Promise<void> {
  await expect(dialog).toBeVisible();
  const checkbox = dialog.getByRole("checkbox");
  if ((await checkbox.count()) > 0) await checkbox.check();
  await dialog.getByRole("button", { name: "Confirm change" }).click();
  await expect(dialog).toBeHidden();
}
