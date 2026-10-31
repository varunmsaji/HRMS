import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

interface BusyRegionProps {
  busy: boolean;
  /** Announced to assistive technology while refreshing. */
  label?: string;
  className?: string;
  children: ReactNode;
}

/** Keeps the previous content on screen while a refresh (next page, re-filter, reload) is in
 * flight — dimmed and non-interactive, so rows can't be acted on while they are about to be
 * replaced — instead of swapping it for a spinner and collapsing the layout. Use a skeleton or
 * spinner only for the very first load, when there is nothing to keep. */
export function BusyRegion({
  busy,
  label = "Refreshing…",
  className,
  children,
}: BusyRegionProps) {
  return (
    <div
      aria-busy={busy || undefined}
      className={cn(
        "transition-opacity duration-motion-fast",
        busy && "pointer-events-none opacity-60",
        className,
      )}
    >
      {busy ? (
        <span role="status" className="sr-only">
          {label}
        </span>
      ) : null}
      {children}
    </div>
  );
}
