import type { PaginationMeta } from "@/lib/api/types";
import { Button } from "@/components/ui/button";

interface PaginationControlsProps {
  pagination: PaginationMeta;
  onPageChange: (page: number) => void;
  disabled?: boolean;
}

/** API-01 pagination footer — "Showing X–Y of Z" + Previous/Next, driven by the backend's
 * `PaginationMeta` (`page`/`per_page`/`total`/`total_pages`). Renders nothing for a single page
 * with no rows, since there's nothing to page through. */
export function PaginationControls({ pagination, onPageChange, disabled }: PaginationControlsProps) {
  const { page, per_page, total, total_pages } = pagination;
  if (total === 0 && total_pages <= 1) return null;

  const rangeStart = total === 0 ? 0 : (page - 1) * per_page + 1;
  const rangeEnd = Math.min(page * per_page, total);

  return (
    <div className="flex items-center justify-between border-t border-border px-0 py-3 text-sm text-foreground-secondary">
      <span>
        Showing {rangeStart}–{rangeEnd} of {total}
      </span>
      <div className="flex items-center gap-2">
        <Button
          type="button"
          variant="outline"
          size="sm"
          disabled={disabled || page <= 1}
          onClick={() => onPageChange(page - 1)}
        >
          Previous
        </Button>
        <span className="px-1 text-xs text-foreground-muted">
          Page {page} of {Math.max(total_pages, 1)}
        </span>
        <Button
          type="button"
          variant="outline"
          size="sm"
          disabled={disabled || page >= total_pages}
          onClick={() => onPageChange(page + 1)}
        >
          Next
        </Button>
      </div>
    </div>
  );
}
