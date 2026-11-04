import {
  EMPTY_SHIFT_VERSION_FORM_VALUES as BASE,
  type ShiftVersionFormValues,
} from "@/lib/shift/validate-shift-version";
import { DEFAULT_TIMEZONE } from "@/lib/timezones";

export interface ShiftTemplate {
  key: string;
  label: string;
  description: string;
  defaultName: string;
  /** Everything except the start date, which is chosen in the form. */
  values: Omit<ShiftVersionFormValues, "effectiveFrom">;
}

const FIXED = { ...BASE, shiftType: "FIXED" as const, timezone: DEFAULT_TIMEZONE };

/** Common starting points; change the times to match the workplace. */
export const SHIFT_TEMPLATES: ShiftTemplate[] = [
  {
    key: "general",
    label: "General (9 to 6)",
    description: "A fixed day shift from 09:00 to 18:00.",
    defaultName: "General shift",
    values: { ...FIXED, startTime: "09:00", endTime: "18:00" },
  },
  {
    key: "morning",
    label: "Morning (6 to 2)",
    description: "A fixed shift from 06:00 to 14:00.",
    defaultName: "Morning shift",
    values: { ...FIXED, startTime: "06:00", endTime: "14:00" },
  },
  {
    key: "evening",
    label: "Evening (2 to 10)",
    description: "A fixed shift from 14:00 to 22:00.",
    defaultName: "Evening shift",
    values: { ...FIXED, startTime: "14:00", endTime: "22:00" },
  },
  {
    key: "night",
    label: "Night (10 to 6)",
    description: "A fixed shift from 22:00 to 06:00 the next morning, marked as a night shift.",
    defaultName: "Night shift",
    values: { ...FIXED, startTime: "22:00", endTime: "06:00", isNightShift: true },
  },
  {
    key: "flexible",
    label: "Flexible hours",
    description: "Arrive any time between 08:00 and 11:00 and work 8 hours.",
    defaultName: "Flexible shift",
    values: {
      ...BASE,
      shiftType: "FLEXIBLE",
      timezone: DEFAULT_TIMEZONE,
      windowStart: "08:00",
      windowEnd: "11:00",
      requiredMinutes: "480",
    },
  },
  {
    key: "blank",
    label: "Start from scratch",
    description: "Set the schedule yourself.",
    defaultName: "",
    values: { ...BASE, timezone: DEFAULT_TIMEZONE },
  },
];
