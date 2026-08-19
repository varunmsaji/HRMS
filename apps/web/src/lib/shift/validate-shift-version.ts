import type { ErrorDetail } from "@/lib/api/types";
import type {
  ShiftBreak,
  ShiftBreakKind,
  ShiftDutyBlock,
  ShiftVersion,
  ShiftVersionType,
} from "@/lib/shift/types";

const TIME_PATTERN = /^\d{2}:\d{2}$/;

export interface ShiftBreakFormValue {
  name: string;
  breakKind: ShiftBreakKind;
  startTime: string;
  endTime: string;
  windowStart: string;
  windowEnd: string;
  minMinutes: string;
  maxMinutes: string;
  scheduledMinutes: string;
  isPaid: boolean;
  isMandatory: boolean;
  allowsSplit: boolean;
}

export interface ShiftDutyBlockFormValue {
  startTime: string;
  endTime: string;
}

export interface ShiftVersionFormValues {
  shiftType: ShiftVersionType | "";
  timezone: string;
  effectiveFrom: string;
  startTime: string;
  endTime: string;
  windowStart: string;
  windowEnd: string;
  coreStart: string;
  coreEnd: string;
  requiredMinutes: string;
  scheduledMinutes: string;
  minScheduledMinutes: string;
  maxScheduledMinutes: string;
  isNightShift: boolean;
  isOtEligible: boolean;
  operatesOnHoliday: boolean;
  operatesOnWeeklyOff: boolean;
  weeklyOffPatternId: string;
  breaks: ShiftBreakFormValue[];
  dutyBlocks: ShiftDutyBlockFormValue[];
}

export const EMPTY_BREAK_FORM_VALUE: ShiftBreakFormValue = {
  name: "",
  breakKind: "FIXED_WINDOW",
  startTime: "",
  endTime: "",
  windowStart: "",
  windowEnd: "",
  minMinutes: "",
  maxMinutes: "",
  scheduledMinutes: "",
  isPaid: false,
  isMandatory: true,
  allowsSplit: false,
};

export const EMPTY_DUTY_BLOCK_FORM_VALUE: ShiftDutyBlockFormValue = {
  startTime: "",
  endTime: "",
};

export const EMPTY_SHIFT_VERSION_FORM_VALUES: ShiftVersionFormValues = {
  shiftType: "",
  timezone: "",
  effectiveFrom: "",
  startTime: "",
  endTime: "",
  windowStart: "",
  windowEnd: "",
  coreStart: "",
  coreEnd: "",
  requiredMinutes: "",
  scheduledMinutes: "",
  minScheduledMinutes: "",
  maxScheduledMinutes: "",
  isNightShift: false,
  isOtEligible: false,
  operatesOnHoliday: false,
  operatesOnWeeklyOff: false,
  weeklyOffPatternId: "",
  breaks: [],
  dutyBlocks: [],
};

export interface ShiftBreakFormErrors {
  name?: string;
  startTime?: string;
  endTime?: string;
  windowStart?: string;
  windowEnd?: string;
  minMinutes?: string;
  maxMinutes?: string;
}

export interface ShiftVersionFormErrors {
  shiftType?: string;
  effectiveFrom?: string;
  startTime?: string;
  endTime?: string;
  windowStart?: string;
  windowEnd?: string;
  coreStart?: string;
  coreEnd?: string;
  requiredMinutes?: string;
  dutyBlocks?: string;
  breaks?: string;
  breakRows?: ShiftBreakFormErrors[];
}

function intOrNull(value: string): number | null {
  const trimmed = value.trim();
  if (!trimmed) return null;
  const parsed = Number(trimmed);
  if (Number.isNaN(parsed)) return null;
  return Math.trunc(parsed);
}

function breakToFormValue(row: ShiftBreak): ShiftBreakFormValue {
  return {
    name: row.name,
    breakKind: row.break_kind,
    startTime: row.start_time ?? "",
    endTime: row.end_time ?? "",
    windowStart: row.window_start ?? "",
    windowEnd: row.window_end ?? "",
    minMinutes: row.min_minutes === null ? "" : String(row.min_minutes),
    maxMinutes: row.max_minutes === null ? "" : String(row.max_minutes),
    scheduledMinutes: row.scheduled_minutes === null ? "" : String(row.scheduled_minutes),
    isPaid: row.is_paid,
    isMandatory: row.is_mandatory,
    allowsSplit: row.allows_split,
  };
}

function dutyBlockToFormValue(row: ShiftDutyBlock): ShiftDutyBlockFormValue {
  return { startTime: row.start_time, endTime: row.end_time };
}

