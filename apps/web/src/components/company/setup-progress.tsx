import { CircleCheck } from "lucide-react";

import { cn } from "@/lib/utils";
import type { SetupStep } from "@/lib/company/types";

export function SetupProgress({ steps }: { steps: SetupStep[] }) {
  return (
    <ul className="divide-y divide-border">
      {steps.map((step) => (
        <li key={step.code} className="flex items-center justify-between gap-4 py-3">
          <span className="text-sm text-foreground">{step.label}</span>
          <span
            className={cn(
              "inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium",
              step.is_complete ? "bg-success-subtle text-success" : "bg-muted text-foreground-muted",
            )}
          >
            {step.is_complete ? <CircleCheck className="h-3 w-3" aria-hidden="true" /> : null}
            {step.is_complete ? "Complete" : "Pending"}
          </span>
        </li>
      ))}
    </ul>
  );
}
