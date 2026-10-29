import { Badge } from "@/components/ui/badge";
import { PAY_RUN_STATUS_LABELS, type PayRunStatus } from "@/lib/payroll/types";

const VARIANTS: Record<PayRunStatus, "outline" | "info" | "warning" | "success" | "secondary"> = {
  DRAFT: "outline",
  INPUTS_LOCKED: "info",
  COMPUTED: "warning",
  APPROVED: "info",
  FINALISED: "success",
  PAID: "secondary",
};

export function PayRunStatusBadge({ status }: { status: PayRunStatus }) {
  return (
    <Badge variant={VARIANTS[status]} dot>
      {PAY_RUN_STATUS_LABELS[status]}
    </Badge>
  );
}
