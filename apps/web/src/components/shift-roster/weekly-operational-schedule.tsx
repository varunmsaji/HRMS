"use client";

import { AlertTriangle, CheckCircle2, Info, Moon } from "lucide-react";

import {
  formatHours,
  isoWeek,
  shortDate,
  timeRange,
  type ScheduleCell,
  type ScheduleShift,
  type WeeklySchedule,
} from "@/lib/shift-roster/schedule";
import { cn } from "@/lib/utils";

const AVATAR_TONES = [
  "bg-primary-subtle text-primary",
  "bg-success-subtle text-success",
  "bg-warning-subtle text-warning",
  "bg-info-subtle text-info",
  "bg-danger-subtle text-danger",
];

function toneFor(seed: string): string {
  let h = 0;
  for (const ch of seed) h = (h * 31 + ch.charCodeAt(0)) >>> 0;
  return AVATAR_TONES[h % AVATAR_TONES.length];
}

function Avatar({ initials, id, dark }: { initials: string; id: string; dark: boolean }) {
  return (
    <span
      className={cn(
        "inline-flex h-6 w-6 items-center justify-center rounded-full border-2 border-surface text-[9px] font-semibold",
        dark ? "bg-foreground text-surface" : toneFor(id),
      )}
    >
      {initials}
    </span>
  );
}

function DayHead({ iso, today, hasOff }: { iso: string; today: string; hasOff: boolean }) {
  const [weekday, day, month] = shortDate(iso).split(" ");
  const isToday = iso === today;
  return (
    <th
      scope="col"
      className={cn(
        "min-w-[8.5rem] px-3 py-3 text-center text-2xs font-semibold uppercase tracking-wider",
        isToday ? "border-x-2 border-t-2 border-primary text-primary" : "text-foreground-muted",
        hasOff && !isToday && "text-foreground-muted/70",
      )}
    >
      <div className="flex items-center justify-center gap-1.5">
        {isToday ? <span className="h-1.5 w-1.5 rounded-full bg-primary" aria-hidden="true" /> : null}
        <span>
          {weekday} {day} {month}
        </span>
      </div>
      {isToday ? (
        <span className="mt-1 inline-block rounded bg-primary px-1.5 py-0.5 text-[9px] text-on-primary">TODAY</span>
      ) : null}
    </th>
  );
}

function Cell({ cell, shift, today }: { cell: ScheduleCell; shift: ScheduleShift; today: boolean }) {
  const dark = shift.is_night_shift;
  const extra = cell.count - cell.people.length;
  if (cell.count === 0) {
    return (
      <td className={cn("p-2 align-top", today && "border-x-2 border-primary bg-primary-subtle/30")}>
        <div className="flex h-[3.75rem] flex-col items-center justify-center rounded-lg border border-dashed border-border text-2xs text-foreground-muted">
          <Moon className="mb-0.5 h-3.5 w-3.5" aria-hidden="true" />
          Weekly off
        </div>
      </td>
    );
  }
  const below = cell.met === false;
  return (
    <td className={cn("p-2 align-top", today && "border-x-2 border-primary bg-primary-subtle/30")}>
      <div
        className={cn(
          "rounded-lg border bg-surface p-2",
          below ? "border-warning-border bg-warning-subtle/40" : "border-border",
          today && !below && "border-primary",
        )}
        title={
          below
            ? `Below the minimum of ${shift.min_staff} for this shift`
            : cell.people.map((p) => p.name).join(", ")
        }
      >
        <div className="flex items-center justify-between gap-1 text-xs font-semibold text-foreground">
          <span className="flex items-center gap-1.5">
            <span
              className={cn("h-1.5 w-1.5 rounded-full", below ? "bg-warning" : "bg-success")}
              aria-hidden="true"
            />
            {cell.count} Staff
          </span>
          {today ? (
            <span className="rounded bg-primary px-1 py-px text-[9px] font-semibold text-on-primary">Live</span>
          ) : cell.has_pending_swap ? (
            <span className="text-warning" title="Swap request pending" aria-label="Swap request pending">
              ⇄
            </span>
          ) : null}
        </div>
        <div className="mt-1.5 flex items-center -space-x-1.5">
          {cell.people.map((p) => (
            <Avatar key={p.id} id={p.id} initials={p.initials} dark={dark} />
          ))}
          {extra > 0 ? (
            <span className="inline-flex h-6 min-w-6 items-center justify-center rounded-full border-2 border-surface bg-muted px-1 text-[9px] font-semibold text-foreground-secondary">
              +{extra}
            </span>
          ) : null}
        </div>
      </div>
    </td>
  );
}

