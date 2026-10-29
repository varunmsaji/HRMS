import * as React from "react"

import { cn } from "@/lib/utils"

const Input = React.forwardRef<HTMLInputElement, React.ComponentProps<"input">>(
  ({ className, type, ...props }, ref) => {
    return (
      <input
        type={type}
        className={cn(
          "flex h-9 w-full rounded-md border border-border bg-surface px-3 py-1.5 text-sm text-foreground transition-colors duration-motion-instant file:border-0 file:bg-transparent file:text-sm file:font-medium file:text-foreground placeholder:text-foreground-disabled hover:border-border-strong focus-visible:border-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/20 aria-[invalid=true]:border-danger aria-[invalid=true]:focus-visible:ring-danger/20 disabled:cursor-not-allowed disabled:bg-surface-secondary disabled:opacity-60",
          className
        )}
        ref={ref}
        {...props}
      />
    )
  }
)
Input.displayName = "Input"

export { Input }
