import * as React from "react"
import { cva, type VariantProps } from "class-variance-authority"

import { cn } from "@/lib/utils"

const badgeVariants = cva(
  "inline-flex items-center gap-1.5 rounded-sm border px-2 py-0.5 text-xs font-medium leading-4 transition-colors focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-1",
  {
    variants: {
      variant: {
        default:
          "border-primary-border bg-primary-subtle text-primary",
        secondary:
          "border-border bg-muted text-foreground-secondary",
        destructive:
          "border-danger-border bg-danger-subtle text-danger",
        outline:
          "border-border bg-surface text-foreground-secondary",
        success:
          "border-success-border bg-success-subtle text-success",
        warning:
          "border-warning-border bg-warning-subtle text-warning",
        danger:
          "border-danger-border bg-danger-subtle text-danger",
        info:
          "border-info-border bg-info-subtle text-info",
        "on-leave":
          "border-on-leave-border bg-on-leave-subtle text-on-leave",
        holiday:
          "border-holiday-border bg-holiday-subtle text-holiday",
        "half-day":
          "border-half-day-border bg-half-day-subtle text-half-day",
        wfh:
          "border-wfh-border bg-wfh-subtle text-wfh",
      },
    },
    defaultVariants: {
      variant: "default",
    },
  }
)

export interface BadgeProps
  extends React.HTMLAttributes<HTMLSpanElement>,
    VariantProps<typeof badgeVariants> {
  dot?: boolean
}

function Badge({ className, variant, dot = false, children, ...props }: BadgeProps) {
  return (
    <span className={cn(badgeVariants({ variant }), className)} {...props}>
      {dot ? (
        <span
          aria-hidden="true"
          className="h-1.5 w-1.5 shrink-0 rounded-full bg-current"
        />
      ) : null}
      {children}
    </span>
  )
}

export { Badge, badgeVariants }
