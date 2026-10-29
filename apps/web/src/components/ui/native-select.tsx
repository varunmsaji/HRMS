import * as React from "react"

import { cn } from "@/lib/utils"

/**
 * Native `<select>` styled to match `Input` across light/dark themes, keyboard
 * navigation, and validation states (`aria-invalid`).
 */
const NativeSelect = React.forwardRef<HTMLSelectElement, React.ComponentProps<"select">>(
  ({ className, children, ...props }, ref) => (
    <select
      ref={ref}
      className={cn(
        "flex h-9 w-full rounded-md border border-border bg-surface px-3 py-1.5 text-sm text-foreground transition-colors duration-motion-instant hover:border-border-strong focus-visible:border-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/20 aria-[invalid=true]:border-danger aria-[invalid=true]:focus-visible:ring-danger/20 disabled:cursor-not-allowed disabled:bg-surface-secondary disabled:opacity-60",
        className
      )}
      {...props}
    >
      {children}
    </select>
  )
)
NativeSelect.displayName = "NativeSelect"

export { NativeSelect }
