import { Badge } from "@/components/ui/badge";
import type { CompanyStatus } from "@/lib/platform/api";

const VARIANT: Record<CompanyStatus, "warning" | "info" | "success" | "danger" | "secondary"> = {
  PENDING_APPROVAL: "warning",
  TRIAL: "info",
  ACTIVE: "success",
  SUSPENDED: "warning",
  REJECTED: "danger",
  TERMINATED: "secondary",
};

export function StatusBadge({ status }: { status: CompanyStatus }) {
  return (
    <Badge variant={VARIANT[status]} dot>
      {status.replace("_", " ")}
    </Badge>
  );
}
