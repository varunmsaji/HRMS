"use client";

import { RefreshCw } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { useApiResource } from "@/hooks/use-api-resource";
import type { Branch } from "@/lib/branch/types";
import type { Department } from "@/lib/department/types";

import { ProportionBar } from "@/components/attendance/dashboard/charts";
import { SectionCard } from "@/components/attendance/dashboard/section-card";
import { useWorkforceOverview } from "@/components/dashboard/use-workforce-overview";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/native-select";
import { formatClockTime } from "@/lib/attendance/format";
import {
  attendanceHref,
  DISTRIBUTION_BUCKETS,
  share,
  type AttendanceOverview,
  type AttendanceBuckets,
} from "@/lib/dashboard/overview";
import { cn } from "@/lib/utils";

interface Option {
  id: string;
  name: string;
}

interface Props {
  today: string;
  timezone: string;
  departments: Option[];
  branches: Option[];
}

type CardKey = keyof AttendanceBuckets | "late" | "exceptions";

interface CardDef {
  key: CardKey;
  label: string;
  value: number;
  note?: string;
  dot: string;
}

function buildCards(d: AttendanceOverview): CardDef[] {
  const cards: CardDef[] = [
    { key: "total", label: "Total employees", value: d.total, dot: "bg-primary", note: `${d.expected_employees} expected to work` },
    { key: "present", label: "Present", value: d.present, dot: "bg-success", note: d.half_day ? `${d.half_day} half-day` : undefined },
    {
      key: "absent",
      label: "Absent",
      value: d.absent,
      dot: "bg-danger",
      note: d.is_today ? "Shift ended, no attendance" : undefined,
    },
    { key: "on_leave", label: "On leave", value: d.on_leave, dot: "bg-on-leave", note: d.half_day_leave ? `${d.half_day_leave} half-day` : undefined },
    { key: "late", label: "Late arrivals", value: d.late, dot: "bg-warning", note: "Included in Present" },
    ...(d.is_today
      ? [{ key: "not_checked_in" as const, label: "Not checked in", value: d.not_checked_in, dot: "bg-border-strong", note: "Shift not yet over" }]
      : []),
    { key: "exceptions", label: "Attendance exceptions", value: d.exceptions, dot: "bg-warning", note: "Missing punch or pending approval" },
  ];
  // Remote work is only shown when the attendance engine actually produced such days.
  if (d.remote_work > 0) cards.splice(4, 0, { key: "remote_work", label: "Remote", value: d.remote_work, dot: "bg-wfh" });
  return cards;
}

