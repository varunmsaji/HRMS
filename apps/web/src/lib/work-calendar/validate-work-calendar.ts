import type { WorkCalendar } from "@/lib/work-calendar/types";

export interface WorkCalendarFormValues {
  name: string;
  code: string;
  description: string;
  weeklyOffPatternId: string;
  restrictedHolidaysAreOffByDefault: boolean;
  holidayCalendarIds: string[];
}

export type WorkCalendarFormErrors = Partial<Record<keyof WorkCalendarFormValues, string>>;

export const EMPTY_WORK_CALENDAR_FORM_VALUES: WorkCalendarFormValues = {
  name: "",
  code: "",
  description: "",
  weeklyOffPatternId: "",
  restrictedHolidaysAreOffByDefault: false,
  holidayCalendarIds: [],
};

export function workCalendarToFormValues(calendar: WorkCalendar): WorkCalendarFormValues {
  return {
    name: calendar.name,
    code: calendar.code ?? "",
    description: calendar.description ?? "",
    weeklyOffPatternId: calendar.weekly_off_pattern_id ?? "",
    restrictedHolidaysAreOffByDefault: calendar.restricted_holidays_are_off_by_default,
    holidayCalendarIds: calendar.holiday_calendar_ids,
  };
}

export function buildCreatePayload(values: WorkCalendarFormValues): Record<string, unknown> {
  return {
    name: values.name.trim(),
    code: values.code.trim() || null,
    description: values.description.trim() || null,
    weekly_off_pattern_id: values.weeklyOffPatternId || null,
    restricted_holidays_are_off_by_default: values.restrictedHolidaysAreOffByDefault,
    holiday_calendar_ids: values.holidayCalendarIds,
  };
}

export function buildUpdatePatch(
  values: WorkCalendarFormValues,
  calendar: WorkCalendar,
): Record<string, unknown> {
  const patch: Record<string, unknown> = {};
  if (values.name.trim() !== calendar.name) patch.name = values.name.trim();
  const code = values.code.trim() || null;
  if (code !== calendar.code) patch.code = code;
  const description = values.description.trim() || null;
  if (description !== calendar.description) patch.description = description;
  const weeklyOffPatternId = values.weeklyOffPatternId || null;
  if (weeklyOffPatternId !== calendar.weekly_off_pattern_id) {
    patch.weekly_off_pattern_id = weeklyOffPatternId;
  }
  if (
    values.restrictedHolidaysAreOffByDefault !== calendar.restricted_holidays_are_off_by_default
  ) {
    patch.restricted_holidays_are_off_by_default = values.restrictedHolidaysAreOffByDefault;
  }
  const sameHolidayCalendars =
    values.holidayCalendarIds.length === calendar.holiday_calendar_ids.length &&
    values.holidayCalendarIds.every((id, index) => id === calendar.holiday_calendar_ids[index]);
  if (!sameHolidayCalendars) {
    patch.holiday_calendar_ids = values.holidayCalendarIds;
  }
  return patch;
}

export function validateWorkCalendarForm(values: WorkCalendarFormValues): WorkCalendarFormErrors {
  const errors: WorkCalendarFormErrors = {};
  if (!values.name.trim()) {
    errors.name = "Calendar name is required.";
  }
  return errors;
}
