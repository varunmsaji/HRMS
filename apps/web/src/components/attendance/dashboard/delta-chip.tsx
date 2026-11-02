import { ArrowDownRight, ArrowUpRight, Minus } from "lucide-react";

import { cn } from "@/lib/utils";

/** Which direction is good news: more present is good, more absent is not, leave is neutral. */
export type DeltaGood = "up" | "down" | "neutral";

interface DeltaChipProps {
  /** Signed change, or `null` when there's nothing to compare with. */
  delta: number | null;
  good: DeltaGood;
  /** Rendered after the number, e.g. " pts" or "". */
  unit?: string;
  /** What it was compared with, e.g. "last Mon". */
  versus: string;
  decimals?: number;
  className?: string;
}

/** A small "▲ 2 vs last Mon" pill, coloured by whether the change is good news — not by its sign. */
export function DeltaChip({ delta, good, unit = "", versus, decimals = 0, className }: DeltaChipProps) {
  if (delta === null) {
    return <span className={cn("text-[11px] text-foreground-muted", className)}>No comparison yet</span>;
  }
  const rounded = Number(delta.toFixed(decimals));
  const flat = rounded === 0;
  const up = rounded > 0;
  const tone = flat || good === "neutral" ? "neutral" : (up ? "up" : "down") === good ? "good" : "bad";
  const Icon = flat ? Minus : up ? ArrowUpRight : ArrowDownRight;
  const text = flat ? `No change vs ${versus}` : `${up ? "+" : "−"}${Math.abs(rounded).toFixed(decimals)}${unit} vs ${versus}`;
  return (
    <span
      className={cn(
        "inline-flex animate-in fade-in-0 items-center gap-0.5 rounded-full px-1.5 py-0.5 text-[11px] font-medium tabular-nums delay-200 duration-motion-slow [animation-fill-mode:backwards]",
        tone === "good" && "bg-success-subtle text-success",
        tone === "bad" && "bg-danger-subtle text-danger",
        tone === "neutral" && "bg-muted text-foreground-secondary",
        className,
      )}
    >
      <Icon className="h-3 w-3" aria-hidden="true" />
      {text}
    </span>
  );
}
