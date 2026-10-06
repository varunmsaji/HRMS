import type { LucideIcon } from "lucide-react";
import type { ReactNode } from "react";

import { EmptyState } from "@/components/common/empty-state";
import { ErrorState } from "@/components/common/error-state";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import type { ApiError } from "@/lib/api/errors";
import { cn } from "@/lib/utils";

interface SectionCardProps {
  id?: string;
  title: string;
  description?: string;
  actions?: ReactNode;
  status: "idle" | "loading" | "ready" | "error";
  error?: ApiError | null;
  onRetry?: () => void;
  /** Shown instead of the children when the section loaded but has nothing to show. */
  empty?: { title: string; description?: string; icon?: LucideIcon } | null;
  /** Shown when the section can't be requested at all (e.g. a missing permission). */
  unavailable?: string | null;
  className?: string;
  children?: ReactNode;
}

/** The dashboard's one section frame: heading + loading / empty / error / ready. A permission
 * error is kept distinct from a failure (and from "no data"); raw backend messages are never
 * shown. */
export function SectionCard({
  id,
  title,
  description,
  actions,
  status,
  error,
  onRetry,
  empty,
  unavailable,
  className,
  children,
}: SectionCardProps) {
  const headingId = id ? `${id}-heading` : undefined;
  return (
    <Card id={id} className={className} aria-labelledby={headingId}>
      <CardContent className="space-y-4 pt-5">
        <div className="flex flex-wrap items-start justify-between gap-2">
          <div className="min-w-0">
            <h2 id={headingId} className="text-md font-semibold text-foreground">
              {title}
            </h2>
            {description ? <p className="mt-0.5 text-xs text-foreground-secondary">{description}</p> : null}
          </div>
          {actions ? <div className="flex shrink-0 items-center gap-2">{actions}</div> : null}
        </div>
        {unavailable ? (
          <p className="rounded-md border border-dashed border-border px-4 py-6 text-center text-sm text-foreground-secondary">
            {unavailable}
          </p>
        ) : status === "loading" || status === "idle" ? (
          <div role="status" aria-label={`Loading ${title}`} className="space-y-2">
            <Skeleton className="h-4 w-1/3" />
            <Skeleton className="h-24 w-full" />
          </div>
        ) : status === "error" ? (
          <ErrorState
            title={error?.status === 403 ? "No access" : `Couldn't load ${title.toLowerCase()}`}
            message={
              error?.status === 403
                ? "You do not have permission to view this section."
                : "This section failed to load. The rest of the dashboard is unaffected."
            }
            onRetry={error?.status === 403 ? undefined : onRetry}
          />
        ) : empty ? (
          <EmptyState icon={empty.icon} title={empty.title} description={empty.description} className="py-8" />
        ) : (
          <div className={cn("space-y-4")}>{children}</div>
        )}
      </CardContent>
    </Card>
  );
}
