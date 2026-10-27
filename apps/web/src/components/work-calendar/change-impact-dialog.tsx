"use client";

import { useCallback, useEffect, useState } from "react";

import { LoadingState } from "@/components/common/loading-state";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { apiClient } from "@/lib/api/client";
import { ApiError, describeApiError } from "@/lib/api/errors";
import { businessToday } from "@/lib/attendance/format";
import { useAuth } from "@/lib/auth/auth-context";
import { formatLongDate } from "@/lib/employee-calendar/month";
import {
  defaultWindow,
  describeSnapshot,
  type ImpactConfirmed,
  type ImpactPreview,
  type ProposedChange,
} from "@/lib/work-calendar/change-impact";

const MAX_ROWS_SHOWN = 100;
const MAX_LEAVE_SHOWN = 10;

interface Props {
  /** The edit the administrator has made, not yet saved. `null` keeps the dialog closed. */
  change: ProposedChange | null;
  title: string;
  /** Called once the backend has confirmed and applied the change. */
  onApplied: (result: ImpactConfirmed) => void;
  /** Back / cancel: nothing was changed. */
  onClose: () => void;
}

/** Preview-then-confirm for a calendar edit. The preview is read-only; "Confirm change" re-sends
 * the change with the preview's digest and the server rechecks everything before applying. */