export function shiftVersionToFormValues(version: ShiftVersion): ShiftVersionFormValues {
  return {
    shiftType: version.shift_type ?? "",
    timezone: version.timezone ?? "",
    effectiveFrom: version.effective_from ?? "",
    startTime: version.start_time ?? "",
    endTime: version.end_time ?? "",
    windowStart: version.window_start ?? "",
    windowEnd: version.window_end ?? "",
    coreStart: version.core_start ?? "",
    coreEnd: version.core_end ?? "",
    requiredMinutes: version.required_minutes === null ? "" : String(version.required_minutes),
    scheduledMinutes:
      version.scheduled_minutes === null ? "" : String(version.scheduled_minutes),
    minScheduledMinutes:
      version.min_scheduled_minutes === null ? "" : String(version.min_scheduled_minutes),
    maxScheduledMinutes:
      version.max_scheduled_minutes === null ? "" : String(version.max_scheduled_minutes),
    isNightShift: version.is_night_shift,
    isOtEligible: version.is_ot_eligible,
    operatesOnHoliday: version.operates_on_holiday,
    operatesOnWeeklyOff: version.operates_on_weekly_off,
    weeklyOffPatternId: version.weekly_off_pattern_id ?? "",
    breaks: version.breaks
      .slice()
      .sort((a, b) => a.sort_order - b.sort_order)
      .map(breakToFormValue),
    dutyBlocks: version.duty_blocks
      .slice()
      .sort((a, b) => a.sequence - b.sequence)
      .map(dutyBlockToFormValue),
  };
}

function breakFormValueToPayload(row: ShiftBreakFormValue, sortOrder: number): Record<string, unknown> {
  const base = {
    name: row.name.trim(),
    break_kind: row.breakKind,
    is_paid: row.isPaid,
    is_mandatory: row.isMandatory,
    allows_split: row.allowsSplit,
    sort_order: sortOrder,
    scheduled_minutes: intOrNull(row.scheduledMinutes),
  };
  if (row.breakKind === "FIXED_WINDOW") {
    return { ...base, start_time: row.startTime.trim(), end_time: row.endTime.trim() };
  }
  return {
    ...base,
    window_start: row.windowStart.trim(),
    window_end: row.windowEnd.trim(),
    min_minutes: intOrNull(row.minMinutes),
    max_minutes: intOrNull(row.maxMinutes),
  };
}

function dutyBlockFormValueToPayload(
  row: ShiftDutyBlockFormValue,
  sequence: number,
): Record<string, unknown> {
  return { sequence, start_time: row.startTime.trim(), end_time: row.endTime.trim() };
}

/** Builds the `PATCH /shifts/{shift_id}/versions/{version_id}` body. Every field the form
 * collects is sent when relevant to the selected `shiftType` — draft PATCHes are safe to
 * resend unchanged (no diffing needed, unlike the identity Shift form), since a draft has no
 * external readers to disturb before publish. `breaks`/`duty_blocks` replace the entire nested
 * collection atomically, so they're included whenever the form holds any rows (or previously
 * did, to support clearing them back to empty). */
export function buildShiftVersionPatch(
  values: ShiftVersionFormValues,
  current: ShiftVersion | null,
): Record<string, unknown> {
  const patch: Record<string, unknown> = {};

  if (values.shiftType) patch.shift_type = values.shiftType;
  if (values.timezone.trim()) patch.timezone = values.timezone.trim();
  if (values.effectiveFrom) patch.effective_from = values.effectiveFrom;

  if (values.shiftType === "FIXED") {
    patch.start_time = values.startTime.trim();
    patch.end_time = values.endTime.trim();
  } else if (values.shiftType === "FLEXIBLE") {
    patch.window_start = values.windowStart.trim();
    patch.window_end = values.windowEnd.trim();
    patch.required_minutes = intOrNull(values.requiredMinutes);
    if (values.coreStart.trim() || values.coreEnd.trim()) {
      patch.core_start = values.coreStart.trim();
      patch.core_end = values.coreEnd.trim();
    }
  }

  if (values.scheduledMinutes.trim()) patch.scheduled_minutes = intOrNull(values.scheduledMinutes);
  if (values.minScheduledMinutes.trim()) {
    patch.min_scheduled_minutes = intOrNull(values.minScheduledMinutes);
  }
  if (values.maxScheduledMinutes.trim()) {
    patch.max_scheduled_minutes = intOrNull(values.maxScheduledMinutes);
  }

  patch.is_night_shift = values.isNightShift;
  patch.is_ot_eligible = values.isOtEligible;
  patch.operates_on_holiday = values.operatesOnHoliday;
  patch.operates_on_weekly_off = values.operatesOnWeeklyOff;
  patch.weekly_off_pattern_id = values.weeklyOffPatternId || null;

  const hadBreaks = (current?.breaks.length ?? 0) > 0;
  if (values.breaks.length > 0 || hadBreaks) {
    patch.breaks = values.breaks.map((row, index) => breakFormValueToPayload(row, index));
  }

  const hadDutyBlocks = (current?.duty_blocks.length ?? 0) > 0;
  if (values.dutyBlocks.length > 0 || hadDutyBlocks) {
    patch.duty_blocks = values.dutyBlocks.map((row, index) =>
      dutyBlockFormValueToPayload(row, index + 1),
    );
  }

  return patch;
}

