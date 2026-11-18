import {
  EMPTY_ATTENDANCE_POLICY_VERSION_FORM_VALUES,
  type AttendancePolicyVersionFormValues,
  type PolicyBandFormRow,
} from "@/lib/attendance-policy/validate-attendance-policy";

export interface AttendancePolicyTemplate {
  key: string;
  label: string;
  description: string;
  defaultName: string;
  values: AttendancePolicyVersionFormValues;
}

function band(min: number, max: number | null, status: string): PolicyBandFormRow {
  return {
    minMinutes: String(min),
    maxMinutes: max === null ? "" : String(max),
    status,
    countsTowardCap: true,
  };
}

/** Under half the full-day hours is absent, up to the full day is a half-day, then present. */
function hourBands(fullDayMinutes: number): PolicyBandFormRow[] {
  const half = fullDayMinutes / 2;
  return [
    band(0, half - 1, "ABSENT"),
    band(half, fullDayMinutes - 1, "HALF_DAY"),
    band(fullDayMinutes, null, "PRESENT"),
  ];
}

/** Attendance rules audit AR-02 (owner decision D-01, 16 Nov 2026). Late or early by less than an
 * hour, beyond the grace, is a mark on the record and no more: it does not also cost half a day
 * because the day ended a few minutes short of the full-day hours. Without these bands the hours
 * alone decide, so arriving one minute past the grace and leaving on time is a half-day. From an
 * hour on, no band applies and the hours decide as before. */
const LATE_MARK_BANDS: PolicyBandFormRow[] = [band(1, 59, "LATE")];
const EARLY_MARK_BANDS: PolicyBandFormRow[] = [band(1, 59, "EARLY_DEPARTURE")];

const BASE = EMPTY_ATTENDANCE_POLICY_VERSION_FORM_VALUES;

export const ATTENDANCE_POLICY_TEMPLATES: AttendancePolicyTemplate[] = [
  {
    key: "standard",
    label: "Standard office",
    description:
      "10 minutes grace, 8 hours for a full day, 4 for a half-day. Late or early by under an hour is marked, not deducted.",
    defaultName: "Standard office",
    values: {
      ...BASE,
      graceInMinutes: "10",
      graceOutMinutes: "10",
      hourBands: hourBands(480),
      lateBands: LATE_MARK_BANDS,
      earlyDepartureBands: EARLY_MARK_BANDS,
    },
  },
  {
    key: "flexible",
    label: "Flexible hours",
    description:
      "30 minutes grace, 6 hours for a full day, 3 for a half-day. Late or early by under an hour is marked, not deducted.",
    defaultName: "Flexible hours",
    values: {
      ...BASE,
      graceInMinutes: "30",
      graceOutMinutes: "30",
      hourBands: hourBands(360),
      lateBands: LATE_MARK_BANDS,
      earlyDepartureBands: EARLY_MARK_BANDS,
    },
  },
  {
    key: "strict",
    label: "Strict attendance",
    description:
      "No grace, 8 hours for a full day. Every third late day in a month is a half-day, and leaving early needs approval.",
    defaultName: "Strict attendance",
    values: {
      ...BASE,
      latesToHalfDayCount: "3",
      earlyDepartureRequiresApproval: true,
      hourBands: hourBands(480),
      // A late arrival is a mark; the every-third-late rule is what deducts. Leaving early
      // without approval is a half-day (the harshest early band applies when unapproved).
      lateBands: LATE_MARK_BANDS,
      earlyDepartureBands: [band(1, 59, "EARLY_DEPARTURE"), band(60, null, "HALF_DAY")],
    },
  },
  {
    key: "blank",
    label: "Start from scratch",
    description: "Set every rule yourself.",
    defaultName: "",
    values: BASE,
  },
];
