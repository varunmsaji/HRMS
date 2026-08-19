import { Badge, type BadgeProps } from "@/components/ui/badge";
import { ATTENDANCE_STATUS_LABELS, type AttendanceStatus } from "@/lib/attendance/types";

const STATUS_VARIANT: Record<AttendanceStatus, NonNullable<BadgeProps["variant"]>> = {
  NOT_JOINED: "outline",
  EXITED: "outline",
  NOT_EXPECTED: "secondary",
  PRESENT: "success",
  HALF_DAY: "warning",
  ABSENT: "danger",
  LEAVE: "on-leave",
  ON_DUTY: "info",
  WFH: "info",
  INCOMPLETE: "warning",
  CONFIG_ERROR: "danger",
};

interface AttendanceStatusBadgeProps {
  status: string;
}

/** Mirrors `EmployeeStatusBadge` — falls back to a plain outline badge for any value outside
 * the known set rather than throwing, since the backend's status set is not client-fixed. */
export function AttendanceStatusBadge({ status }: AttendanceStatusBadgeProps) {
  const known = status in STATUS_VARIANT ? (status as AttendanceStatus) : null;
  return (
    <Badge variant={known ? STATUS_VARIANT[known] : "outline"}>
      {known ? ATTENDANCE_STATUS_LABELS[known] : status}
    </Badge>
  );
}
