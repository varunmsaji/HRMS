import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

interface CollapseProps {
  open: boolean;
  children: ReactNode;
  className?: string;
}

/** Expands and collapses its content smoothly, whatever its height, without measuring anything in
 * JavaScript: a one-row grid animates between `0fr` and `1fr`. Collapsed content stays mounted but
 * is `invisible` (out of the tab order, hidden from screen readers) once the animation ends, and
 * the animation is skipped for users who prefer reduced motion. */
export function Collapse({ open, children, className }: CollapseProps) {
  return (
    <div
      aria-hidden={open ? undefined : true}
      className={cn(
        "grid transition-[grid-template-rows,opacity,visibility] duration-motion-base ease-out motion-reduce:transition-none",
        open ? "visible grid-rows-[1fr] opacity-100" : "invisible grid-rows-[0fr] opacity-0",
        className,
      )}
    >
      {/* Negative margin + padding so focus rings on the content aren't clipped by overflow-hidden. */}
      <div className="-m-1 min-h-0 overflow-hidden p-1">{children}</div>
    </div>
  );
}
