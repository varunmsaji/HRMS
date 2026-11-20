import { Badge, type BadgeProps } from "@/components/ui/badge";
import { BUCKET_LABELS, type DayBucket } from "@/lib/attendance/dashboard";
import {
  ATTENDANCE_STATUS_LABELS,
  type AttendanceDayDisplay,
  type AttendanceStatus,
} from "@/lib/attendance/types";

const STATUS_VARIANT: Record<AttendanceStatus, NonNullable<BadgeProps["variant"]>> = {
  NOT_JOINED: "outline",
  EXITED: "outline",
  NOT_EXPECTED: "secondary",
  PRESENT: "success",
  HALF_DAY: "half-day",
  ABSENT: "danger",
  LEAVE: "on-leave",
  ON_DUTY: "info",
  WFH: "wfh",
  INCOMPLETE: "warning",
  CONFIG_ERROR: "danger",
};

/** Badge look per backend display code (the day's bucket). */
const CODE_VARIANT: Record<string, NonNullable<BadgeProps["variant"]>> = {
  PRESENT: "success",
  REMOTE: "wfh",
  ON_DUTY: "info",
  HALF_DAY: "half-day",
  ABSENT: "danger",
  LEAVE: "on-leave",
  INCOMPLETE: "warning",
  CONFIG_ERROR: "danger",
  HOLIDAY: "secondary",
  WEEKLY_OFF: "secondary",
  NON_WORKING: "secondary",
  NOT_EMPLOYED: "outline",
  NOT_CHECKED_IN: "outline",
};

interface AttendanceStatusBadgeProps {
  status: string;
  /** The day's `display` from the API. When present it names the badge; `status` is the fallback. */
  display?: AttendanceDayDisplay | null;
}

/** Mirrors `EmployeeStatusBadge` — falls back to a plain outline badge for any value outside
 * the known set rather than throwing, since the backend's status set is not client-fixed. */
export function AttendanceStatusBadge({ status, display }: AttendanceStatusBadgeProps) {
  if (display) {
    const known = display.code in CODE_VARIANT;
    return (
      <Badge variant={known ? CODE_VARIANT[display.code] : "outline"} dot>
        {display.label || (BUCKET_LABELS as Record<string, string>)[display.code as DayBucket] || status}
      </Badge>
    );
  }
  const known = status in STATUS_VARIANT ? (status as AttendanceStatus) : null;
  return (
    <Badge variant={known ? STATUS_VARIANT[known] : "outline"} dot>
      {known ? ATTENDANCE_STATUS_LABELS[known] : status}
    </Badge>
  );
}
