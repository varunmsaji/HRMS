/** `GET /v1/attendance/pattern-alerts`: who keeps being late or absent. The server decides who is
 * flagged (thresholds in `Settings.attendance_pattern_*`); this file only words it. */

export type PatternKind = "repeat_late" | "frequent_absence" | "repeat_missing_punch" | "repeat_absent_weekday";

export interface PatternThresholds {
  window_days: number;
  weekday_window_days: number;
  late_days: number;
  absent_days: number;
  incomplete_days: number;
  weekday_absences: number;
}

export interface PatternAlert {
  employee_id: string;
  kind: PatternKind;
  count: number;
  /** The days behind the alert, newest first (at most five). */
  dates: string[];
  /** For `repeat_absent_weekday`: 0 = Monday ... 6 = Sunday. */
  weekday: number | null;
}

export interface PatternAlerts {
  as_of: string;
  thresholds: PatternThresholds;
  alerts: PatternAlert[];
}

export const PATTERN_KIND_LABELS: Record<PatternKind, string> = {
  repeat_late: "Often late",
  frequent_absence: "Often absent",
  repeat_missing_punch: "Missing punches",
  repeat_absent_weekday: "Absent on the same weekday",
};

const WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];

/** The pattern in a few words, for example "late on 6 days in the last 30". */
export function describePattern(alert: PatternAlert, t: PatternThresholds): string {
  switch (alert.kind) {
    case "repeat_late":
      return `late on ${alert.count} days in the last ${t.window_days}`;
    case "frequent_absence":
      return `absent on ${alert.count} days in the last ${t.window_days}`;
    case "repeat_missing_punch":
      return `missing a punch on ${alert.count} days in the last ${t.window_days}`;
    case "repeat_absent_weekday":
      return `absent on ${alert.count} ${WEEKDAYS[alert.weekday ?? 0]}s in the last ${t.weekday_window_days} days`;
  }
}