/** Light client-side pre-check — the backend is authoritative (publish-time validation covers
 * far more, e.g. duty-block overlap, break-outside-window). This just catches the most common
 * "forgot a required field" mistakes before a round-trip. */
export function validateShiftVersionForm(values: ShiftVersionFormValues): ShiftVersionFormErrors {
  const errors: ShiftVersionFormErrors = {};

  if (!values.shiftType) {
    errors.shiftType = "Choose a schedule type.";
    return errors;
  }

  if (values.shiftType === "FIXED") {
    if (!values.startTime.trim() || !TIME_PATTERN.test(values.startTime.trim())) {
      errors.startTime = "Start time is required (HH:mm).";
    }
    if (!values.endTime.trim() || !TIME_PATTERN.test(values.endTime.trim())) {
      errors.endTime = "End time is required (HH:mm).";
    }
    if (
      !errors.startTime &&
      !errors.endTime &&
      values.startTime.trim() === values.endTime.trim()
    ) {
      errors.endTime = "End time must differ from start time.";
    }
  }

  if (values.shiftType === "FLEXIBLE") {
    if (!values.windowStart.trim() || !TIME_PATTERN.test(values.windowStart.trim())) {
      errors.windowStart = "Window start is required (HH:mm).";
    }
    if (!values.windowEnd.trim() || !TIME_PATTERN.test(values.windowEnd.trim())) {
      errors.windowEnd = "Window end is required (HH:mm).";
    }
    if (!values.requiredMinutes.trim()) {
      errors.requiredMinutes = "Required minutes is required.";
    }
    if ((values.coreStart.trim() !== "") !== (values.coreEnd.trim() !== "")) {
      errors.coreEnd = "Core start and core end must be given together.";
    }
  }

  if (values.shiftType === "SPLIT" && values.dutyBlocks.length < 2) {
    errors.dutyBlocks = "A split shift needs at least 2 duty blocks to publish.";
  }

  const breakRowErrors: ShiftBreakFormErrors[] = values.breaks.map((row) => {
    const rowErrors: ShiftBreakFormErrors = {};
    if (!row.name.trim()) rowErrors.name = "Name is required.";
    if (row.breakKind === "FIXED_WINDOW") {
      if (!row.startTime.trim()) rowErrors.startTime = "Start time is required.";
      if (!row.endTime.trim()) rowErrors.endTime = "End time is required.";
    } else {
      if (!row.windowStart.trim()) rowErrors.windowStart = "Window start is required.";
      if (!row.windowEnd.trim()) rowErrors.windowEnd = "Window end is required.";
      if (!row.minMinutes.trim()) rowErrors.minMinutes = "Minimum minutes is required.";
      if (!row.maxMinutes.trim()) rowErrors.maxMinutes = "Maximum minutes is required.";
    }
    return rowErrors;
  });
  if (breakRowErrors.some((row) => Object.keys(row).length > 0)) {
    errors.breakRows = breakRowErrors;
  }

  return errors;
}

const API_FIELD_TO_FORM_FIELD: Partial<Record<string, keyof ShiftVersionFormErrors>> = {
  shift_type: "shiftType",
  effective_from: "effectiveFrom",
  start_time: "startTime",
  end_time: "endTime",
  window_start: "windowStart",
  window_end: "windowEnd",
  core_start: "coreStart",
  core_end: "coreEnd",
  required_minutes: "requiredMinutes",
};

const BREAK_ROW_FIELD_MAP: Partial<Record<string, keyof ShiftBreakFormErrors>> = {
  start_time: "startTime",
  end_time: "endTime",
  window_start: "windowStart",
  window_end: "windowEnd",
  min_minutes: "minMinutes",
  max_minutes: "maxMinutes",
};

/** Maps `ApiError.details` (e.g. from a 422 on `PATCH/POST .../versions*`) back onto the form's
 * error shape — `breaks.1.end_time` becomes `breakRows[1].endTime`, everything else maps by
 * name or falls through to a general message under the closest matching section. */
export function mapShiftVersionApiErrors(details: ErrorDetail[]): ShiftVersionFormErrors {
  const errors: ShiftVersionFormErrors = {};
  const breakRows: ShiftBreakFormErrors[] = [];

  for (const detail of details) {
    const field = detail.field ?? "";
    const segments = field.split(".");

    if (segments[0] === "breaks") {
      if (segments.length >= 3) {
        const index = Number(segments[1]);
        const rowField = BREAK_ROW_FIELD_MAP[segments[2]];
        if (!Number.isNaN(index) && rowField) {
          breakRows[index] = { ...breakRows[index], [rowField]: detail.message };
          continue;
        }
      }
      errors.breaks = detail.message;
      continue;
    }

    if (segments[0] === "duty_blocks") {
      errors.dutyBlocks = detail.message;
      continue;
    }

    const formField = API_FIELD_TO_FORM_FIELD[field];
    if (formField) {
      (errors as Record<string, string>)[formField] = detail.message;
    }
  }

  if (breakRows.length > 0) errors.breakRows = breakRows;
  return errors;
}
