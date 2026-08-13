import { Clock } from "lucide-react";

import { EmptyState } from "@/components/common/empty-state";

interface BackendPendingNoticeProps {
  dependency: string;
  title?: string;
  description?: string;
}

/** Honest "not built yet" state for screens wired to a real, documented API contract whose
 * backend endpoint hasn't shipped (see docs/modules/company/07_Implementation_Backlog.md) —
 * never fabricated data, never a silent success. */
export function BackendPendingNotice({ dependency, title = "Not available yet", description }: BackendPendingNoticeProps) {
  return (
    <EmptyState
      icon={Clock}
      title={title}
      description={
        description ??
        `This screen is wired to the real API contract, but the backend endpoint (${dependency}) hasn't shipped yet.`
      }
    />
  );
}
