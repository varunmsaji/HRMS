"use client"

import * as React from "react"
import Link from "next/link"
import { ChevronRight } from "lucide-react"

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
      "overflow-hidden rounded-xl border border-border bg-surface shadow-elevation-1",
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
      "border-b border-border bg-surface-secondary/70 [&_tr]:border-b",
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
      "group/row border-b border-border-subtle transition-colors duration-motion-instant hover:bg-primary-subtle/40 data-[state=selected]:bg-primary-subtle/60",
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
        "h-10 whitespace-nowrap px-3 py-2 align-middle text-2xs font-semibold uppercase tracking-wider text-foreground-muted first:pl-5 last:pr-5",
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
  /** Keep the content on one line (codes, dates, badges, short names). Long free text should wrap. */
  nowrap?: boolean
}

const TableCell = React.forwardRef<HTMLTableCellElement, TableCellProps>(
  ({ className, align = "left", numeric = false, nowrap = false, ...props }, ref) => (
    <td
      ref={ref}
      className={cn(
        "px-3 py-3 align-middle text-sm text-foreground first:pl-5 last:pr-5",
        nowrap && "whitespace-nowrap",
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

/**
 * Two-line cell: a primary value with a quieter secondary line beneath it
 * (e.g. designation over department). Gives a column hierarchy instead of one flat string.
 */
function TableCellStack({
  primary,
  secondary,
  className,
}: {
  primary: React.ReactNode
  secondary?: React.ReactNode
  className?: string
}) {
  return (
    <div className={cn("min-w-0", className)}>
      <div className="truncate text-sm font-medium text-foreground">{primary}</div>
      {secondary ? <div className="mt-0.5 truncate text-xs text-foreground-muted">{secondary}</div> : null}
    </div>
  )
}

/** Identifier such as an employee or policy code: monospace, quiet, never wraps. */
function TableCode({ children, className }: { children: React.ReactNode; className?: string }) {
  return (
    <span
      className={cn(
        "inline-block whitespace-nowrap rounded-sm bg-muted px-1.5 py-0.5 font-mono text-2xs font-medium tracking-tight text-foreground-secondary",
        className
      )}
    >
      {children}
    </span>
  )
}

/** Placeholder for a missing value — visibly quiet, and announced as "none" to screen readers. */
function TableEmpty({ label = "None" }: { label?: string }) {
  return (
    <span className="text-foreground-disabled">
      <span aria-hidden="true">—</span>
      <span className="sr-only">{label}</span>
    </span>
  )
}

/** Row-end action link ("View", "Open"): a small pill with a chevron that picks up the row hover. */
function TableRowAction({
  href,
  children = "View",
  className,
}: {
  href: string
  children?: React.ReactNode
  className?: string
}) {
  return (
    <Link
      href={href}
      className={cn(
        "inline-flex items-center gap-0.5 rounded-md px-2 py-1 text-xs font-medium text-primary transition-colors hover:bg-primary-subtle focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
        className
      )}
    >
      {children}
      <ChevronRight className="h-3.5 w-3.5 transition-transform duration-motion-fast group-hover/row:translate-x-0.5" aria-hidden="true" />
    </Link>
  )
}

/** Row-end action that opens a dialog or runs in place (so no chevron): same pill as TableRowAction. */
function TableRowActionButton({
  className,
  type = "button",
  ...props
}: React.ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button
      type={type}
      className={cn(
        "inline-flex items-center rounded-md px-2 py-1 text-xs font-medium text-primary transition-colors hover:bg-primary-subtle focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:pointer-events-none disabled:opacity-50",
        className
      )}
      {...props}
    />
  )
}

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
  TableCellStack,
  TableCode,
  TableEmpty,
  TableRowAction,
  TableRowActionButton,
}
