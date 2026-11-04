export const ELIGIBILITY_LABELS: Record<string, string> = {
  SHIFT_FLAG: "Only shifts marked as overtime-eligible",
  ALWAYS: "Everyone",
  NEVER: "Nobody (overtime is off)",
  GRADE_VIA_ASSIGNMENT: "By grade",
};

export const ROUNDING_LABELS: Record<string, string> = {
  NONE: "No rounding",
  NEAREST: "To the nearest",
  UP: "Round up",
  DOWN: "Round down",
};

export const NIGHT_MODE_LABELS: Record<string, string> = {
  SHIFT_FLAG: "When the shift is a night shift",
  WINDOW: "When it falls inside the night hours",
  BOTH: "Either of those",
};

export const DAY_CLASS_LABELS: Record<string, string> = {
  NORMAL: "Normal day",
  WEEKLY_OFF: "Weekly off",
  HOLIDAY: "Holiday",
  NIGHT: "Night",
};
