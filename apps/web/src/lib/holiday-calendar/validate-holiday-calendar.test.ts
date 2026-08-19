import { describe, expect, it } from "vitest";

import type { HolidayCalendar } from "@/lib/holiday-calendar/types";
import {
  EMPTY_HOLIDAY_CALENDAR_FORM_VALUES,
  buildCreatePayload,
  buildUpdatePatch,
  holidayCalendarToFormValues,
  validateHolidayCalendarForm,
} from "@/lib/holiday-calendar/validate-holiday-calendar";

const calendar: HolidayCalendar = {
  id: "cal-1",
  company_id: "company-1",
  name: "India National",
  code: "NAT",
  kind: "NATIONAL",
  state_code: null,
  valid_from: null,
  valid_to: null,
  is_active: true,
  version: 1,
  created_at: "2026-08-01T00:00:00Z",
  updated_at: "2026-08-01T00:00:00Z",
};

describe("validateHolidayCalendarForm", () => {
  it("requires a name", () => {
    const errors = validateHolidayCalendarForm(EMPTY_HOLIDAY_CALENDAR_FORM_VALUES);
    expect(errors.name).toBeDefined();
  });

  it("requires a state code for regional calendars", () => {
    const errors = validateHolidayCalendarForm({
      ...EMPTY_HOLIDAY_CALENDAR_FORM_VALUES,
      name: "Kerala Office",
      kind: "REGIONAL",
    });
    expect(errors.stateCode).toBeDefined();
  });

  it("rejects valid_to before valid_from", () => {
    const errors = validateHolidayCalendarForm({
      ...EMPTY_HOLIDAY_CALENDAR_FORM_VALUES,
      name: "FY26",
      validFrom: "2026-04-01",
      validTo: "2026-01-01",
    });
    expect(errors.validTo).toBeDefined();
  });

  it("accepts a well-formed national calendar", () => {
    const errors = validateHolidayCalendarForm({
      ...EMPTY_HOLIDAY_CALENDAR_FORM_VALUES,
      name: "India National",
    });
    expect(errors).toEqual({});
  });
});

describe("buildCreatePayload", () => {
  it("nulls out blank optional fields", () => {
    const payload = buildCreatePayload(EMPTY_HOLIDAY_CALENDAR_FORM_VALUES);
    expect(payload).toMatchObject({ code: null, state_code: null, valid_from: null, valid_to: null });
  });
});

describe("holidayCalendarToFormValues / buildUpdatePatch", () => {
  it("round-trips unchanged values to an empty patch", () => {
    const values = holidayCalendarToFormValues(calendar);
    expect(buildUpdatePatch(values, calendar)).toEqual({});
  });

  it("only includes changed fields in the patch", () => {
    const values = holidayCalendarToFormValues(calendar);
    values.name = "India National Holidays";
    expect(buildUpdatePatch(values, calendar)).toEqual({ name: "India National Holidays" });
  });
});
