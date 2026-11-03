import { cn } from "@/lib/utils";

export interface ScopeOption<T extends string> {
  value: T;
  label: string;
  /** False leaves the option out (the caller's permission or record decides). Defaults to shown. */
  show?: boolean;
}

/** The "My … / Team … / Decision center" switch at the top of the leave, overtime and regularization
 * pages. The caller says which options exist for this user; a switch with a single option is not
 * drawn at all, since there is nothing to switch between. */
export function ScopeTabs<T extends string>({
  label,
  options,
  value,
  onChange,
}: {
  label: string;
  options: ScopeOption<T>[];
  value: T;
  onChange: (next: T) => void;
}) {
  const shown = options.filter((o) => o.show !== false);
  if (shown.length < 2) return null;
  return (
    <div role="group" aria-label={label} className="inline-flex rounded-md border border-border bg-surface p-0.5">
      {shown.map((o) => (
        <button
          key={o.value}
          type="button"
          aria-pressed={value === o.value}
          onClick={() => onChange(o.value)}
          className={cn(
            "rounded-sm px-3 py-1.5 text-xs font-medium transition-colors",
            value === o.value
              ? "bg-primary text-on-primary"
              : "text-foreground-secondary hover:bg-muted hover:text-foreground",
          )}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}
