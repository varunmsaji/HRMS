import { describe, expect, it } from "vitest";

import type { Holiday } from "@/lib/holiday-calendar/types";
import {
  buildHolidayCreatePayload,
  buildHolidayUpdatePayload,
  holidayToFormValues,
  validateHolidayForm,
  EMPTY_HOLIDAY_FORM_VALUES,
} from "@/lib/holiday-calendar/validate-holiday";

const holiday: Holiday = {
  id: "holiday-1",
  company_id: "company-1",
  calendar_id: "cal-1",
  date: "2026-08-15",
  name: "Independence Day",
  is_optional: false,
  holiday_type: "PUBLIC",
  is_paid: true,
  is_working: false,
  region_note: null,
  replaced_holiday_id: null,
  is_active: true,
  version: 1,
  created_at: "2026-08-01T00:00:00Z",
  updated_at: "2026-08-01T00:00:00Z",
};

describe("validateHolidayForm", () => {
  it("requires a date and a name", () => {
    const errors = validateHolidayForm(EMPTY_HOLIDAY_FORM_VALUES);
    expect(errors.date).toBeDefined();
    expect(errors.name).toBeDefined();
  });

  it("rejects a malformed date", () => {
    const errors = validateHolidayForm({
      ...EMPTY_HOLIDAY_FORM_VALUES,
      date: "15-08-2026",
      name: "Independence Day",
    });
    expect(errors.date).toBeDefined();
  });

  it("accepts a well-formed holiday", () => {
    const errors = validateHolidayForm({
      ...EMPTY_HOLIDAY_FORM_VALUES,
      date: "2026-08-15",
      name: "Independence Day",
    });
    expect(errors).toEqual({});
  });
});

describe("buildHolidayCreatePayload", () => {
  it("nulls out a blank region note", () => {
    const payload = buildHolidayCreatePayload({
      ...EMPTY_HOLIDAY_FORM_VALUES,
      date: "2026-08-15",
      name: "Independence Day",
    });
    expect(payload).toMatchObject({ region_note: null });
  });
});

describe("holidayToFormValues / buildHolidayUpdatePayload", () => {
  it("round-trips unchanged values to an empty patch", () => {
    const values = holidayToFormValues(holiday);
    expect(buildHolidayUpdatePayload(values, holiday)).toEqual({});
  });

  it("only includes changed fields in the patch", () => {
    const values = holidayToFormValues(holiday);
    values.name = "15th August";
    values.isWorking = true;
    expect(buildHolidayUpdatePayload(values, holiday)).toEqual({
      name: "15th August",
      is_working: true,
    });
  });

  it("never includes date, even though the caller edited it in the shared form-values shape", () => {
    const values = holidayToFormValues(holiday);
    values.date = "2026-08-16";
    expect(buildHolidayUpdatePayload(values, holiday)).toEqual({});
  });
});
