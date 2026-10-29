"use client"

import * as React from "react"

import { cn } from "@/lib/utils"

/** True when the table is wider than the scrollport, with a 1px tolerance for borders. */
export function tableNeedsHorizontalScroll(scrollWidth: number, clientWidth: number): boolean {
  return scrollWidth > clientWidth + 1
}

/**
 * Enterprise Data Table Primitives
 * Standardized single-border table container, toolbar, header, and cell density
 * per docs/design/01_Design_System.md.
 */

const TableContainer = React.forwardRef<
  HTMLDivElement,
  React.HTMLAttributes<HTMLDivElement>
>(({ className, ...props }, ref) => (
  <div
    ref={ref}
    className={cn(
      "overflow-hidden rounded-lg border border-border bg-surface",
      className
    )}
    {...props}
  />
))
TableContainer.displayName = "TableContainer"

const TableToolbar = React.forwardRef<
  HTMLDivElement,
  React.HTMLAttributes<HTMLDivElement>
>(({ className, ...props }, ref) => (
  <div
    ref={ref}
    className={cn(
      "flex flex-wrap items-center justify-between gap-3 border-b border-border bg-surface px-4 py-3",
      className
    )}
    {...props}
  />
))
TableToolbar.displayName = "TableToolbar"

/**
 * Scrollport for a wide table. The hint is only rendered when the content is
 * actually wider than the port, and it sits above the table so it does not
 * cover cells or intercept clicks. The port itself is a tab stop only then,
 * so keyboard users can reach and scroll it.
 */
export function HorizontalScroll({
  children,
  className,
  label = "Scrollable table",
}: {
  children: React.ReactNode
  className?: string
  label?: string
}) {
  const scrollerRef = React.useRef<HTMLDivElement>(null)
  const hintId = React.useId()
  const [overflowing, setOverflowing] = React.useState(false)

  React.useEffect(() => {
    const scroller = scrollerRef.current
    if (!scroller) return
    const measure = () => {
      setOverflowing(tableNeedsHorizontalScroll(scroller.scrollWidth, scroller.clientWidth))
    }
    measure()
    if (typeof ResizeObserver === "undefined") return
    const observer = new ResizeObserver(measure)
    observer.observe(scroller)
    for (const child of Array.from(scroller.children)) observer.observe(child)
    return () => observer.disconnect()
  }, [])

  return (
    <div className={cn("min-w-0", className)}>
      {overflowing ? (
        <p id={hintId} className="border-b border-border px-4 py-1.5 text-xs text-foreground-muted">
          Scroll horizontally to see more columns
        </p>
      ) : null}
      <div
        ref={scrollerRef}
        tabIndex={overflowing ? 0 : undefined}
        role={overflowing ? "region" : undefined}
        aria-label={overflowing ? label : undefined}
        aria-describedby={overflowing ? hintId : undefined}
        className="relative w-full min-w-0 overflow-x-auto focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      >
        {children}
      </div>
    </div>
  )
}

const Table = React.forwardRef<
  HTMLTableElement,
  React.TableHTMLAttributes<HTMLTableElement>
>(({ className, ...props }, ref) => (
  <HorizontalScroll>
    <table
      ref={ref}
      className={cn("w-full caption-bottom border-collapse text-sm", className)}
      {...props}
    />
  </HorizontalScroll>
))
Table.displayName = "Table"

const TableHeader = React.forwardRef<
  HTMLTableSectionElement,
  React.HTMLAttributes<HTMLTableSectionElement>
>(({ className, ...props }, ref) => (
  <thead
    ref={ref}
    className={cn(
      "border-b border-border bg-surface-secondary text-xs font-semibold uppercase tracking-wider text-foreground-secondary [&_tr]:border-b",
      className
    )}
    {...props}
  />
))
TableHeader.displayName = "TableHeader"

const TableBody = React.forwardRef<
  HTMLTableSectionElement,
  React.HTMLAttributes<HTMLTableSectionElement>
>(({ className, ...props }, ref) => (
  <tbody
    ref={ref}
    className={cn("divide-y divide-border [&_tr:last-child]:border-0", className)}
    {...props}
  />
))
TableBody.displayName = "TableBody"

const TableFooter = React.forwardRef<
  HTMLTableSectionElement,
  React.HTMLAttributes<HTMLTableSectionElement>
>(({ className, ...props }, ref) => (
  <tfoot
    ref={ref}
    className={cn(
      "border-t border-border bg-surface-secondary font-medium [&>tr]:last:border-b-0",
      className
    )}
    {...props}
  />
))
TableFooter.displayName = "TableFooter"

const TableRow = React.forwardRef<
  HTMLTableRowElement,
  React.HTMLAttributes<HTMLTableRowElement>
>(({ className, ...props }, ref) => (
  <tr
    ref={ref}
    className={cn(
      "border-b border-border transition-colors duration-motion-instant hover:bg-muted/50 data-[state=selected]:bg-primary-subtle/50",
      className
    )}
    {...props}
  />
))
TableRow.displayName = "TableRow"

interface TableHeadProps extends React.ThHTMLAttributes<HTMLTableCellElement> {
  align?: "left" | "center" | "right"
}

const TableHead = React.forwardRef<HTMLTableCellElement, TableHeadProps>(
  ({ className, align = "left", ...props }, ref) => (
    <th
      ref={ref}
      scope="col"
      className={cn(
        "h-9 px-4 py-2 align-middle text-xs font-semibold uppercase tracking-wider text-foreground-muted",
        align === "right" && "text-right",
        align === "center" && "text-center",
        align === "left" && "text-left",
        className
      )}
      {...props}
    />
  )
)
TableHead.displayName = "TableHead"

interface TableCellProps extends React.TdHTMLAttributes<HTMLTableCellElement> {
  align?: "left" | "center" | "right"
  numeric?: boolean
}

const TableCell = React.forwardRef<HTMLTableCellElement, TableCellProps>(
  ({ className, align = "left", numeric = false, ...props }, ref) => (
    <td
      ref={ref}
      className={cn(
        "px-4 py-2.5 align-middle text-sm text-foreground",
        (align === "right" || numeric) && "text-right tabular-nums",
        align === "center" && "text-center",
        align === "left" && !numeric && "text-left",
        className
      )}
      {...props}
    />
  )
)
TableCell.displayName = "TableCell"

const TableCaption = React.forwardRef<
  HTMLTableCaptionElement,
  React.HTMLAttributes<HTMLTableCaptionElement>
>(({ className, ...props }, ref) => (
  <caption
    ref={ref}
    className={cn("mt-4 text-xs text-foreground-muted", className)}
    {...props}
  />
))
TableCaption.displayName = "TableCaption"

export {
  TableContainer,
  TableToolbar,
  Table,
  TableHeader,
  TableBody,
  TableFooter,
  TableHead,
  TableRow,
  TableCell,
  TableCaption,
}
