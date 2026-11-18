import type { LucideIcon } from "lucide-react";

import { cn } from "@/lib/utils";

export type TileAccent =
  "success" | "danger" | "warning" | "primary" | "info" | "leave" | "holiday";

const TILE_ACCENTS: Record<TileAccent, { chip: string; bar: string }> = {
  success: { chip: "bg-success-subtle text-success", bar: "bg-success" },
  danger: { chip: "bg-danger-subtle text-danger", bar: "bg-danger" },
  warning: { chip: "bg-warning-subtle text-warning", bar: "bg-warning" },
  primary: { chip: "bg-primary-subtle text-primary", bar: "bg-primary" },
  info: { chip: "bg-info-subtle text-info", bar: "bg-info" },
  leave: { chip: "bg-on-leave-subtle text-on-leave", bar: "bg-on-leave" },
  holiday: { chip: "bg-holiday-subtle text-holiday", bar: "bg-holiday" },
};

export interface StatTileProps {
  label: string;
  value: string;
  hint?: string;
  tone?: string;
  icon: LucideIcon;
  accent: TileAccent;
  progress?: number | null;
  showPercent?: boolean;
}

/** One attendance figure (employee month view, employee insights): a tinted icon chip and label, the value, a hint, and an optional bar for
 * figures that are a share of something (days worked of expected, punctuality). The label stays
 * the `dt` text and the value its next sibling so screen readers and tests read them as a pair. */
export function StatTile({
  label,
  value,
  hint,
  tone,
  icon: Icon,
  accent,
  progress,
  showPercent = true,
}: StatTileProps) {
  const a = TILE_ACCENTS[accent];
  const pct =
    progress == null ? null : Math.max(0, Math.min(100, Math.round(progress)));
  return (
    <div className="flex min-w-0 flex-col rounded-xl border border-border-subtle bg-surface p-4 shadow-sm transition-shadow hover:shadow-md">
      <dt className="flex min-w-0 items-center gap-2.5 text-sm font-medium leading-snug text-foreground-secondary">
        <span
          aria-hidden="true"
          className={cn(
            "grid h-9 w-9 shrink-0 place-items-center rounded-lg",
            a.chip,
          )}
        >
          <Icon className="h-[18px] w-[18px]" />
        </span>
        {label}
      </dt>
      <dd
        className={cn(
          "mt-3 text-xl font-semibold leading-tight tracking-tight tabular-nums break-words text-foreground sm:text-2xl",
          tone,
        )}
      >
        {value}
      </dd>
      {hint ? (
        <p className="mt-0.5 truncate text-xs text-foreground-muted">{hint}</p>
      ) : null}
      {pct !== null ? (
        <div
          className="mt-auto flex items-center gap-2 pt-3"
          aria-hidden="true"
        >
          <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-muted">
            <div
              className={cn("h-full rounded-full transition-[width]", a.bar)}
              style={{ width: `${pct}%` }}
            />
          </div>
          {showPercent ? (
            <span className="text-xs font-medium tabular-nums text-foreground-muted">
              {pct}%
            </span>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
