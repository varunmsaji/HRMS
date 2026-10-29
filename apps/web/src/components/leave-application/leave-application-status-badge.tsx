import { Badge, type BadgeProps } from "@/components/ui/badge";
import {
  LEAVE_APPLICATION_STATUS_LABELS,
  type LeaveApplicationStatus,
} from "@/lib/leave-application/types";

const STATUS_VARIANT: Record<LeaveApplicationStatus, NonNullable<BadgeProps["variant"]>> = {
  SUBMITTED: "warning",
  APPROVED: "success",
  REJECTED: "danger",
  CANCELLED: "outline",
};

interface LeaveApplicationStatusBadgeProps {
  status: string;
}

/** Mirrors `RegularizationStatusBadge` — falls back to a plain outline badge for any value
 * outside the known set rather than throwing. */
export function LeaveApplicationStatusBadge({ status }: LeaveApplicationStatusBadgeProps) {
  const known = status in STATUS_VARIANT ? (status as LeaveApplicationStatus) : null;
  return (
    <Badge variant={known ? STATUS_VARIANT[known] : "outline"} dot>
      {known ? LEAVE_APPLICATION_STATUS_LABELS[known] : status}
    </Badge>
  );
}
