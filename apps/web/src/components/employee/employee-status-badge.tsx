import { Badge, type BadgeProps } from "@/components/ui/badge";
import type { EmployeeStatus } from "@/lib/employee/types";

const STATUS_VARIANT: Record<EmployeeStatus, NonNullable<BadgeProps["variant"]>> = {
  PRE_JOINING: "info",
  PROBATION: "warning",
  ACTIVE: "success",
  ON_NOTICE: "warning",
  SUSPENDED: "danger",
  ON_LONG_LEAVE: "on-leave",
  EXITED: "outline",
  ABSCONDING: "danger",
  RETIRED: "outline",
  DECEASED: "outline",
};

const STATUS_LABEL: Record<EmployeeStatus, string> = {
  PRE_JOINING: "Pre-joining",
  PROBATION: "Probation",
  ACTIVE: "Active",
  ON_NOTICE: "On notice",
  SUSPENDED: "Suspended",
  ON_LONG_LEAVE: "On long leave",
  EXITED: "Exited",
  ABSCONDING: "Absconding",
  RETIRED: "Retired",
  DECEASED: "Deceased",
};

interface EmployeeStatusBadgeProps {
  status: string;
}

/** `Employee.status` is FR-EMP-014's fixed 10-value enum (`lib/employee/types.ts`) — falls
 * back to a plain outline badge for any value outside that set rather than throwing, since the
 * frontend must not assume the backend's own set can never grow. */
export function EmployeeStatusBadge({ status }: EmployeeStatusBadgeProps) {
  const known = status in STATUS_VARIANT ? (status as EmployeeStatus) : null;
  return (
    <Badge variant={known ? STATUS_VARIANT[known] : "outline"}>{known ? STATUS_LABEL[known] : status}</Badge>
  );
}
