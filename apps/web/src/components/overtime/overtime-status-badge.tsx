import { Badge, type BadgeProps } from "@/components/ui/badge";
import { OVERTIME_STATUS_LABELS, type OvertimeStatus } from "@/lib/overtime/types";

const STATUS_VARIANT: Record<OvertimeStatus, NonNullable<BadgeProps["variant"]>> = {
  PENDING: "warning",
  AUTO_APPROVED: "success",
  APPROVED: "success",
  REJECTED: "danger",
};

interface OvertimeStatusBadgeProps {
  status: string;
}

/** Mirrors `RegularizationStatusBadge` — falls back to a plain outline badge for any value
 * outside the known set rather than throwing. */
export function OvertimeStatusBadge({ status }: OvertimeStatusBadgeProps) {
  const known = status in STATUS_VARIANT ? (status as OvertimeStatus) : null;
  return (
    <Badge variant={known ? STATUS_VARIANT[known] : "outline"} dot>
      {known ? OVERTIME_STATUS_LABELS[known] : status}
    </Badge>
  );
}
