import { Button } from "@/components/ui/button";

interface ConcurrencyConflictBannerProps {
  message: string;
  onReload: () => void;
  onCancel: () => void;
  reloading?: boolean;
}

/** Shared `409 STALE_RESOURCE` banner — mirrors the pattern already proven in
 * `app/app/legal-entities/[id]/page.tsx`, extracted here since every effective-dated Employee
 * sub-resource (Assignment/Compensation/Statutory/Bank) plus the Employee identity edit itself
 * needs the identical "reload latest / cancel" recovery flow. */
export function ConcurrencyConflictBanner({
  message,
  onReload,
  onCancel,
  reloading,
}: ConcurrencyConflictBannerProps) {
  return (
    <div className="mb-4 rounded-md border border-warning/30 bg-warning/5 p-4" role="alert">
      <p className="text-sm font-medium text-foreground">{message}</p>
      <div className="mt-3 flex flex-wrap gap-2">
        <Button type="button" size="sm" onClick={onReload} disabled={reloading}>
          {reloading ? "Reloading…" : "Reload latest"}
        </Button>
        <Button type="button" size="sm" variant="outline" onClick={onCancel} disabled={reloading}>
          Cancel current changes
        </Button>
      </div>
    </div>
  );
}
