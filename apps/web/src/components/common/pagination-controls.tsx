import type { PaginationMeta } from "@/lib/api/types";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

interface PaginationControlsProps {
  pagination: PaginationMeta;
  onPageChange: (page: number) => void;
  disabled?: boolean;
  className?: string;
}

/** API-01 pagination footer — "Showing X–Y of Z" + Previous/Next, driven by the backend's
 * `PaginationMeta` (`page`/`per_page`/`total`/`total_pages`). Renders nothing for a single page
 * with no rows, since there's nothing to page through. */
export function PaginationControls({
  pagination,
  onPageChange,
  disabled,
  className,
}: PaginationControlsProps) {
  const { page, per_page, total, total_pages } = pagination;
  if (total === 0 && total_pages <= 1) return null;

  const rangeStart = total === 0 ? 0 : (page - 1) * per_page + 1;
  const rangeEnd = Math.min(page * per_page, total);

  return (
    <div
      className={cn(
        "flex flex-wrap items-center justify-between gap-3 border-t border-border px-4 py-3 text-xs text-foreground-secondary",
        className,
      )}
    >
      <span className="tabular-nums">
        Showing <strong className="font-medium text-foreground">{rangeStart}</strong>–
        <strong className="font-medium text-foreground">{rangeEnd}</strong> of{" "}
        <strong className="font-medium text-foreground">{total}</strong>
      </span>
      <div className="flex items-center gap-2">
        <Button
          type="button"
          variant="outline"
          size="xs"
          disabled={disabled || page <= 1}
          onClick={() => onPageChange(page - 1)}
        >
          Previous
        </Button>
        <span className="px-1.5 text-xs tabular-nums text-foreground-muted">
          Page {page} of {Math.max(total_pages, 1)}
        </span>
        <Button
          type="button"
          variant="outline"
          size="xs"
          disabled={disabled || page >= total_pages}
          onClick={() => onPageChange(page + 1)}
        >
          Next
        </Button>
      </div>
    </div>
  );
}