function ShiftHead({ shift }: { shift: ScheduleShift }) {
  const met = shift.min_staff !== null && shift.days_below_target === 0;
  return (
    <th
      scope="row"
      className="sticky left-0 z-10 min-w-[15rem] border-r border-border bg-surface px-5 py-4 text-left align-top"
    >
      <div className="flex items-center gap-2">
        <span className="text-sm font-semibold text-foreground">{shift.name}</span>
        <span className="rounded bg-primary-subtle px-1.5 py-0.5 text-[10px] font-semibold text-primary">
          {shift.peak_staff} Staff
        </span>
      </div>
      <p className="mt-0.5 text-xs text-foreground-secondary">
        {timeRange(shift.start_time, shift.end_time)} • {formatHours(shift.weekly_hours)}h/wk
      </p>
      {shift.departments.length > 0 ? (
        <p className="mt-1.5 text-xs text-foreground-muted">{shift.departments.join(", ")}</p>
      ) : null}
      {shift.min_staff !== null ? (
        <p
          className={cn(
            "mt-1.5 flex items-center gap-1 text-xs font-medium",
            met ? "text-success" : "text-warning",
          )}
        >
          {met ? (
            <CheckCircle2 className="h-3.5 w-3.5" aria-hidden="true" />
          ) : (
            <AlertTriangle className="h-3.5 w-3.5" aria-hidden="true" />
          )}
          Target: {shift.min_staff} {met ? "met" : `— below on ${shift.days_below_target} ${shift.days_below_target === 1 ? "day" : "days"}`}{" "}
          (peak {shift.peak_staff})
        </p>
      ) : null}
    </th>
  );
}

export function WeeklyOperationalSchedule({ schedule, today }: { schedule: WeeklySchedule; today: string }) {
  const { shifts, days, totals } = schedule;
  const dayHasNoStaff = (iso: string) => shifts.every((s) => (s.cells.find((c) => c.date === iso)?.count ?? 0) === 0);
  return (
    <section
      aria-label="Weekly operational schedule"
      className="overflow-hidden rounded-2xl border border-border bg-surface shadow-elevation-1"
    >
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border px-5 py-4">
        <div className="flex items-center gap-2.5">
          <h2 className="text-base font-semibold text-foreground">Weekly Operational Schedule</h2>
          <span className="rounded-full bg-muted px-2.5 py-0.5 text-2xs font-medium text-foreground-secondary">
            {shifts.length} Active {shifts.length === 1 ? "Rotation" : "Rotations"}
          </span>
        </div>
        <div className="flex items-center gap-4 text-xs text-foreground-secondary">
          <span className="flex items-center gap-1.5">
            <span className="h-2 w-2 rounded-full bg-success" aria-hidden="true" /> Threshold Fulfilled
          </span>
          <span className="flex items-center gap-1.5">
            <span className="h-2 w-2 rounded-full bg-warning" aria-hidden="true" /> Below Target / Swap Pending
          </span>
        </div>
      </div>

      {shifts.length === 0 ? (
        <p className="px-5 py-10 text-center text-sm text-foreground-muted">
          No shifts are rostered for this week.
        </p>
      ) : (
        <div className="overflow-x-auto">
          <table className="min-w-full border-collapse text-sm">
            <thead>
              <tr className="bg-muted/40">
                <th
                  scope="col"
                  className="sticky left-0 z-10 border-r border-border bg-muted px-5 py-3 text-left text-2xs font-semibold uppercase tracking-wider text-foreground-muted"
                >
                  Shift timing &amp; rotation
                </th>
                {days.map((d) => (
                  <DayHead key={d} iso={d} today={today} hasOff={dayHasNoStaff(d)} />
                ))}
              </tr>
            </thead>
            <tbody>
              {shifts.map((shift) => (
                <tr key={shift.id} className="border-t border-border">
                  <ShiftHead shift={shift} />
                  {shift.cells.map((cell) => (
                    <Cell key={cell.date} cell={cell} shift={shift} today={cell.date === today} />
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div className="flex flex-wrap items-center justify-between gap-2 border-t border-border bg-muted/30 px-5 py-3 text-xs text-foreground-secondary">
        <span className="flex items-center gap-1.5">
          <Info className="h-3.5 w-3.5" aria-hidden="true" />
          Total allocated roster hours:{" "}
          <strong className="text-foreground">{totals.allocated_hours.toLocaleString()} hrs</strong> / Week{" "}
          {isoWeek(schedule.week_start)}
        </span>
        {totals.last_roster_update ? (
          <span>
            Roster last updated{" "}
            {new Date(totals.last_roster_update).toLocaleString("en-GB", {
              day: "2-digit",
              month: "short",
              hour: "2-digit",
              minute: "2-digit",
            })}
          </span>
        ) : null}
      </div>
    </section>
  );
}
