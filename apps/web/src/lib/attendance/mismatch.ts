import { bucketOf, isWorkOnLeaveUnresolved } from "@/lib/attendance/dashboard";
import type { AttendanceDay } from "@/lib/attendance/types";

/** What is wrong with a day that HR can act on. Informational flags (late, early out, overtime)
 * are not mismatches: nothing needs fixing, only noting. */
export type MismatchKind =
  | "config_error"
  | "work_on_leave"
  | "missing_out"
  | "missing_in"
  | "no_punches"
  | "incomplete"
  | "pending_approval";

export interface Mismatch {
  kind: MismatchKind;
  /** One plain-language line for the list. */
  reason: string;
}

/** The single most important problem with a day, or `null` when the day is fine. Order matters:
 * a day that cannot be calculated or conflicts with leave must be settled before its punches are. */
export function mismatchOf(day: AttendanceDay): Mismatch | null {
  if (bucketOf(day) === "CONFIG_ERROR") {
    return { kind: "config_error", reason: "Can't be calculated: the shift or policy is missing." };
  }
  if (isWorkOnLeaveUnresolved(day)) {
    return { kind: "work_on_leave", reason: "Punched in on a day of approved leave." };
  }
  const incomplete = day.attendance_status === "INCOMPLETE";
  if (day.missing_punch || incomplete) {
    if (!day.actual_first_in && !day.actual_last_out) return { kind: "no_punches", reason: "Nothing was punched on a working day." };
    if (day.actual_first_in && !day.actual_last_out) return { kind: "missing_out", reason: "Checked in but never checked out." };
    if (!day.actual_first_in && day.actual_last_out) return { kind: "missing_in", reason: "Checked out with no check-in." };
    return { kind: "incomplete", reason: "Punches don't add up to a full day." };
  }
  if (day.is_pending_approval) return { kind: "pending_approval", reason: "Waiting for an approval." };
  return null;
}
