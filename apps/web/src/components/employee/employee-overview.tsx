"use client";

import { Briefcase, Contact, UserRound } from "lucide-react";
import type { ReactNode } from "react";

import { EmployeeSideCards } from "@/components/employee/employee-side-cards";
import { ErrorState } from "@/components/common/error-state";
import { LoadingState } from "@/components/common/loading-state";
import { formatCompanyDate } from "@/lib/dates/company-date";
import { useCompanyDatePattern } from "@/lib/dates/use-company-date";
import { ApiError } from "@/lib/api/errors";
import type { Employee } from "@/lib/employee/types";
import { PAY_BASIS_LABELS, type PayBasis } from "@/lib/employee/types";
import type { EmployeeWorkSummary } from "@/lib/employee/use-employee-work-summary";

const WORK_LOCATION_LABELS: Record<string, string> = {
  OFFICE: "Office",
  WFH: "Work from home",
  HYBRID: "Hybrid",
  FIELD: "Field",
};

function DetailField({
  label,
  value,
  hint,
  mono = false,
}: {
  label: string;
  value: string | null | undefined;
  hint?: string | null;
  mono?: boolean;
}) {
  const hasValue = Boolean(value && value.trim());
  return (
    <div className="min-w-0">
      <dt className="text-xs font-medium text-foreground-muted">{label}</dt>
      <dd
        className={`mt-1 break-words text-sm ${
          hasValue ? "font-medium text-foreground" : "text-foreground-disabled"
        } ${mono && hasValue ? "font-mono" : ""}`}
      >
        {hasValue ? value : "Not provided"}
        {hasValue && hint ? <span className="ml-1.5 font-normal text-foreground-muted">{hint}</span> : null}
      </dd>
    </div>
  );
}

function OverviewCard({ title, icon, children }: { title: string; icon: ReactNode; children: ReactNode }) {
  return (
    <section aria-label={title} className="rounded-2xl border border-border bg-surface p-5 shadow-elevation-1">
      <h2 className="mb-4 flex items-center gap-2 text-base font-semibold text-foreground">
        <span className="text-primary">{icon}</span>
        {title}
      </h2>
      {children}
    </section>
  );
}

function ageOn(dateOfBirth: string, today = new Date()): number | null {
  const [y, m, d] = dateOfBirth.split("-").map(Number);
  if (!y || !m || !d) return null;
  let age = today.getFullYear() - y;
  if (today.getMonth() + 1 < m || (today.getMonth() + 1 === m && today.getDate() < d)) age -= 1;
  return age >= 0 ? age : null;
}

export function EmployeeOverview({
  employee,
  work,
  workLoading,
  workError,
}: {
  employee: Employee;
  work: EmployeeWorkSummary | null;
  workLoading: boolean;
  workError: ApiError | null;
}) {
  const datePattern = useCompanyDatePattern();
  const age = employee.date_of_birth ? ageOn(employee.date_of_birth) : null;
  const legalName = [employee.first_name, employee.middle_name, employee.last_name].filter(Boolean).join(" ");

  return (
    <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_20rem]">
      <div className="grid content-start gap-6">
        <OverviewCard title="Personal details" icon={<UserRound className="h-4 w-4" aria-hidden="true" />}>
          <dl className="grid grid-cols-1 gap-x-6 gap-y-4 sm:grid-cols-2 2xl:grid-cols-3">
            <DetailField label="Legal name" value={legalName} />
            {employee.display_name?.trim() && employee.display_name.trim() !== legalName ? (
              <DetailField label="Display name" value={employee.display_name} />
            ) : null}
            <DetailField label="Employee code" value={employee.employee_code} mono />
            <DetailField
              label="Date of birth"
              value={employee.date_of_birth ? formatCompanyDate(employee.date_of_birth, datePattern) : null}
              hint={age !== null ? `(${age} yrs)` : null}
            />
            <DetailField label="Gender" value={employee.gender} />
            <DetailField label="Marital status" value={employee.marital_status} />
            <DetailField label="Blood group" value={employee.blood_group} />
            <DetailField label="Nationality" value={employee.nationality} />
          </dl>
        </OverviewCard>

        <OverviewCard title="Contact" icon={<Contact className="h-4 w-4" aria-hidden="true" />}>
          <dl className="grid grid-cols-1 gap-x-6 gap-y-4 sm:grid-cols-2">
            <DetailField label="Personal email" value={employee.personal_email} />
            <DetailField label="Personal mobile" value={employee.personal_mobile} />
          </dl>
        </OverviewCard>

        <OverviewCard title="Current work" icon={<Briefcase className="h-4 w-4" aria-hidden="true" />}>
          {workLoading ? <LoadingState label="Loading work information…" /> : null}
          {workError && !workLoading ? (
            <ErrorState
              message={
                workError.status === 403
                  ? "You do not have permission to view this employee's work information."
                  : workError.message
              }
            />
          ) : null}

          {!workLoading && !workError && work ? (
            <>
              <dl className="grid grid-cols-1 gap-x-6 gap-y-4 sm:grid-cols-2 2xl:grid-cols-3">
                <DetailField label="Company" value={work.company} />
                <DetailField label="Designation" value={work.designation} />
                <DetailField label="Department" value={work.department} />
                <DetailField label="Branch" value={work.branch} />
                <DetailField label="Reporting manager" value={work.manager?.name} />
                <DetailField label="Shift" value={work.shift} />
                <DetailField
                  label="Work location"
                  value={
                    work.assignment?.work_location_type
                      ? (WORK_LOCATION_LABELS[work.assignment.work_location_type] ??
                        work.assignment.work_location_type)
                      : null
                  }
                />
                <DetailField
                  label="Joining date"
                  value={
                    work.employment ? formatCompanyDate(work.employment.joining_date, datePattern) : null
                  }
                />
                <DetailField
                  label="Probation ends"
                  value={
                    work.employment?.probation_end_date
                      ? formatCompanyDate(work.employment.probation_end_date, datePattern)
                      : null
                  }
                />
                <DetailField
                  label="Pay basis"
                  value={
                    work.employment
                      ? (PAY_BASIS_LABELS[work.employment.pay_basis as PayBasis] ?? work.employment.pay_basis)
                      : null
                  }
                />
              </dl>

              {!work.employment ? (
                <p className="mt-5 rounded-xl border border-dashed border-border bg-surface-secondary/50 px-3.5 py-2.5 text-xs text-foreground-secondary">
                  This employee has no employment record yet — add one from the Employment section.
                </p>
              ) : null}
            </>
          ) : null}
        </OverviewCard>
      </div>
      <EmployeeSideCards employeeId={employee.id} />
    </div>
  );
}
