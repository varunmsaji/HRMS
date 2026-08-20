import { Badge, type BadgeProps } from "@/components/ui/badge";
import { REGULARIZATION_STATUS_LABELS, type RegularizationStatus } from "@/lib/regularization/types";

const STATUS_VARIANT: Record<RegularizationStatus, NonNullable<BadgeProps["variant"]>> = {
  SUBMITTED: "warning",
  APPROVED: "success",
  REJECTED: "danger",
  CANCELLED: "outline",
};

interface RegularizationStatusBadgeProps {
  status: string;
}

/** Mirrors `AttendanceStatusBadge` — falls back to a plain outline badge for any value outside
 * the known set rather than throwing. */
export function RegularizationStatusBadge({ status }: RegularizationStatusBadgeProps) {
  const known = status in STATUS_VARIANT ? (status as RegularizationStatus) : null;
  return (
    <Badge variant={known ? STATUS_VARIANT[known] : "outline"}>
      {known ? REGULARIZATION_STATUS_LABELS[known] : status}
    </Badge>
  );
}
