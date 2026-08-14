import type { Shift } from "@/lib/shift/types";

export interface ShiftFormValues {
  name: string;
  code: string;
  startTime: string;
  endTime: string;
  breakMinutesPaid: string;
  breakMinutesUnpaid: string;
  graceInMinutes: string;
  graceOutMinutes: string;
  halfDayThresholdHours: string;
  minHoursFullDay: string;
  isNightShift: boolean;
  isCrossMidnight: boolean;
  isOtEligible: boolean;
}

export type ShiftFormErrors = Partial<Record<keyof ShiftFormValues, string>>;

export const EMPTY_SHIFT_FORM_VALUES: ShiftFormValues = {
  name: "",
  code: "",
  startTime: "",
  endTime: "",
  breakMinutesPaid: "0",
  breakMinutesUnpaid: "0",
  graceInMinutes: "0",
  graceOutMinutes: "0",
  halfDayThresholdHours: "",
  minHoursFullDay: "",
  isNightShift: false,
  isCrossMidnight: false,
  isOtEligible: false,
};

const TIME_PATTERN = /^\d{2}:\d{2}$/;

function intOrZero(value: string): number {
  const trimmed = value.trim();
  if (!trimmed) return 0;
  const parsed = Number(trimmed);
  if (Number.isNaN(parsed)) return 0;
  return Math.trunc(parsed);
}

function decimalOrNull(value: string): number | null {
  const trimmed = value.trim();
  if (!trimmed) return null;
  const parsed = Number(trimmed);
  if (Number.isNaN(parsed)) return null;
  return parsed;
}

function decimalToString(value: number | null): string {
  if (value === null) return "";
  return String(value);
}

export function shiftToFormValues(shift: Shift): ShiftFormValues {
  return {
    name: shift.name,
    code: shift.code ?? "",
    startTime: shift.start_time,
    endTime: shift.end_time,
    breakMinutesPaid: String(shift.break_minutes_paid),
    breakMinutesUnpaid: String(shift.break_minutes_unpaid),
    graceInMinutes: String(shift.grace_in_minutes),
    graceOutMinutes: String(shift.grace_out_minutes),
    halfDayThresholdHours: decimalToString(shift.half_day_threshold_hours),
    minHoursFullDay: decimalToString(shift.min_hours_full_day),
    isNightShift: shift.is_night_shift,
    isCrossMidnight: shift.is_cross_midnight,
    isOtEligible: shift.is_ot_eligible,
  };
}

/** Full payload for `POST /shifts` — every field the form collects. */
export function buildCreatePayload(values: ShiftFormValues): Record<string, unknown> {
  return {
    name: values.name.trim(),
    code: values.code.trim() || null,
    start_time: values.startTime.trim(),
    end_time: values.endTime.trim(),
    break_minutes_paid: intOrZero(values.breakMinutesPaid),
    break_minutes_unpaid: intOrZero(values.breakMinutesUnpaid),
    grace_in_minutes: intOrZero(values.graceInMinutes),
    grace_out_minutes: intOrZero(values.graceOutMinutes),
    half_day_threshold_hours: decimalOrNull(values.halfDayThresholdHours),
    min_hours_full_day: decimalOrNull(values.minHoursFullDay),
    is_night_shift: values.isNightShift,
    is_cross_midnight: values.isCrossMidnight,
    is_ot_eligible: values.isOtEligible,
  };
}

/** Diff-only payload for `PATCH /shifts/{id}`. */
export function buildUpdatePatch(values: ShiftFormValues, shift: Shift): Record<string, unknown> {
  const patch: Record<string, unknown> = {};

  if (values.name.trim() !== shift.name) patch.name = values.name.trim();

  const code = values.code.trim() || null;
  if (code !== shift.code) patch.code = code;

  if (values.startTime.trim() !== shift.start_time) patch.start_time = values.startTime.trim();
  if (values.endTime.trim() !== shift.end_time) patch.end_time = values.endTime.trim();

  const breakMinutesPaid = intOrZero(values.breakMinutesPaid);
  if (breakMinutesPaid !== shift.break_minutes_paid) patch.break_minutes_paid = breakMinutesPaid;

  const breakMinutesUnpaid = intOrZero(values.breakMinutesUnpaid);
  if (breakMinutesUnpaid !== shift.break_minutes_unpaid) {
    patch.break_minutes_unpaid = breakMinutesUnpaid;
  }

  const graceInMinutes = intOrZero(values.graceInMinutes);
  if (graceInMinutes !== shift.grace_in_minutes) patch.grace_in_minutes = graceInMinutes;

  const graceOutMinutes = intOrZero(values.graceOutMinutes);
  if (graceOutMinutes !== shift.grace_out_minutes) patch.grace_out_minutes = graceOutMinutes;

  const halfDayThresholdHours = decimalOrNull(values.halfDayThresholdHours);
  if (halfDayThresholdHours !== shift.half_day_threshold_hours) {
    patch.half_day_threshold_hours = halfDayThresholdHours;
  }

  const minHoursFullDay = decimalOrNull(values.minHoursFullDay);
  if (minHoursFullDay !== shift.min_hours_full_day) patch.min_hours_full_day = minHoursFullDay;

  if (values.isNightShift !== shift.is_night_shift) patch.is_night_shift = values.isNightShift;
  if (values.isCrossMidnight !== shift.is_cross_midnight) {
    patch.is_cross_midnight = values.isCrossMidnight;
  }
  if (values.isOtEligible !== shift.is_ot_eligible) patch.is_ot_eligible = values.isOtEligible;

  return patch;
}

export function validateShiftForm(values: ShiftFormValues): ShiftFormErrors {
  const errors: ShiftFormErrors = {};

  if (!values.name.trim()) {
    errors.name = "Shift name is required.";
  }

  if (!values.startTime.trim()) {
    errors.startTime = "Start time is required.";
  } else if (!TIME_PATTERN.test(values.startTime.trim())) {
    errors.startTime = "Use HH:mm format.";
  }

  if (!values.endTime.trim()) {
    errors.endTime = "End time is required.";
  } else if (!TIME_PATTERN.test(values.endTime.trim())) {
    errors.endTime = "Use HH:mm format.";
  }

  if (
    !errors.startTime &&
    !errors.endTime &&
    values.endTime.trim() <= values.startTime.trim() &&
    !values.isCrossMidnight
  ) {
    errors.endTime = "End time must be after start time unless this is a cross-midnight shift.";
  }

  const halfDayThresholdHours = decimalOrNull(values.halfDayThresholdHours);
  const minHoursFullDay = decimalOrNull(values.minHoursFullDay);
  if (
    halfDayThresholdHours !== null &&
    minHoursFullDay !== null &&
    halfDayThresholdHours >= minHoursFullDay
  ) {
    errors.minHoursFullDay = "Min hours for full day must be greater than the half-day threshold.";
  }

  return errors;
}
