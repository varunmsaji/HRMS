import type { Holiday } from "@/lib/holiday-calendar/types";

export interface HolidayFormValues {
  date: string;
  name: string;
  holidayType: "PUBLIC" | "COMPANY" | "OPTIONAL" | "RESTRICTED" | "WORKING_HOLIDAY";
  isPaid: boolean;
  isWorking: boolean;
  regionNote: string;
}

export type HolidayFormErrors = Partial<Record<keyof HolidayFormValues, string>>;

export const EMPTY_HOLIDAY_FORM_VALUES: HolidayFormValues = {
  date: "",
  name: "",
  holidayType: "PUBLIC",
  isPaid: true,
  isWorking: false,
  regionNote: "",
};

const DATE_PATTERN = /^\d{4}-\d{2}-\d{2}$/;

export function buildHolidayCreatePayload(values: HolidayFormValues): Record<string, unknown> {
  return {
    date: values.date.trim(),
    name: values.name.trim(),
    holiday_type: values.holidayType,
    is_paid: values.isPaid,
    is_working: values.isWorking,
    region_note: values.regionNote.trim() || null,
  };
}

export function validateHolidayForm(values: HolidayFormValues): HolidayFormErrors {
  const errors: HolidayFormErrors = {};
  if (!values.date.trim()) {
    errors.date = "Date is required.";
  } else if (!DATE_PATTERN.test(values.date.trim())) {
    errors.date = "Use YYYY-MM-DD format.";
  }
  if (!values.name.trim()) {
    errors.name = "Holiday name is required.";
  }
  return errors;
}

export function holidayToFormValues(holiday: Holiday): HolidayFormValues {
  return {
    date: holiday.date,
    name: holiday.name,
    holidayType: holiday.holiday_type,
    isPaid: holiday.is_paid,
    isWorking: holiday.is_working,
    regionNote: holiday.region_note ?? "",
  };
}

/** `date` and `calendar_id` are immutable after creation (architecture §25 — "no PATCH of used
 * dates"; correcting a wrong date is deactivate + create a new row) and `HolidayUpdate` forbids
 * extra fields, so `date` is never included here even though it's part of the shared form-values
 * shape used for both add and edit. */
export function buildHolidayUpdatePayload(
  values: HolidayFormValues,
  holiday: Holiday,
): Record<string, unknown> {
  const patch: Record<string, unknown> = {};
  if (values.name.trim() !== holiday.name) patch.name = values.name.trim();
  if (values.holidayType !== holiday.holiday_type) patch.holiday_type = values.holidayType;
  if (values.isPaid !== holiday.is_paid) patch.is_paid = values.isPaid;
  if (values.isWorking !== holiday.is_working) patch.is_working = values.isWorking;
  const regionNote = values.regionNote.trim() || null;
  if (regionNote !== holiday.region_note) patch.region_note = regionNote;
  return patch;
}
