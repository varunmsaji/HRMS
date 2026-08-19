import type { HolidayCalendar } from "@/lib/holiday-calendar/types";

export interface HolidayCalendarFormValues {
  name: string;
  code: string;
  kind: "NATIONAL" | "REGIONAL" | "COMPANY" | "LOCATION";
  stateCode: string;
  validFrom: string;
  validTo: string;
}

export type HolidayCalendarFormErrors = Partial<Record<keyof HolidayCalendarFormValues, string>>;

export const EMPTY_HOLIDAY_CALENDAR_FORM_VALUES: HolidayCalendarFormValues = {
  name: "",
  code: "",
  kind: "COMPANY",
  stateCode: "",
  validFrom: "",
  validTo: "",
};

export function holidayCalendarToFormValues(calendar: HolidayCalendar): HolidayCalendarFormValues {
  return {
    name: calendar.name,
    code: calendar.code ?? "",
    kind: calendar.kind,
    stateCode: calendar.state_code ?? "",
    validFrom: calendar.valid_from ?? "",
    validTo: calendar.valid_to ?? "",
  };
}

export function buildCreatePayload(values: HolidayCalendarFormValues): Record<string, unknown> {
  return {
    name: values.name.trim(),
    code: values.code.trim() || null,
    kind: values.kind,
    state_code: values.stateCode.trim() || null,
    valid_from: values.validFrom.trim() || null,
    valid_to: values.validTo.trim() || null,
  };
}

export function buildUpdatePatch(
  values: HolidayCalendarFormValues,
  calendar: HolidayCalendar,
): Record<string, unknown> {
  const patch: Record<string, unknown> = {};
  if (values.name.trim() !== calendar.name) patch.name = values.name.trim();
  const code = values.code.trim() || null;
  if (code !== calendar.code) patch.code = code;
  if (values.kind !== calendar.kind) patch.kind = values.kind;
  const stateCode = values.stateCode.trim() || null;
  if (stateCode !== calendar.state_code) patch.state_code = stateCode;
  const validFrom = values.validFrom.trim() || null;
  if (validFrom !== calendar.valid_from) patch.valid_from = validFrom;
  const validTo = values.validTo.trim() || null;
  if (validTo !== calendar.valid_to) patch.valid_to = validTo;
  return patch;
}

export function validateHolidayCalendarForm(
  values: HolidayCalendarFormValues,
): HolidayCalendarFormErrors {
  const errors: HolidayCalendarFormErrors = {};
  if (!values.name.trim()) {
    errors.name = "Calendar name is required.";
  }
  if (values.kind === "REGIONAL" && !values.stateCode.trim()) {
    errors.stateCode = "State code is required for a regional calendar.";
  }
  if (values.validFrom && values.validTo && values.validTo < values.validFrom) {
    errors.validTo = "Valid-to date must be on or after the valid-from date.";
  }
  return errors;
}
