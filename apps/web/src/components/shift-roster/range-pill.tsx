"use client";

import { CalendarDays, ChevronLeft, ChevronRight } from "lucide-react";

import { Button } from "@/components/ui/button";

/** The rounded "‹ 12 Jan – 18 Jan 2026 ›" control every roster view uses to move through time. */
export function RangePill({
  label,
  onPrev,
  onNext,
  prevLabel = "Previous",
  nextLabel = "Next",
}: {
  label: string;
  onPrev: () => void;
  onNext: () => void;
  prevLabel?: string;
  nextLabel?: string;
}) {
  return (
    <div className="flex items-center gap-1 rounded-full border border-primary/60 bg-surface p-1 shadow-elevation-1">
      <Button type="button" variant="ghost" size="icon" className="size-8 rounded-full" aria-label={prevLabel} onClick={onPrev}>
        <ChevronLeft aria-hidden="true" />
      </Button>
      <span className="flex items-center gap-2 px-1 text-sm font-medium text-primary" aria-live="polite">
        <CalendarDays className="size-4" aria-hidden="true" />
        {label}
      </span>
      <Button type="button" variant="ghost" size="icon" className="size-8 rounded-full" aria-label={nextLabel} onClick={onNext}>
        <ChevronRight aria-hidden="true" />
      </Button>
    </div>
  );
}
