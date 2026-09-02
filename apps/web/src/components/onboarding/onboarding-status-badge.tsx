import { Badge, type BadgeProps } from "@/components/ui/badge";
import type { OnboardingCaseStatus } from "@/lib/onboarding/types";

const STATUS_VARIANT: Record<OnboardingCaseStatus, NonNullable<BadgeProps["variant"]>> = {
  DRAFT: "outline",
  INVITED: "info",
  IN_PROGRESS: "info",
  SUBMITTED: "warning",
  UNDER_REVIEW: "warning",
  CHANGES_REQUESTED: "danger",
  VERIFIED: "success",
  ACTIVATED: "success",
  EXPIRED: "outline",
  CANCELLED: "outline",
};

const STATUS_LABEL: Record<OnboardingCaseStatus, string> = {
  DRAFT: "Draft",
  INVITED: "Invited",
  IN_PROGRESS: "In progress",
  SUBMITTED: "Submitted",
  UNDER_REVIEW: "Under review",
  CHANGES_REQUESTED: "Changes requested",
  VERIFIED: "Verified",
  ACTIVATED: "Activated",
  EXPIRED: "Expired",
  CANCELLED: "Cancelled",
};

interface OnboardingStatusBadgeProps {
  status: string;
}

/** Falls back to a plain outline badge for any value outside the known set rather than
 * throwing, mirroring `EmployeeStatusBadge`'s own convention. */
export function OnboardingStatusBadge({ status }: OnboardingStatusBadgeProps) {
  const known = status in STATUS_VARIANT ? (status as OnboardingCaseStatus) : null;
  return (
    <Badge variant={known ? STATUS_VARIANT[known] : "outline"}>{known ? STATUS_LABEL[known] : status}</Badge>
  );
}
