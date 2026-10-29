import { ShieldAlert, TriangleAlert } from "lucide-react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

interface ErrorStateProps {
  title?: string;
  message: string;
  onRetry?: () => void;
  className?: string;
}

export function ErrorState({
  title,
  message,
  onRetry,
  className,
}: ErrorStateProps) {
  const isPermissionError =
    /permission|no access|forbidden/i.test(message) ||
    (title ? /permission|no access/i.test(title) : false);

  const resolvedTitle =
    title ?? (isPermissionError ? "Access restricted" : "Something went wrong");
  const Icon = isPermissionError ? ShieldAlert : TriangleAlert;

  return (
    <div
      role="alert"
      className={cn(
        "flex flex-col items-center gap-3 rounded-lg border px-6 py-8 text-center",
        isPermissionError
          ? "border-warning-border bg-warning-subtle/60"
          : "border-danger-border bg-danger-subtle/60",
        className,
      )}
    >
      <div
        className={cn(
          "flex h-9 w-9 items-center justify-center rounded-md border bg-surface",
          isPermissionError
            ? "border-warning-border text-warning"
            : "border-danger-border text-danger",
        )}
      >
        <Icon className="h-4 w-4" aria-hidden="true" />
      </div>
      <div className="max-w-md space-y-1">
        <p className="text-sm font-semibold text-foreground">{resolvedTitle}</p>
        <p className="text-xs leading-relaxed text-foreground-secondary">{message}</p>
      </div>
      {onRetry ? (
        <Button variant="outline" size="sm" onClick={onRetry} className="mt-1">
          Try again
        </Button>
      ) : null}
    </div>
  );
}
