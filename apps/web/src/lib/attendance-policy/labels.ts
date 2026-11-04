/** Plain-language names for the stored rule values, shared by the form and the read-only summary.
 * Meanings follow the Settings Guide's Attendance Policies section. */
export const MISSING_PUNCH_LABELS: Record<string, string> = {
  INCOMPLETE: "Flag the day for someone to fix",
  ABSENT: "Mark the day absent",
  AUTO_CLOSE: "Close automatically",
  REQUIRE_REGULARIZATION: "Wait for a correction request",
};

export const MISSING_SHIFT_LABELS: Record<string, string> = {
  INCOMPLETE: "Flag the day for someone to fix",
  ABSENT: "Mark the day absent",
};

export const MULTI_PUNCH_LABELS: Record<string, string> = {
  PAIR_ALL: "Count only time between each in and out",
  FIRST_IN_LAST_OUT: "Count from first in to last out, gaps included",
};

export const CORE_HOURS_LABELS: Record<string, string> = {
  IGNORE: "Do nothing",
  FLAG: "Flag for reports",
  HALF_DAY: "Make it a half-day",
  ABSENT: "Make it absent",
};

export const SPLIT_MISSED_BLOCK_LABELS: Record<string, string> = {
  IGNORE: "Do nothing",
  HALF_DAY: "Make it a half-day",
  ABSENT: "Make it absent",
  REQUIRE_REGULARIZATION: "Wait for a correction request",
};

export const INCOMPLETE_AT_LOCK_LABELS: Record<string, string> = {
  TREAT_ABSENT: "Count as absent (unpaid)",
  TREAT_PRESENT: "Count as present (paid)",
  KEEP_INCOMPLETE: "Refuse to close until resolved",
};

export const BAND_RESULT_LABELS: Record<string, string> = {
  NONE: "No effect",
  PRESENT: "Present",
  LATE: "Late",
  EARLY_DEPARTURE: "Early departure",
  HALF_DAY: "Half-day",
  ABSENT: "Absent",
};

export function labelOf(labels: Record<string, string>, value: string): string {
  return labels[value] ?? value.replaceAll("_", " ");
}

/** "8 hours", "4 hours 30 minutes", "45 minutes". */
export function formatMinutes(minutes: number): string {
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  const parts = [];
  if (hours > 0) parts.push(`${hours} ${hours === 1 ? "hour" : "hours"}`);
  if (rest > 0 || hours === 0) parts.push(`${rest} ${rest === 1 ? "minute" : "minutes"}`);
  return parts.join(" ");
}
