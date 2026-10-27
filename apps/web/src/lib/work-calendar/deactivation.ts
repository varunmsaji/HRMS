import type { ApiError } from "@/lib/api/errors";

const BLOCKED_CODES = new Set([
  "WORK_CALENDAR_HAS_ACTIVE_ASSIGNMENTS",
  "WEEKLY_OFF_PATTERN_HAS_ACTIVE_ASSIGNMENTS",
]);

interface BlockedContext {
  active_assignment_count?: number;
  default_for_work_calendars?: number;
  next_action?: string;
}

/**
 * Explains a 409 from deactivating a work calendar or weekly-off pattern that is still in use,
 * using only what the API returned (counts and the next action). `null` for any other error.
 */
export function describeDeactivationBlocked(error: ApiError): string | null {
  if (!BLOCKED_CODES.has(error.code)) return null;
  const context = (error.details.find((d) => BLOCKED_CODES.has(String(d.code)))?.context ??
    {}) as BlockedContext;
  const parts: string[] = [];
  if (context.active_assignment_count) {
    const n = context.active_assignment_count;
    parts.push(`${n} active or future assignment${n === 1 ? "" : "s"}`);
  }
  if (context.default_for_work_calendars) {
    const n = context.default_for_work_calendars;
    parts.push(`${n} active work calendar${n === 1 ? "" : "s"} that use it as the default pattern`);
  }
  const what = parts.length > 0 ? `It is still used by ${parts.join(" and ")}. ` : "";
  return `${what}${
    context.next_action ??
    "Reassign the affected scopes or end the assignments first, then deactivate."
  }`;
}
