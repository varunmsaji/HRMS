export interface CalendarExceptionFormValues {
  exceptionDate: string;
  exceptionType: "SPECIAL_WORKING" | "SHUTDOWN" | "SUBSTITUTE_HOLIDAY" | "CANCEL_HOLIDAY";
  name: string;
  reason: string;
  isPaid: "" | "true" | "false";
}

export type CalendarExceptionFormErrors = Partial<
  Record<keyof CalendarExceptionFormValues, string>
>;

const DATE_PATTERN = /^\d{4}-\d{2}-\d{2}$/;

export const EMPTY_CALENDAR_EXCEPTION_FORM_VALUES: CalendarExceptionFormValues = {
  exceptionDate: "",
  exceptionType: "SPECIAL_WORKING",
  name: "",
  reason: "",
  isPaid: "",
};

export function buildCalendarExceptionCreatePayload(
  values: CalendarExceptionFormValues,
): Record<string, unknown> {
  return {
    exception_date: values.exceptionDate.trim(),
    exception_type: values.exceptionType,
    name: values.name.trim() || null,
    reason: values.reason.trim() || null,
    is_paid: values.isPaid === "" ? null : values.isPaid === "true",
  };
}

export function validateCalendarExceptionForm(
  values: CalendarExceptionFormValues,
): CalendarExceptionFormErrors {
  const errors: CalendarExceptionFormErrors = {};
  if (!values.exceptionDate.trim()) {
    errors.exceptionDate = "Date is required.";
  } else if (!DATE_PATTERN.test(values.exceptionDate.trim())) {
    errors.exceptionDate = "Use YYYY-MM-DD format.";
  }
  return errors;
}
