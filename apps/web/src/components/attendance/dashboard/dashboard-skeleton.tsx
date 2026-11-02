import { Skeleton } from "@/components/ui/skeleton";

/** What the attendance dashboard looks like while its first data loads: the same tabs, pulse card,
 * KPI tiles and Needs attention card in the same places, so nothing jumps when the real content
 * arrives. Announced once to screen readers; the grey shapes are decoration. */
export function AttendanceDashboardSkeleton() {
  return (
    <div role="status" aria-label="Loading attendance" className="space-y-6">
      <span className="sr-only">Loading attendance…</span>
      <div aria-hidden="true" className="space-y-6">
        <div className="flex gap-4 border-b border-border pb-2.5">
          {[16, 14, 14, 28].map((w, i) => (
            <Skeleton key={i} className="h-4" style={{ width: `${w * 4}px` }} />
          ))}
        </div>

        <div className="grid gap-6 rounded-xl border border-border bg-surface p-5 lg:grid-cols-[minmax(0,5fr)_minmax(0,7fr)] lg:gap-8">
          <div className="space-y-3">
            <Skeleton className="h-3 w-32" />
            <Skeleton className="h-10 w-40" />
            <Skeleton className="h-3 w-52" />
            <Skeleton className="h-16 w-full" />
          </div>
          <div className="space-y-3 self-center">
            <Skeleton className="h-3 w-24" />
            <Skeleton className="h-4 w-full rounded-full" />
            <div className="flex flex-wrap gap-2">
              {[24, 20, 28, 22, 26].map((w, i) => (
                <Skeleton key={i} className="h-8 rounded-full" style={{ width: `${w * 4}px` }} />
              ))}
            </div>
          </div>
        </div>

        <div className="grid grid-cols-2 gap-2.5 sm:grid-cols-3 xl:grid-cols-6">
          {Array.from({ length: 6 }).map((_, i) => (
            <div key={i} className="space-y-2 rounded-md border border-border bg-surface p-3.5">
              <Skeleton className="h-2.5 w-20" />
              <Skeleton className="h-6 w-12" />
              <Skeleton className="h-2.5 w-28" />
            </div>
          ))}
        </div>

        <div className="space-y-3 rounded-xl border border-border bg-surface p-5">
          <Skeleton className="h-4 w-36" />
          {Array.from({ length: 3 }).map((_, i) => (
            <div key={i} className="flex items-center gap-3">
              <Skeleton className="h-5 w-14 rounded-full" />
              <Skeleton className="h-4 flex-1" />
              <Skeleton className="h-7 w-20 rounded-md" />
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
