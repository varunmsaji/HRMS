import { cn } from "@/lib/utils"

function Skeleton({
  className,
  ...props
}: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn("animate-pulse rounded-sm bg-muted", className)}
      {...props}
    />
  )
}

function TableSkeleton({
  rows = 5,
  columns = 5,
  className,
}: {
  rows?: number
  columns?: number
  className?: string
}) {
  return (
    <div className={cn("w-full space-y-2 p-4", className)} aria-hidden="true">
      <div className="grid gap-4 border-b border-border pb-2.5" style={{ gridTemplateColumns: `repeat(${columns}, minmax(0, 1fr))` }}>
        {Array.from({ length: columns }).map((_, idx) => (
          <Skeleton key={idx} className="h-3.5 w-2/3" />
        ))}
      </div>
      {Array.from({ length: rows }).map((_, rowIdx) => (
        <div
          key={rowIdx}
          className="grid gap-4 border-b border-border/50 py-2.5 last:border-0"
          style={{ gridTemplateColumns: `repeat(${columns}, minmax(0, 1fr))` }}
        >
          {Array.from({ length: columns }).map((__, colIdx) => (
            <Skeleton key={colIdx} className={colIdx === 0 ? "h-4 w-4/5" : "h-4 w-3/5"} />
          ))}
        </div>
      ))}
    </div>
  )
}

export { Skeleton, TableSkeleton }
