import type {
  RegularizationRequestCreatePayload,
  RegularizationType,
} from "@/lib/regularization/types";

/** Form state for the "raise a regularization" dialog. `correctionKind` collapses the backend's
 * punch-or-shift requirement (WD-28 decision 2 — every request needs one or the other) into one
 * choice: `WRONG_SHIFT` always corrects via a shift pick, every other type corrects via punch
 * times. Punch entry is deliberately a single IN/OUT pair (not an arbitrary list) — it covers
 * missing/wrong punch and full-day corrections, the primary real-world cases; a multi-interval
 * editor is not required by any of this slice's phases. */
export type RegularizationCorrectionKind = "PUNCHES" | "SHIFT";

export interface RegularizationFormValues {
  attendanceDate: string;
  requestType: RegularizationType | "";
  reason: string;
  correctionKind: RegularizationCorrectionKind;
  shiftId: string;
  punchInTime: string;
  punchOutTime: string;
  attachmentReference: string;
}

export type RegularizationFormErrors = Partial<
  Record<"attendanceDate" | "requestType" | "reason" | "shiftId" | "punches" | "attachment", string>
>;

export function emptyRegularizationFormValues(
  overrides?: Partial<RegularizationFormValues>,
): RegularizationFormValues {
  return {
    attendanceDate: "",
    requestType: "",
    reason: "",
    correctionKind: "PUNCHES",
    shiftId: "",
    punchInTime: "",
    punchOutTime: "",
    attachmentReference: "",
    ...overrides,
  };
}

/** Client-side checks only cover what's true regardless of policy config — `reason_required`/
 * `attachment_required`/`allowed_types` are `RegularizationPolicyVersion` fields gated behind
 * `ATTENDANCE.POLICY_MANAGE` (config-admin only), so an ordinary employee's browser cannot read
 * them before submitting. The backend remains the source of truth (Phase 1) and returns a 422
 * with a field-level error the dialog surfaces via `getFieldError`, same pattern as
 * `RosterEntryDialog`'s `shift_id` handling. */
export function validateRegularizationForm(values: RegularizationFormValues): RegularizationFormErrors {
  const errors: RegularizationFormErrors = {};
  if (!values.attendanceDate) errors.attendanceDate = "Choose the attendance date.";
  if (!values.requestType) errors.requestType = "Choose a request type.";
  if (values.correctionKind === "SHIFT" && !values.shiftId) {
    errors.shiftId = "Choose the correct shift.";
  }
  if (values.correctionKind === "PUNCHES" && !values.punchInTime && !values.punchOutTime) {
    errors.punches = "Enter at least one corrected punch time.";
  }
  return errors;
}

/** Interprets the entered date/time as the browser's local time and converts to UTC — same
 * convention as `PunchEntryDialog` (`new Date(punchTime).toISOString()` on a `datetime-local`
 * value), not a raw UTC literal. Neither is perfectly correct in general (the semantically right
 * answer depends on the employee's *shift* timezone, WD-06 — not the reviewer's browser), but
 * matching the existing punch-entry convention is consistent rather than introducing a third,
 * different interpretation. */
function toUtcIso(date: string, time: string): string {
  return new Date(`${date}T${time}`).toISOString();
}

export function buildRegularizationCreatePayload(
  values: RegularizationFormValues,
  employeeId?: string,
): RegularizationRequestCreatePayload {
  const payload: RegularizationRequestCreatePayload = {
    attendance_date: values.attendanceDate,
    request_type: values.requestType as RegularizationType,
    reason: values.reason.trim() || undefined,
    attachment_reference: values.attachmentReference.trim() || undefined,
  };
  if (employeeId) payload.employee_id = employeeId;

  if (values.correctionKind === "SHIFT") {
    payload.requested_shift_id = values.shiftId;
  } else {
    payload.requested_punches = [];
    if (values.punchInTime) {
      payload.requested_punches.push({
        direction: "IN",
        requested_time: toUtcIso(values.attendanceDate, values.punchInTime),
      });
    }
    if (values.punchOutTime) {
      payload.requested_punches.push({
        direction: "OUT",
        requested_time: toUtcIso(values.attendanceDate, values.punchOutTime),
      });
    }
  }
  return payload;
}
