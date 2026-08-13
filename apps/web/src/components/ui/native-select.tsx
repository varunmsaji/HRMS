import * as React from "react"

import { cn } from "@/lib/utils"

/**
 * No Radix-based Select is scaffolded in this project yet (only the primitives in
 * components.json's original shadcn install). A handful of registration fields
 * (country, timezone, fiscal-year month, company size) need a real <select> for
 * correct keyboard/screen-reader behavior without pulling in a new dependency —
 * styled to match Input so it reads as the same design system.
 */
const NativeSelect = React.forwardRef<HTMLSelectElement, React.ComponentProps<"select">>(
  ({ className, children, ...props }, ref) => (
    <select
      ref={ref}
      className={cn(
        "flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-base shadow-sm transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50 md:text-sm",
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
