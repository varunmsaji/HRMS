"use client";

import { CalendarDays, CheckCircle2, FileText, FolderOpen, Hourglass, XCircle } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";

import { CompanyDate } from "@/components/common/company-date";
import { apiClient } from "@/lib/api/client";
import { businessToday } from "@/lib/attendance/format";
import { useAuth } from "@/lib/auth/auth-context";
import type { EmployeeDocument } from "@/lib/employee/types";
import type { LeaveApplication } from "@/lib/leave-application/types";
import type { LeaveBalance } from "@/lib/leave-ledger/types";

function SideCard({ title, icon, action, children }: { title: string; icon: React.ReactNode; action?: React.ReactNode; children: React.ReactNode }) {
  return (
    <section aria-label={title} className="rounded-2xl border border-border bg-surface p-5 shadow-elevation-1">
      <div className="mb-4 flex items-center justify-between gap-3">
        <h2 className="flex items-center gap-2 text-base font-semibold text-foreground">
          <span className="text-primary">{icon}</span>
          {title}
        </h2>
        {action}
      </div>
      {children}
    </section>
  );
}

function days(value: string): string {
  return String(Number(value));
}

/** Leave balances, the next approved leave, and document status — beside the overview cards.
 * Each card is fetched on its own and omitted when the viewer can't read it, never shown empty. */
export function EmployeeSideCards({ employeeId }: { employeeId: string }) {
  const { user } = useAuth();
  const today = businessToday(user?.company_timezone ?? "Asia/Kolkata");
  const [balances, setBalances] = useState<LeaveBalance[] | null>(null);
  const [nextLeave, setNextLeave] = useState<LeaveApplication | null | undefined>(undefined);
  const [documents, setDocuments] = useState<EmployeeDocument[] | null>(null);

  useEffect(() => {
    let cancelled = false;
    apiClient
      .get<LeaveBalance[]>(`/leave-balances?employee_id=${employeeId}`)
      .then((d) => !cancelled && setBalances(d))
      .catch(() => {});
    apiClient
      .getList<LeaveApplication>("/leave-applications", {
        employee_id: employeeId,
        application_status: "APPROVED",
        date_from: today,
        per_page: 50,
      })
      .then(({ data }) => {
        if (cancelled) return;
        const upcoming = data.filter((a) => a.end_date >= today).sort((a, b) => a.start_date.localeCompare(b.start_date));
        setNextLeave(upcoming[0] ?? null);
      })
      .catch(() => {});
    apiClient
      .get<EmployeeDocument[]>(`/employees/${employeeId}/documents`)
      .then((d) => !cancelled && setDocuments(d))
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [employeeId, today]);

  const verified = documents?.filter((d) => d.status === "VERIFIED").length ?? 0;

  return (
    <div className="space-y-6">
      {balances ? (
        <SideCard
          title="Leave balances"
          icon={<CalendarDays className="h-4 w-4" aria-hidden="true" />}
          action={
            <Link href="/app/leave-balances" className="text-xs font-medium text-primary hover:underline">
              View ledger
            </Link>
          }
        >
          {balances.length === 0 ? (
            <p className="text-sm text-foreground-muted">No balance-tracked leave types.</p>
          ) : (
            <ul className="space-y-3">
              {balances.map((b) => (
                <li key={b.leave_type_id} className="flex items-center justify-between gap-3 text-sm">
                  <span className="text-foreground-secondary">
                    {b.leave_type_name} <span className="text-foreground-muted">({b.leave_type_code})</span>
                  </span>
                  <span className="font-semibold tabular-nums text-foreground">
                    {days(b.balance)} <span className="font-normal text-foreground-muted">days</span>
                    {Number(b.reserved_balance) > 0 ? (
                      <span className="ml-1 font-normal text-warning">({days(b.reserved_balance)} pending)</span>
                    ) : null}
                  </span>
                </li>
              ))}
            </ul>
          )}
          {nextLeave ? (
            <p className="mt-4 rounded-xl bg-info-subtle p-3 text-xs text-foreground-secondary">
              <span className="block font-semibold text-foreground">Next approved leave</span>
              <CompanyDate value={nextLeave.start_date} />
              {nextLeave.end_date !== nextLeave.start_date ? (
                <>
                  {" – "}
                  <CompanyDate value={nextLeave.end_date} />
                </>
              ) : null}{" "}
              ({days(nextLeave.total_days)} {Number(nextLeave.total_days) === 1 ? "day" : "days"})
            </p>
          ) : null}
        </SideCard>
      ) : null}

      {documents ? (
        <SideCard
          title={`Documents (${verified} of ${documents.length} verified)`}
          icon={<FolderOpen className="h-4 w-4" aria-hidden="true" />}
        >
          {documents.length === 0 ? (
            <p className="text-sm text-foreground-muted">No documents uploaded.</p>
          ) : (
            <ul className="space-y-3">
              {documents.slice(0, 5).map((d) => (
                <li key={d.id} className="flex items-center gap-3 text-sm">
                  <FileText className="h-4 w-4 shrink-0 text-foreground-muted" aria-hidden="true" />
                  <span className="min-w-0 flex-1">
                    <span className="block truncate font-medium text-foreground">{d.original_filename}</span>
                    <span className="block text-xs text-foreground-muted">{d.document_type.replaceAll("_", " ").toLowerCase()}</span>
                  </span>
                  {d.status === "VERIFIED" ? (
                    <CheckCircle2 className="h-4 w-4 shrink-0 text-success" aria-label="Verified" />
                  ) : d.status === "REJECTED" ? (
                    <XCircle className="h-4 w-4 shrink-0 text-danger" aria-label="Rejected" />
                  ) : (
                    <Hourglass className="h-4 w-4 shrink-0 text-warning" aria-label="Pending verification" />
                  )}
                </li>
              ))}
            </ul>
          )}
          {documents.length > 5 ? (
            <p className="mt-3 text-xs text-foreground-muted">Showing 5 of {documents.length}. See the Documents tab.</p>
          ) : null}
        </SideCard>
      ) : null}
    </div>
  );
}