export function ChangeImpactDialog({ change, title, onApplied, onClose }: Props) {
  const { user } = useAuth();
  const today = businessToday(user?.company_timezone ?? "Asia/Kolkata");
  const initial = defaultWindow(today);

  const [windowFrom, setWindowFrom] = useState(initial.from);
  const [windowTo, setWindowTo] = useState(initial.to);
  const [preview, setPreview] = useState<ImpactPreview | null>(null);
  const [previewedWindow, setPreviewedWindow] = useState<{ from: string; to: string } | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [stale, setStale] = useState(false);
  const [acknowledged, setAcknowledged] = useState(false);
  const [applying, setApplying] = useState(false);
  const [reloadToken, setReloadToken] = useState(0);

  useEffect(() => {
    if (!change) return;
    let cancelled = false;
    const run = async () => {
      setLoading(true);
      setError(null);
      setStale(false);
      setAcknowledged(false);
      try {
        const data = await apiClient.post<ImpactPreview>("/work-calendar-changes/preview", {
          change,
          window_from: windowFrom,
          window_to: windowTo,
        });
        if (cancelled) return;
        setPreview(data);
        setPreviewedWindow({ from: windowFrom, to: windowTo });
      } catch (err) {
        if (cancelled) return;
        setPreview(null);
        setError(
          err instanceof ApiError && err.code === "STALE_RESOURCE"
            ? "This record was changed by someone else after you opened it. Close this dialog and reopen it to see the latest version."
            : describeApiError(err),
        );
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    void run();
    return () => {
      cancelled = true;
    };
  }, [change, windowFrom, windowTo, reloadToken]);

  const refresh = useCallback(() => setReloadToken((n) => n + 1), []);

  async function handleConfirm() {
    if (!change || !preview || !previewedWindow) return;
    setApplying(true);
    setError(null);
    try {
      const result = await apiClient.post<ImpactConfirmed>("/work-calendar-changes/confirm", {
        change,
        window_from: previewedWindow.from,
        window_to: previewedWindow.to,
        impact_digest: preview.impact_digest,
        acknowledge_protected_impact: acknowledged,
      });
      onApplied(result);
    } catch (err) {
      if (err instanceof ApiError && err.code === "CALENDAR_PREVIEW_STALE") {
        setStale(true);
      } else {
        setError(describeApiError(err));
      }
    } finally {
      setApplying(false);
    }
  }

  const canConfirm =
    !!preview && !loading && !applying && !stale && (!preview.requires_acknowledgement || acknowledged);
  const windowValid = windowFrom !== "" && windowTo !== "" && windowFrom <= windowTo;

  return (
    <Dialog open={change !== null} onOpenChange={(open) => (!open ? onClose() : undefined)}>
      <DialogContent className="max-h-[90vh] max-w-3xl overflow-y-auto">
        <DialogHeader>
          <DialogTitle>{title}: review impact</DialogTitle>
        </DialogHeader>

        <div className="flex flex-wrap items-end gap-3">
          <label className="text-xs text-foreground-secondary">
            Preview from
            <Input
              type="date"
              value={windowFrom}
              onChange={(e) => setWindowFrom(e.target.value)}
              className="mt-1"
            />
          </label>
          <label className="text-xs text-foreground-secondary">
            Preview to
            <Input
              type="date"
              value={windowTo}
              onChange={(e) => setWindowTo(e.target.value)}
              className="mt-1"
            />
          </label>
          <p className="pb-2 text-xs text-foreground-muted">
            Nothing is saved until you confirm. Windows are limited to one year.
          </p>
        </div>

        {!windowValid ? (
          <p role="alert" className="text-sm text-danger">
            Choose a start date that is not after the end date.
          </p>
        ) : null}

        {loading ? <LoadingState label="Calculating impact…" /> : null}

        {error ? (
          <p role="alert" className="rounded-md border border-danger/30 bg-danger-subtle px-3 py-2 text-sm">
            {error}
          </p>
        ) : null}

        {stale ? (
          <div role="alert" className="rounded-md border border-warning/40 bg-warning/10 px-3 py-2 text-sm">
            <p className="font-medium">This preview is out of date.</p>
            <p className="mt-1">
              The configuration, leave or payroll data changed since you previewed it. Nothing was
              applied. Review a fresh preview before confirming.
            </p>
            <Button className="mt-2" size="sm" variant="outline" onClick={refresh}>
              Refresh preview
            </Button>
          </div>
        ) : null}

        {preview && !loading ? <PreviewBody preview={preview} /> : null}

        {preview && !loading && preview.requires_acknowledgement ? (
          <label className="flex items-start gap-2 text-sm">
            <input
              type="checkbox"
              className="mt-1"
              checked={acknowledged}
              onChange={(e) => setAcknowledged(e.target.checked)}
            />
            <span>
              I understand that existing leave days, locked attendance periods and payroll runs
              listed above will <strong>not</strong> be changed, and I have reviewed them.
            </span>
          </label>
        ) : null}

        <DialogFooter>
          <Button variant="outline" onClick={onClose} disabled={applying}>
            Back
          </Button>
          <Button onClick={() => void handleConfirm()} disabled={!canConfirm}>
            {applying ? "Applying…" : "Confirm change"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function PreviewBody({ preview }: { preview: ImpactPreview }) {
  const exact = preview.population.complete;
  const leave = preview.leave_impact;
  return (
    <div className="space-y-4 text-sm">
      <section aria-label="Summary">
        <p data-testid="impact-summary" className="font-medium text-foreground">
          {exact ? "" : "At least "}
          {preview.affected_employee_count}{" "}
          {preview.affected_employee_count === 1 ? "employee" : "employees"} affected on{" "}
          {preview.changed_date_count} {preview.changed_date_count === 1 ? "date" : "dates"} between{" "}
          {preview.window_from} and {preview.window_to}.
        </p>
        <p className="mt-1 text-xs text-foreground-muted">
          {preview.population.employees_analysed} of {preview.population.employees_in_scope}{" "}
          employees in scope were analysed
          {exact ? "." : " — the population is larger than the preview limit, so these counts are a lower bound."}
        </p>
      </section>

      {preview.warnings.length > 0 ? (
        <section aria-label="Notices">
          <ul className="space-y-1">
            {preview.warnings.map((w) => (
              <li key={w.code} className="rounded-md border border-border bg-accent px-3 py-2">
                <span className="font-medium">Notice: </span>
                {w.message}
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      {preview.incomplete_configuration.employees > 0 ? (
        <p role="status" className="rounded-md border border-warning/40 bg-warning/10 px-3 py-2">
          Incomplete configuration: {preview.incomplete_configuration.employees} employee(s) have{" "}
          {preview.incomplete_configuration.dates} date(s) with no work calendar, so their impact
          cannot be fully calculated.
        </p>
      ) : null}

      {preview.rows.length > 0 ? (
        <section aria-label="Changed dates">
          <h3 className="mb-1 font-medium">Changed dates</h3>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[32rem] text-left">
              <thead className="text-xs uppercase text-foreground-muted">
                <tr>
                  <th scope="col" className="py-1 pr-2">Date</th>
                  <th scope="col" className="py-1 pr-2">Currently</th>
                  <th scope="col" className="py-1 pr-2">After this change</th>
                  <th scope="col" className="py-1 text-right">Employees</th>
                </tr>
              </thead>
              <tbody>
                {preview.rows.slice(0, MAX_ROWS_SHOWN).map((row) => (
                  <tr key={`${row.date}-${describeSnapshot(row.previous)}-${describeSnapshot(row.proposed)}`} className="border-t border-border">
                    <td className="py-1 pr-2">{formatLongDate(row.date)}</td>
                    <td className="py-1 pr-2">{describeSnapshot(row.previous)}</td>
                    <td className="py-1 pr-2">{describeSnapshot(row.proposed)}</td>
                    <td className="py-1 text-right">{row.affected_employee_count}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {preview.rows_truncated || preview.rows.length > MAX_ROWS_SHOWN ? (
            <p className="mt-1 text-xs text-foreground-muted">
              Showing the first {Math.min(MAX_ROWS_SHOWN, preview.rows.length)} changes only.
            </p>
          ) : null}
        </section>
      ) : (
        <p>No employee&apos;s day classification changes in this window.</p>
      )}

      <section aria-label="Leave impact">
        <h3 className="mb-1 font-medium">Leave</h3>
        <p data-testid="leave-impact">
          {leave.approved_day_records} approved and {leave.pending_day_records} pending leave day
          record(s) fall on changed dates. Existing leave is never recalculated or approved or
          rejected by this change.
        </p>
        {leave.items.length > 0 ? (
          <ul className="mt-1 list-disc pl-5">
            {leave.items.slice(0, MAX_LEAVE_SHOWN).map((item) => (
              <li key={`${item.application_id}-${item.date}`}>
                {item.employee_code}, {formatLongDate(item.date)}:{" "}
                {item.status === "APPROVED" ? "Approved" : "Pending"} leave, day becomes{" "}
                {item.proposed_day_type ?? "unresolved"}
              </li>
            ))}
          </ul>
        ) : null}
        {leave.items_truncated || leave.items.length > MAX_LEAVE_SHOWN ? (
          <p className="mt-1 text-xs text-foreground-muted">More leave records are affected than shown.</p>
        ) : null}
      </section>

      {preview.protected_periods.length > 0 ? (
        <section aria-label="Protected periods">
          <h3 className="mb-1 font-medium">Locked attendance and payroll</h3>
          <ul className="list-disc pl-5" data-testid="protected-periods">
            {preview.protected_periods.map((p) => (
              <li key={p.id}>
                {p.kind === "ATTENDANCE_PERIOD" ? "Attendance period" : "Pay run"} {p.period_start}{" "}
                to {p.period_end} ({p.status.toLowerCase().replace("_", " ")}):{" "}
                {p.changed_dates_in_period} changed date(s). Not recalculated.
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      {preview.excluded_not_employed_employee_dates > 0 ? (
        <p className="text-xs text-foreground-muted">
          {preview.excluded_not_employed_employee_dates} employee-date(s) were left out because the
          employee was not employed on that date.
        </p>
      ) : null}
    </div>
  );
}
