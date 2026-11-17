"use client";

import { useEffect, useMemo, useState, type ReactNode } from "react";

import { apiClient } from "@/lib/api/client";
import type { ShiftBreak, ShiftVersion } from "@/lib/shift/types";
import { cn } from "@/lib/utils";

/** Shared look for shift cards across the roster views (grid, schedule, board, calendar): a
 * soft tinted card with a coloured left bar, the time range, shift name and break length. All
 * colours are the app's own theme tokens. */

const SHIFT_TONES = [
  "border-primary bg-primary-subtle text-primary",
  "border-success bg-success-subtle text-success",
  "border-warning bg-warning-subtle text-warning",
  "border-info bg-info-subtle text-info",
  "border-danger bg-danger-subtle text-danger",
] as const;
export const NIGHT_TONE = "border-foreground bg-muted text-foreground";
export const OFF_TONE =
  "border-border-strong bg-surface-secondary text-foreground-secondary";

/** A stable colour per shift, so a pattern (all mornings, then nights) reads at a glance. Night
 * shifts are always dark, matching the Schedule coverage tab. */
export function shiftTone(
  shift: { id: string; is_night_shift?: boolean } | undefined,
): string {
  if (!shift) return SHIFT_TONES[0];
  if (shift.is_night_shift) return NIGHT_TONE;
  let h = 0;
  for (const ch of shift.id) h = (h * 31 + ch.charCodeAt(0)) >>> 0;
  return SHIFT_TONES[h % SHIFT_TONES.length];
}

export function initialsOf(name: string): string {
  const parts = name.split(/\s+/).filter(Boolean);
  return (
    (parts[0]?.[0] ?? "") +
    (parts.length > 1 ? (parts[parts.length - 1][0] ?? "") : "")
  ).toUpperCase();
}

export function hhmm(t: string | null | undefined): string {
  return t ? t.slice(0, 5) : "";
}

/** The live schedule of a shift, from its current version. */
export interface ShiftSchedule {
  start: string | null;
  end: string | null;
  breakMinutes: number;
}

function minutesBetween(from: string, to: string): number {
  const [fh, fm] = from.split(":").map(Number);
  const [th, tm] = to.split(":").map(Number);
  let diff = th * 60 + tm - (fh * 60 + fm);
  if (diff < 0) diff += 24 * 60;
  return diff;
}

function breakMinutes(b: ShiftBreak): number {
  if (b.break_kind === "FIXED_WINDOW" && b.start_time && b.end_time) {
    return minutesBetween(b.start_time, b.end_time);
  }
  return b.scheduled_minutes ?? b.max_minutes ?? b.min_minutes ?? 0;
}

export function scheduleOf(v: ShiftVersion): ShiftSchedule {
  return {
    start: v.start_time ?? v.window_start,
    end: v.end_time ?? v.window_end,
    breakMinutes: (v.breaks ?? []).reduce((sum, b) => sum + breakMinutes(b), 0),
  };
}

/** Times and breaks live on a shift's current version (the shift row only carries frozen legacy
 * values). Resolves each shift as of `asOf`; a failure (e.g. no shift-manage permission) simply
 * leaves that shift out so callers fall back to the legacy fields. */
export function useShiftSchedules(
  shiftIds: string[],
  asOf: string,
): Map<string, ShiftSchedule> {
  const [schedules, setSchedules] = useState<Map<string, ShiftSchedule>>(
    new Map(),
  );
  const key = useMemo(
    () => [...new Set(shiftIds)].sort().join(","),
    [shiftIds],
  );
  useEffect(() => {
    const ids = key ? key.split(",") : [];
    if (ids.length === 0) return;
    let cancelled = false;
    void Promise.all(
      ids.map((id) =>
        apiClient
          .get<ShiftVersion>(`/shifts/${id}/versions/resolve?as_of=${asOf}`)
          .then((v) => [id, scheduleOf(v)] as const)
          .catch(() => null),
      ),
    ).then((pairs) => {
      if (cancelled) return;
      setSchedules(
        new Map(
          pairs.filter(
            (p): p is readonly [string, ShiftSchedule] => p !== null,
          ),
        ),
      );
    });
    return () => {
      cancelled = true;
    };
  }, [key, asOf]);
  return schedules;
}

export function PersonAvatar({
  name,
  className,
}: {
  name: string;
  className?: string;
}) {
  return (
    <span
      aria-hidden="true"
      className={cn(
        "flex size-9 shrink-0 items-center justify-center rounded-full bg-primary-subtle text-xs font-semibold text-primary",
        className,
      )}
    >
      {initialsOf(name)}
    </span>
  );
}

/** The card itself. Spans only, so it can sit inside a button. */
export function ShiftCard({
  tone,
  time,
  label,
  subLabel,
  breakMins = 0,
  draft = false,
  className,
  children,
}: {
  tone: string;
  time?: string;
  label: ReactNode;
  subLabel?: string;
  breakMins?: number;
  draft?: boolean;
  className?: string;
  children?: ReactNode;
}) {
  return (
    <span
      className={cn(
        "block w-full rounded-md border-l-4 px-2.5 py-2 text-left leading-tight",
        tone,
        draft &&
          "border-y border-r border-dashed border-y-foreground-muted border-r-foreground-muted",
        className,
      )}
    >
      {time ? (
        <span className="block text-xs font-semibold">{time}</span>
      ) : null}
      <span className="mt-0.5 block text-[11px] font-medium opacity-90">
        {label}
      </span>
      {subLabel ? (
        <span className="mt-0.5 block text-[11px] font-normal opacity-75">
          {subLabel}
        </span>
      ) : null}
      {breakMins > 0 ? (
        <span className="mt-1 flex items-center gap-1 text-[11px] font-medium">
          <span
            aria-hidden="true"
            className="inline-block h-2.5 w-1 rounded-sm bg-current opacity-70"
          />
          {breakMins} m break
        </span>
      ) : null}
      {children}
    </span>
  );
}
