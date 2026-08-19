import { describe, expect, it } from "vitest";

import type { WorkCalendar } from "@/lib/work-calendar/types";
import {
  EMPTY_WORK_CALENDAR_FORM_VALUES,
  buildCreatePayload,
  buildUpdatePatch,
  validateWorkCalendarForm,
  workCalendarToFormValues,
} from "@/lib/work-calendar/validate-work-calendar";

const calendar: WorkCalendar = {
  id: "wc-1",
  company_id: "company-1",
  name: "India General",
  code: null,
  description: null,
  weekly_off_pattern_id: "pattern-1",
  restricted_holidays_are_off_by_default: false,
  is_active: true,
  version: 1,
  created_at: "2026-08-01T00:00:00Z",
  updated_at: "2026-08-01T00:00:00Z",
  holiday_calendar_ids: ["cal-1", "cal-2"],
};

describe("validateWorkCalendarForm", () => {
  it("requires a name", () => {
    expect(validateWorkCalendarForm(EMPTY_WORK_CALENDAR_FORM_VALUES).name).toBeDefined();
  });
});

describe("buildCreatePayload", () => {
  it("includes the ordered holiday_calendar_ids list", () => {
    const payload = buildCreatePayload({
      ...EMPTY_WORK_CALENDAR_FORM_VALUES,
      name: "India General",
      holidayCalendarIds: ["cal-1", "cal-2"],
    });
    expect(payload.holiday_calendar_ids).toEqual(["cal-1", "cal-2"]);
  });
});

describe("workCalendarToFormValues / buildUpdatePatch", () => {
  it("round-trips unchanged values to an empty patch", () => {
    const values = workCalendarToFormValues(calendar);
    expect(buildUpdatePatch(values, calendar)).toEqual({});
  });

  it("detects a reordered holiday_calendar_ids list as a change", () => {
    const values = workCalendarToFormValues(calendar);
    values.holidayCalendarIds = ["cal-2", "cal-1"];
    expect(buildUpdatePatch(values, calendar)).toEqual({
      holiday_calendar_ids: ["cal-2", "cal-1"],
    });
  });

  it("detects a name change", () => {
    const values = workCalendarToFormValues(calendar);
    values.name = "India General Holidays";
    expect(buildUpdatePatch(values, calendar)).toEqual({ name: "India General Holidays" });
  });
});