export function WorkforceOverview({ today, timezone, departments, branches }: Props) {
  const [date, setDate] = useState("");
  const [departmentId, setDepartmentId] = useState("");
  const [branchId, setBranchId] = useState("");
  const { data, error, initialLoading, refreshing, fetchedAt, refresh } = useWorkforceOverview({
    date: date === today ? "" : date,
    departmentId,
    branchId,
    enabled: true,
  });

  const shownDate = data?.attendance_date ?? (date || today);
  const status = error && !data ? "error" : initialLoading ? "loading" : "ready";
  const isEmpty = !!data && data.total === 0;

  return (
    <SectionCard
      id="workforce-overview"
      title="Today's Workforce Overview"
      description={
        shownDate === today
          ? `Live for today, ${shownDate} (${timezone}).`
          : `Historical view for ${shownDate}. Pending requests below are always current.`
      }
      status={status}
      error={error}
      onRetry={() => void refresh()}
    >
      <div className="flex flex-wrap items-end gap-3">
        <label className="text-xs text-foreground-secondary">
          Date
          <Input
            type="date"
            value={date || today}
            max={today}
            onChange={(e) => setDate(e.target.value)}
            className="mt-1 h-9 w-40"
            aria-label="Attendance date"
          />
        </label>
        <label className="text-xs text-foreground-secondary">
          Department
          <NativeSelect value={departmentId} onChange={(e) => setDepartmentId(e.target.value)} className="mt-1 w-44" aria-label="Department">
            <option value="">All departments</option>
            {departments.map((o) => (
              <option key={o.id} value={o.id}>{o.name}</option>
            ))}
          </NativeSelect>
        </label>
        {branches.length > 0 ? (
          <label className="text-xs text-foreground-secondary">
            Branch
            <NativeSelect value={branchId} onChange={(e) => setBranchId(e.target.value)} className="mt-1 w-44" aria-label="Branch">
              <option value="">All branches</option>
              {branches.map((o) => (
                <option key={o.id} value={o.id}>{o.name}</option>
              ))}
            </NativeSelect>
          </label>
        ) : null}
        <div className="ml-auto flex items-center gap-3">
          <span className="text-xs text-foreground-muted" aria-live="polite">
            {fetchedAt ? `Updated ${formatClockTime(fetchedAt.toISOString(), timezone)}` : null}
          </span>
          <Button type="button" variant="outline" size="sm" onClick={() => void refresh()} disabled={refreshing} aria-label="Refresh workforce overview">
            <RefreshCw className={cn("h-4 w-4", refreshing && "animate-spin")} aria-hidden="true" />
            Refresh
          </Button>
        </div>
      </div>

      {error && data ? (
        <p role="alert" className="rounded-md border border-danger-border bg-danger-subtle px-3 py-2 text-xs text-danger">
          Couldn&apos;t refresh — showing the last loaded figures.{" "}
          <button type="button" className="font-medium underline" onClick={() => void refresh()}>Retry</button>
        </p>
      ) : null}

      {isEmpty ? (
        <p className="rounded-md border border-dashed border-border px-4 py-6 text-center text-sm text-foreground-secondary">
          No active employees match the selected date and filters.
        </p>
      ) : null}

      {data && !isEmpty ? (
        <div className={cn("space-y-6 transition-opacity", refreshing && "opacity-60")} aria-busy={refreshing}>
          <ul className="grid grid-cols-2 gap-3 sm:grid-cols-3 xl:grid-cols-4">
            {buildCards(data).map((card) => (
              <li key={card.key} className="min-w-0">
                <Link
                  href={attendanceHref(card.key, data.attendance_date, today)}
                  aria-label={`${card.label}: ${card.value}. View details.`}
                  className="flex h-full flex-col rounded-lg border border-border bg-surface p-4 hover:border-border-strong focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                >
                  <span className="flex items-center gap-2 text-xs font-medium text-foreground-secondary">
                    <span className={cn("h-2 w-2 shrink-0 rounded-full", card.dot)} aria-hidden="true" />
                    <span className="truncate">{card.label}</span>
                  </span>
                  <span className="mt-2 text-3xl font-semibold tabular-nums text-foreground">{card.value.toLocaleString()}</span>
                  {card.note ? <span className="mt-1 text-xs text-foreground-muted">{card.note}</span> : null}
                </Link>
              </li>
            ))}
          </ul>

          <div className="grid min-w-0 gap-6 lg:grid-cols-5 [&>*]:min-w-0">
            <div className="space-y-3 lg:col-span-2">
              <h3 className="text-sm font-semibold text-foreground">Attendance distribution</h3>
              <ProportionBar
                ariaLabel={`Attendance distribution across ${data.total} employees`}
                segments={DISTRIBUTION_BUCKETS.map((b) => ({ key: b.key, label: b.label, count: data[b.key], barClass: b.bar }))}
              />
              <ul className="space-y-1.5 text-sm">
                {DISTRIBUTION_BUCKETS.filter((b) => data[b.key] > 0).map((b) => {
                  const pct = share(data[b.key], data.total);
                  return (
                    <li key={b.key} className="flex items-center gap-2">
                      <span className={cn("h-2.5 w-2.5 shrink-0 rounded-sm", b.bar)} aria-hidden="true" />
                      <span className="flex-1 truncate text-foreground">{b.label}</span>
                      <span className="tabular-nums font-medium">{data[b.key]}</span>
                      <span className="w-12 text-right text-xs tabular-nums text-foreground-muted">{pct === null ? "—" : `${pct.toFixed(0)}%`}</span>
                    </li>
                  );
                })}
              </ul>
              {data.no_record > 0 ? (
                <p className="text-xs text-foreground-muted">
                  {data.no_record} employee{data.no_record === 1 ? " has" : "s have"} no attendance record for this date yet (the
                  daily calculation hasn&apos;t run for them), so they are not guessed into any category.
                </p>
              ) : null}
            </div>

            <div className="space-y-3 lg:col-span-3">
              <h3 className="text-sm font-semibold text-foreground">By department</h3>
              {data.departments.length === 0 ? (
                <p className="rounded-md border border-dashed border-border px-4 py-6 text-center text-sm text-foreground-secondary">No department data for this view.</p>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b border-border text-xs text-foreground-secondary">
                        <th scope="col" className="py-2 pr-3 text-left font-medium">Department</th>
                        <th scope="col" className="px-2 py-2 text-right font-medium">Total</th>
                        <th scope="col" className="px-2 py-2 text-right font-medium">Present</th>
                        <th scope="col" className="px-2 py-2 text-right font-medium">Absent</th>
                        <th scope="col" className="py-2 pl-2 text-right font-medium">On leave</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-border">
                      {data.departments.map((row) => (
                        <tr key={row.department_id ?? "none"}>
                          <th scope="row" className="max-w-[12rem] truncate py-2 pr-3 text-left font-medium text-foreground">
                            {row.department_id ? (
                              <Link href={`/app/departments/${row.department_id}`} className="hover:text-primary hover:underline">{row.department_name}</Link>
                            ) : (
                              row.department_name
                            )}
                          </th>
                          <td className="px-2 py-2 text-right tabular-nums">{row.total}</td>
                          <td className="px-2 py-2 text-right tabular-nums">{row.present}</td>
                          <td className="px-2 py-2 text-right tabular-nums">{row.absent}</td>
                          <td className="py-2 pl-2 text-right tabular-nums">{row.on_leave}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          </div>
        </div>
      ) : null}
    </SectionCard>
  );
}

/** Loads the department/branch filter options, then the overview. The lists are best-effort: if
 * they fail the filters simply offer "All". */
export function WorkforceSection({ today, timezone }: { today: string; timezone: string }) {
  const departments = useApiResource<Department[]>("/departments");
  const branches = useApiResource<Branch[]>("/branches");
  return (
    <WorkforceOverview
      today={today}
      timezone={timezone}
      departments={(departments.data ?? []).map((d) => ({ id: d.id, name: d.name }))}
      branches={(branches.data ?? []).map((b) => ({ id: b.id, name: b.name }))}
    />
  );
}
