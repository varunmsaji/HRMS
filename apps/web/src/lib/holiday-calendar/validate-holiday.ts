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
