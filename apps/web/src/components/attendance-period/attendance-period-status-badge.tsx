import { Badge, type BadgeProps } from "@/components/ui/badge";
import {
  ATTENDANCE_PERIOD_STATUS_LABELS,
  type AttendancePeriodStatus,
} from "@/lib/attendance-period/types";

const STATUS_VARIANT: Record<AttendancePeriodStatus, NonNullable<BadgeProps["variant"]>> = {
  OPEN: "success",
  CLOSED: "outline",
};

interface AttendancePeriodStatusBadgeProps {
  status: string;
}

/** Mirrors `OvertimeStatusBadge` — falls back to a plain outline badge for any value outside the
 * known set rather than throwing. */
export function AttendancePeriodStatusBadge({ status }: AttendancePeriodStatusBadgeProps) {
  const known = status in STATUS_VARIANT ? (status as AttendancePeriodStatus) : null;
  return (
    <Badge variant={known ? STATUS_VARIANT[known] : "outline"} dot>
      {known ? ATTENDANCE_PERIOD_STATUS_LABELS[known] : status}
    </Badge>
  );
}
