/** Mirrors `apps/api/src/hrms/modules/organisation/calendar_impact.py`. */

export type ProposedChange =
  | { change_type: "HOLIDAY_CREATE"; holiday_calendar_id: string; body: Record<string, unknown> }
  | {
      change_type: "HOLIDAY_UPDATE";
      holiday_id: string;
      expected_version: number;
      patch: Record<string, unknown>;
    }
  | {
      change_type: "HOLIDAY_CALENDAR_UPDATE";
      holiday_calendar_id: string;
      expected_version: number;
      patch: Record<string, unknown>;
    }
  | { change_type: "EXCEPTION_CREATE"; work_calendar_id: string; body: Record<string, unknown> }
  | {
      change_type: "EXCEPTION_UPDATE";
      exception_id: string;
      expected_version: number;
      patch: Record<string, unknown>;
    }
  | {
      change_type: "WEEKLY_OFF_PATTERN_UPDATE";
      pattern_id: string;
      expected_version: number;
      patch: Record<string, unknown>;
    }
  | {
      change_type: "WORK_CALENDAR_UPDATE";
      work_calendar_id: string;
      expected_version: number;
      patch: Record<string, unknown>;
    }
  | {
      change_type: "ASSIGNMENT_CREATE";
      body: Record<string, unknown>;
      expected_version?: number;
    };

export interface DaySnapshot {
  configured: boolean;
  day_type: string | null;
  label: string | null;
  weekly_off_fraction: string | null;
}

export interface ImpactRow {
  date: string;
  previous: DaySnapshot;
  proposed: DaySnapshot;
  affected_employee_count: number;
}

export interface ImpactWarning {
  code: string;
  message: string;
}

export interface LeaveImpactItem {
  application_id: string;
  employee_id: string;
  employee_code: string;
  date: string;
  status: "APPROVED" | "PENDING";
  previous_day_type: string | null;
  proposed_day_type: string | null;
}

export interface ProtectedPeriod {
  id: string;
  kind: "ATTENDANCE_PERIOD" | "PAY_RUN";
  legal_entity_id: string;
  period_start: string;
  period_end: string;
  status: string;
  changed_dates_in_period: number;
}

export interface ImpactPreview {
  change_type: string;
  window_from: string;
  window_to: string;
  population: {
    employees_in_scope: number;
    employees_analysed: number;
    groups_analysed: number;
    complete: boolean;
  };
  changed_date_count: number;
  affected_employee_count: number;
  rows: ImpactRow[];
  rows_truncated: boolean;
  employee_samples: Array<{
    employee_id: string;
    employee_code: string;
    name: string;
    changed_date_count: number;
  }>;
  excluded_not_employed_employee_dates: number;
  incomplete_configuration: { employees: number; dates: number };
  leave_impact: {
    approved_day_records: number;
    pending_day_records: number;
    applications: number;
    employees: number;
    items: LeaveImpactItem[];
    items_truncated: boolean;
    records_modified: 0;
  };
  protected_periods: ProtectedPeriod[];
  warnings: ImpactWarning[];
  requires_acknowledgement: boolean;
  impact_digest: string;
}

export interface ImpactConfirmed {
  change_type: string;
  entity_id: string | null;
  impact_digest: string;
  affected_employee_count: number;
  changed_date_count: number;
  confirmed_by: string | null;
  confirmed_at: string;
}

export const DAY_TYPE_LABELS: Record<string, string> = {
  WORKING: "Working day",
  WEEKLY_OFF: "Weekly off",
  HOLIDAY: "Holiday",
  SPECIAL_WORKING: "Special working day",
  SHUTDOWN: "Shutdown",
};

/** "Weekly off — Founders Day", "Working day", "Not set up". Text only, never colour. */
export function describeSnapshot(snapshot: DaySnapshot): string {
  if (!snapshot.configured || !snapshot.day_type) return "No calendar set up";
  const base = DAY_TYPE_LABELS[snapshot.day_type] ?? snapshot.day_type;
  const half =
    snapshot.day_type === "WEEKLY_OFF" &&
    snapshot.weekly_off_fraction !== null &&
    Number(snapshot.weekly_off_fraction) < 1
      ? " (half day)"
      : "";
  return snapshot.label ? `${base}${half} — ${snapshot.label}` : `${base}${half}`;
}

/** Default preview window: today through the next 180 days (the API allows up to 366). */
export function defaultWindow(today: string): { from: string; to: string } {
  const [y, m, d] = today.split("-").map(Number);
  const end = new Date(Date.UTC(y, m - 1, d + 179));
  return { from: today, to: end.toISOString().slice(0, 10) };
}
