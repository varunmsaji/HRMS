"use client";

import { CheckCircle2, CircleSlash, X } from "lucide-react";
import { useMemo, useRef, useState } from "react";

import { FormField } from "@/components/common/form-field";
import { useToast } from "@/components/common/toast";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { apiClient, newIdempotencyKey } from "@/lib/api/client";
import { ApiError, describeApiError } from "@/lib/api/errors";
import { addDays, formatShortDate } from "@/lib/attendance/dashboard";
import { businessToday, formatClockTime, wallTimeToUtcIso, zoneLabel } from "@/lib/attendance/format";
import {
  MANUAL_DAY_MAX_EMPLOYEES,
  MANUAL_DAY_MAX_SPAN_HOURS,
  type ManualDayEntryInput,
  type ManualDayEntryResponse,
  type ManualDayEntryResult,
} from "@/lib/attendance/types";
import { useAuth } from "@/lib/auth/auth-context";
import {
  employeeOptionName,
  useEmployeeDirectory,
  type EmployeeDirectory,
} from "@/lib/employee/use-employee-directory";

export interface MarkDayEmployee {
  id: string;
  label: string;
}

interface MarkDayDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Pre-selected employees, e.g. the row "Mark present" was clicked on. Read when the dialog
   * opens. */
  initialEmployees?: MarkDayEmployee[];
  /** Hide the picker and keep exactly `initialEmployees` (the employee's own Attendance tab). */
  lockEmployees?: boolean;
  /** `YYYY-MM-DD` in the business timezone. Defaults to today. */
  initialDate?: string;
  onRecorded: () => void;
}

type Step = "edit" | "review" | "done";

const REASON_PRESETS = [
  "Biometric device was offline",
  "Forgot to punch",
  "On-site / field work",
  "App or network issue",
];

/** Plain-language versions of the server's refusal codes. Unknown codes fall back to the
 * server's own message. */
const BLOCK_REASONS: Record<string, string> = {
  EXISTING_PUNCHES: "Already has punches on this day. Fix it with Record punch instead.",
  ATTENDANCE_PERIOD_CLOSED: "The attendance period for this date is closed. Reopen it first.",
  EMPLOYEE_TERMINATED: "This date is after the employee's last working day.",
  PUNCH_TIME_BEFORE_EMPLOYMENT: "This date is before the employee joined.",
  PUNCH_TIME_IN_FUTURE: "The time is in the future.",
  NOT_FOUND: "Not found, or outside the employees you manage.",
  SELF_ENTRY_NOT_ALLOWED: "You can't mark your own attendance. Ask another HR admin, or raise a regularization.",
};

function blockReason(result: ManualDayEntryResult): string {
  return (result.code && BLOCK_REASONS[result.code]) || result.message || "Could not be recorded.";
}

function formatSpan(minutes: number): string {
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  return m ? `${h}h ${m}m` : `${h}h`;
}

/** HR marks a whole day — an IN and an OUT — for one or more employees.
 *
 * Two steps, never one: **Review** asks the server (`/day-entries/preview`) what would happen to
 * each employee and shows it, and only **Confirm** writes. The confirm sends just the employees
 * the review marked ready, under one idempotency key kept for the whole review, so a retry after
 * a network failure cannot record anyone twice. Changing any field after a review discards it.
 *
 * Times are wall-clock times in the business timezone, converted with `wallTimeToUtcIso` — never
 * the viewer's browser zone (`D1`). An OUT time at or before the IN time means the next day
 * (an overnight shift), and the form says so. */
export function MarkDayDialog(props: MarkDayDialogProps) {
  // The form mounts fresh on every open, so it always starts from the props — no reset effect.
  if (!props.open) return null;
  const key = `${props.initialDate ?? ""}|${(props.initialEmployees ?? []).map((e) => e.id).join(",")}`;
  return <MarkDayForm key={key} {...props} />;
}

function MarkDayForm({
  onOpenChange,
  initialEmployees,
  lockEmployees = false,
  initialDate,
  onRecorded,
}: MarkDayDialogProps) {
  const { toast } = useToast();
  const { user } = useAuth();
  const tz = user?.company_timezone ?? "Asia/Kolkata";
  const today = businessToday(tz);
  const directory = useEmployeeDirectory({ enabled: !lockEmployees });

  const [selected, setSelected] = useState<MarkDayEmployee[]>(initialEmployees ?? []);
  const [date, setDate] = useState(initialDate ?? today);
  const [inTime, setInTime] = useState("09:00");
  const [outTime, setOutTime] = useState("18:00");
  const [reason, setReason] = useState("");
  const [step, setStep] = useState<Step>("edit");
  const [preview, setPreview] = useState<ManualDayEntryResponse | null>(null);
  const [result, setResult] = useState<ManualDayEntryResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const submitKey = useRef<string | null>(null);

  const overnight = outTime <= inTime;
  const outDate = overnight ? addDays(date, 1) : date;
  const instants = useMemo(() => {
    if (!date || !inTime || !outTime) return null;
    try {
      const punchIn = wallTimeToUtcIso(`${date}T${inTime}`, tz);
      const punchOut = wallTimeToUtcIso(`${outDate}T${outTime}`, tz);
      const spanMinutes = Math.round((Date.parse(punchOut) - Date.parse(punchIn)) / 60000);
      return { punchIn, punchOut, spanMinutes };
    } catch {
      return null;
    }
  }, [date, inTime, outTime, outDate, tz]);

  const names = useMemo(() => {
    const map = new Map<string, string>();
    for (const e of directory.employees) map.set(e.id, employeeOptionName(e));
    for (const e of selected) map.set(e.id, e.label);
    return map;
  }, [directory.employees, selected]);

  /** Any edit invalidates a review — what was checked is no longer what would be sent. */
  function edited<T>(setter: (value: T) => void) {
    return (value: T) => {
      setter(value);
      if (step !== "edit") {
        setStep("edit");
        setPreview(null);
        submitKey.current = null;
      }
      setError(null);
    };
  }

  function validate(): string | null {
    if (selected.length === 0) return "Choose at least one employee.";
    if (selected.length > MANUAL_DAY_MAX_EMPLOYEES)
      return `Choose at most ${MANUAL_DAY_MAX_EMPLOYEES} employees at a time.`;
    if (!instants) return "Enter a date, an IN time and an OUT time.";
    if (date > today) return "The date can't be in the future.";
    if (Date.parse(instants.punchOut) > Date.now())
      return "The OUT time hasn't happened yet. Record only the IN with Record punch, or wait.";
    if (instants.spanMinutes > MANUAL_DAY_MAX_SPAN_HOURS * 60)
      return `IN to OUT can be at most ${MANUAL_DAY_MAX_SPAN_HOURS} hours.`;
    if (reason.trim().length < 3) return "Give a reason. It is saved with every punch and in the audit log.";
    return null;
  }

  function body(employeeIds: string[], idempotencyKey?: string): ManualDayEntryInput {
    return {
      employee_ids: employeeIds,
      punch_in_at: instants!.punchIn,
      punch_out_at: instants!.punchOut,
      reason: reason.trim(),
      ...(idempotencyKey ? { idempotency_key: idempotencyKey } : {}),
    };
  }

  async function handleReview() {
    const problem = validate();
    if (problem) {
      setError(problem);
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const data = await apiClient.post<ManualDayEntryResponse>(
        "/attendance/punches/day-entries/preview",
        body(selected.map((e) => e.id)),
      );
      setPreview(data);
      submitKey.current = newIdempotencyKey();
      setStep("review");
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  }

  async function handleConfirm() {
    if (!preview) return;
    const ready = preview.results.filter((r) => r.outcome === "READY").map((r) => r.employee_id);
    if (ready.length === 0) return;
    setBusy(true);
    setError(null);
    try {
      submitKey.current ??= newIdempotencyKey();
      const data = await apiClient.post<ManualDayEntryResponse>(
        "/attendance/punches/day-entries",
        body(ready, submitKey.current),
      );
      setResult(data);
      setStep("done");
      onRecorded();
      if (data.recorded_count > 0) {
        toast({
          title: `Attendance marked for ${data.recorded_count} employee${data.recorded_count === 1 ? "" : "s"}`,
          variant: "success",
        });
      }
    } catch (err) {
      // The key is kept: pressing Confirm again resends the same submission, and the server
      // returns what it already stored instead of storing it twice.
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  }

  const readyCount = preview?.ready_count ?? 0;
  const zone = zoneLabel(tz);

  return (
    <Dialog open onOpenChange={(next) => (!busy ? onOpenChange(next) : null)}>
      <DialogContent className="max-h-[90vh] max-w-lg overflow-y-auto">
        <DialogHeader>
          <DialogTitle>Mark attendance</DialogTitle>
          <DialogDescription>
            Records an IN and an OUT punch for each employee. Each punch is marked as entered by
            HR and saved to the audit log with your reason.
          </DialogDescription>
        </DialogHeader>

        {step === "done" && result ? (
          <DoneSummary result={result} names={names} />
        ) : (
          <div className="space-y-4">
            {lockEmployees ? (
              <FormField id="mark-day-employee" label="Employee">
                <Input value={selected.map((e) => e.label).join(", ")} disabled />
              </FormField>
            ) : (
              <EmployeeChecklist
                directory={directory}
                excludeId={user?.employee_id ?? undefined}
                selected={selected}
                onChange={edited(setSelected)}
              />
            )}

            <div className="grid gap-3 sm:grid-cols-3">
              <FormField id="mark-day-date" label="Date" required>
                <Input
                  type="date"
                  value={date}
                  max={today}
                  onChange={(e) => edited(setDate)(e.target.value)}
                />
              </FormField>
              <FormField id="mark-day-in" label={`IN (${zone})`} required>
                <Input type="time" value={inTime} onChange={(e) => edited(setInTime)(e.target.value)} />
              </FormField>
              <FormField id="mark-day-out" label={`OUT (${zone})`} required>
                <Input type="time" value={outTime} onChange={(e) => edited(setOutTime)(e.target.value)} />
              </FormField>
            </div>
            {instants ? (
              <p className="text-sm text-foreground-secondary">
                {formatShortDate(date)} {inTime} → {overnight ? `${formatShortDate(outDate)} ` : ""}
                {outTime} · {formatSpan(instants.spanMinutes)}
                {overnight ? (
                  <Badge variant="info" className="ml-2">
                    OUT is next day
                  </Badge>
                ) : null}
              </p>
            ) : null}

            <FormField
              id="mark-day-reason"
              label="Reason"
              required
              description="Saved on every punch and in the audit log."
            >
              <Input
                value={reason}
                maxLength={200}
                onChange={(e) => edited(setReason)(e.target.value)}
              />
            </FormField>
            <div className="flex flex-wrap gap-1.5">
              {REASON_PRESETS.map((preset) => (
                <Button
                  key={preset}
                  type="button"
                  size="xs"
                  variant={reason === preset ? "default" : "outline"}
                  onClick={() => edited(setReason)(preset)}
                >
                  {preset}
                </Button>
              ))}
            </div>

            {step === "review" && preview ? (
              <ReviewList preview={preview} names={names} timezone={tz} />
            ) : null}

            {error ? (
              <p role="alert" className="text-sm text-danger">
                {error}
              </p>
            ) : null}
          </div>
        )}

        <DialogFooter>
          {step === "done" ? (
            <Button type="button" onClick={() => onOpenChange(false)}>
              Close
            </Button>
          ) : (
            <>
              <Button type="button" variant="outline" onClick={() => onOpenChange(false)} disabled={busy}>
                Cancel
              </Button>
              {step === "edit" ? (
                <Button type="button" onClick={() => void handleReview()} disabled={busy}>
                  {busy ? "Checking…" : "Review"}
                </Button>
              ) : (
                <Button
                  type="button"
                  onClick={() => void handleConfirm()}
                  disabled={busy || readyCount === 0}
                >
                  {busy
                    ? "Recording…"
                    : readyCount === 0
                      ? "Nothing to record"
                      : `Confirm for ${readyCount} employee${readyCount === 1 ? "" : "s"}`}
                </Button>
              )}
            </>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function errorText(err: unknown): string {
  if (err instanceof ApiError && err.status === 403) {
    return "You don't have permission to mark attendance for other employees.";
  }
  return err instanceof ApiError ? describeApiError(err) : "Something went wrong.";
}

function EmployeeChecklist({
  directory,
  excludeId,
  selected,
  onChange,
}: {
  directory: EmployeeDirectory;
  /** The caller's own employee: HR cannot mark their own attendance here. */
  excludeId?: string;
  selected: MarkDayEmployee[];
  onChange: (next: MarkDayEmployee[]) => void;
}) {
  const [query, setQuery] = useState("");
  const selectedIds = useMemo(() => new Set(selected.map((e) => e.id)), [selected]);
  const atCap = selected.length >= MANUAL_DAY_MAX_EMPLOYEES;
  const q = query.trim().toLowerCase();
  const candidates = excludeId ? directory.employees.filter((e) => e.id !== excludeId) : directory.employees;
  const visible = q ? candidates.filter((e) => employeeOptionName(e).toLowerCase().includes(q)) : candidates;

  function toggle(id: string, label: string) {
    if (selectedIds.has(id)) onChange(selected.filter((e) => e.id !== id));
    else if (!atCap) onChange([...selected, { id, label }]);
  }

  return (
    <fieldset className="space-y-2">
      <legend className="text-sm font-medium text-foreground">
        Employees <span className="text-danger">*</span>
      </legend>
      {selected.length > 0 ? (
        <ul className="flex flex-wrap gap-1.5" aria-label="Selected employees">
          {selected.map((e) => (
            <li key={e.id}>
              <Badge variant="secondary" className="gap-1 pr-1">
                {e.label}
                <button
                  type="button"
                  aria-label={`Remove ${e.label}`}
                  className="rounded-sm p-0.5 hover:bg-accent"
                  onClick={() => onChange(selected.filter((s) => s.id !== e.id))}
                >
                  <X className="h-3 w-3" aria-hidden="true" />
                </button>
              </Badge>
            </li>
          ))}
        </ul>
      ) : null}
      <Input
        type="search"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        placeholder="Filter loaded employees…"
        aria-label="Filter employees"
      />
      <div className="max-h-48 overflow-y-auto rounded-md border border-border">
        {directory.loading && directory.employees.length === 0 ? (
          <p className="px-3 py-2 text-sm text-foreground-muted">Loading employees…</p>
        ) : visible.length === 0 ? (
          <p className="px-3 py-2 text-sm text-foreground-muted">No employee matches.</p>
        ) : (
          <ul className="divide-y divide-border">
            {visible.map((emp) => {
              const label = employeeOptionName(emp);
              const checked = selectedIds.has(emp.id);
              return (
                <li key={emp.id}>
                  <label className="flex cursor-pointer items-center gap-2 px-3 py-1.5 text-sm hover:bg-accent">
                    <Checkbox
                      checked={checked}
                      disabled={!checked && atCap}
                      onChange={() => toggle(emp.id, label)}
                    />
                    {label}
                  </label>
                </li>
              );
            })}
          </ul>
        )}
      </div>
      <div className="flex flex-wrap items-center gap-2 text-xs text-foreground-muted">
        <span>
          {selected.length} selected{atCap ? ` (the limit is ${MANUAL_DAY_MAX_EMPLOYEES} at a time)` : ""}.
        </span>
        {directory.error ? (
          <Button type="button" variant="ghost" size="xs" onClick={directory.retry}>
            Retry loading
          </Button>
        ) : directory.hasMore ? (
          <>
            <span>
              Showing {directory.employees.length} of {directory.total ?? "many"}.
            </span>
            <Button
              type="button"
              variant="ghost"
              size="xs"
              onClick={directory.loadMore}
              disabled={directory.loadingMore}
            >
              {directory.loadingMore ? "Loading…" : "Load more"}
            </Button>
          </>
        ) : null}
      </div>
    </fieldset>
  );
}

function ReviewList({
  preview,
  names,
  timezone,
}: {
  preview: ManualDayEntryResponse;
  names: Map<string, string>;
  timezone: string;
}) {
  return (
    <section aria-label="Review" className="space-y-2 rounded-md border border-border p-3">
      <p className="text-sm font-medium text-foreground">
        {preview.ready_count} ready
        {preview.blocked_count ? ` · ${preview.blocked_count} will be skipped` : ""}
      </p>
      <ul className="max-h-56 space-y-1.5 overflow-y-auto text-sm">
        {preview.results.map((r) => (
          <li key={r.employee_id} className="flex items-start gap-2">
            {r.outcome === "READY" ? (
              <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-success" aria-label="Ready" />
            ) : (
              <CircleSlash className="mt-0.5 h-4 w-4 shrink-0 text-danger" aria-label="Skipped" />
            )}
            <div className="min-w-0">
              <p className="text-foreground">{names.get(r.employee_id) ?? "Employee"}</p>
              {r.outcome === "BLOCKED" ? (
                <p className="text-xs text-foreground-secondary">
                  {blockReason(r)}
                  {r.existing_punches.length
                    ? ` Existing: ${r.existing_punches
                        .map((p) => `${p.direction} ${formatClockTime(p.punch_time, timezone)}`)
                        .join(", ")}.`
                    : ""}
                </p>
              ) : null}
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}

function DoneSummary({ result, names }: { result: ManualDayEntryResponse; names: Map<string, string> }) {
  const blocked = result.results.filter((r) => r.outcome === "BLOCKED");
  return (
    <div className="space-y-3 text-sm">
      <p className="flex items-center gap-2 text-foreground">
        <CheckCircle2 className="h-4 w-4 text-success" aria-hidden="true" />
        Marked for {result.recorded_count} employee{result.recorded_count === 1 ? "" : "s"}. Their
        attendance has been recalculated.
      </p>
      {blocked.length ? (
        <div className="space-y-1">
          <p className="font-medium text-foreground">
            Not recorded ({blocked.length}) — something changed since the review:
          </p>
          <ul className="space-y-1">
            {blocked.map((r) => (
              <li key={r.employee_id} className="text-foreground-secondary">
                {names.get(r.employee_id) ?? "Employee"}: {blockReason(r)}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </div>
  );
}
