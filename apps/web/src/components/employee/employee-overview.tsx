"use client";

import { Briefcase, Contact, Pencil, UserRound } from "lucide-react";
import type { ReactNode } from "react";

import { EmployeeSideCards } from "@/components/employee/employee-side-cards";
import type { EmployeeSectionKey } from "@/components/employee/employee-section-nav";
import { Button } from "@/components/ui/button";
import { ErrorState } from "@/components/common/error-state";
import { LoadingState } from "@/components/common/loading-state";
import { formatCompanyDate } from "@/lib/dates/company-date";
import { useCompanyDatePattern } from "@/lib/dates/use-company-date";
import { ApiError } from "@/lib/api/errors";
import type { AssignmentChangeType, Employee } from "@/lib/employee/types";
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
  onEdit,
}: {
  label: string;
  value: string | null | undefined;
  hint?: string | null;
  mono?: boolean;
  /** When given, a small pencil next to the label opens the editor for this value. */
  onEdit?: () => void;
}) {
  const hasValue = Boolean(value && value.trim());
  return (
    <div className="min-w-0">
      <dt className="flex items-center gap-1 text-xs font-medium text-foreground-muted">
        {label}
        {onEdit ? (
          <button
            type="button"
            onClick={onEdit}
            aria-label={`Edit ${label.toLowerCase()}`}
            title={`Edit ${label.toLowerCase()}`}
            className="rounded p-0.5 text-foreground-muted hover:bg-muted hover:text-primary focus-visible:outline focus-visible:outline-2 focus-visible:outline-primary"
          >
            <Pencil className="h-3 w-3" aria-hidden="true" />
          </button>
        ) : null}
      </dt>
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

function OverviewCard({
  title,
  icon,
  action,
  children,
}: {
  title: string;
  icon: ReactNode;
  action?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section aria-label={title} className="rounded-2xl border border-border bg-surface p-5 shadow-elevation-1">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-2">
        <h2 className="flex items-center gap-2 text-base font-semibold text-foreground">
          <span className="text-primary">{icon}</span>
          {title}
        </h2>
        {action ? <div className="flex flex-wrap items-center gap-2">{action}</div> : null}
      </div>
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

/** What the Overview lets you change from where you are. Left out entirely on the employee's own
 * profile, which is read-only; each action is also hidden when the user may not do it. */
export interface OverviewActions {
  canEditDetails: boolean;
  canChangeWork: boolean;
  /** Opens the personal-details editor. */
  onEditDetails: () => void;
  /** Opens the assignment-change dialog, with a change type pre-selected where one fits. */
  onChangeWork: (changeType: AssignmentChangeType | "") => void;
  /** Jumps to a section that has its own editor. */
  onOpenSection: (section: EmployeeSectionKey) => void;
}

/** Sections with their own editors, listed on the Overview so everything editable is reachable
 * from here. The section itself shows what the user may do in it. */
const OTHER_EDITABLE_SECTIONS: ReadonlyArray<{ key: EmployeeSectionKey; label: string; hint: string }> = [
  { key: "employment", label: "Employment", hint: "Joining date, probation, pay basis, termination" },
  { key: "compensation", label: "Compensation", hint: "CTC and revisions" },
  { key: "salary", label: "Salary", hint: "Salary structure and lines" },
  { key: "statutory", label: "Statutory", hint: "PAN, UAN, PF, ESI" },
  { key: "banking", label: "Banking", hint: "Bank accounts for payroll" },
  { key: "identity", label: "Identity", hint: "Identity documents" },
  { key: "experience", label: "Experience", hint: "Previous employment" },
  { key: "education", label: "Education", hint: "Qualifications" },
  { key: "dependents", label: "Dependents", hint: "Family members" },
  { key: "documents", label: "Documents", hint: "Uploaded files" },
];

export function EmployeeOverview({
  employee,
  work,
  workLoading,
  workError,
  actions,
}: {
  employee: Employee;
  work: EmployeeWorkSummary | null;
  workLoading: boolean;
  workError: ApiError | null;
  actions?: OverviewActions;
}) {
  const editDetails = actions?.canEditDetails ? actions.onEditDetails : undefined;
  const changeWork = (type: AssignmentChangeType | "") =>
    actions?.canChangeWork ? () => actions.onChangeWork(type) : undefined;
  const openEmployment = actions ? () => actions.onOpenSection("employment") : undefined;
  const datePattern = useCompanyDatePattern();
  const age = employee.date_of_birth ? ageOn(employee.date_of_birth) : null;
  const legalName = [employee.first_name, employee.middle_name, employee.last_name].filter(Boolean).join(" ");

  return (
    <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_20rem]">
      <div className="grid content-start gap-6">
        <OverviewCard
          title="Personal details"
          icon={<UserRound className="h-4 w-4" aria-hidden="true" />}
          action={
            editDetails ? (
              <Button type="button" variant="outline" size="sm" onClick={editDetails}>
                <Pencil className="mr-1.5 h-3.5 w-3.5" aria-hidden="true" />
                Edit
              </Button>
            ) : null
          }
        >
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

        <OverviewCard
          title="Contact"
          icon={<Contact className="h-4 w-4" aria-hidden="true" />}
          action={
            editDetails ? (
              <Button type="button" variant="outline" size="sm" onClick={editDetails}>
                <Pencil className="mr-1.5 h-3.5 w-3.5" aria-hidden="true" />
                Edit
              </Button>
            ) : null
          }
        >
          <dl className="grid grid-cols-1 gap-x-6 gap-y-4 sm:grid-cols-2">
            <DetailField label="Personal email" value={employee.personal_email} />
            <DetailField label="Personal mobile" value={employee.personal_mobile} />
          </dl>
        </OverviewCard>

        <OverviewCard
          title="Current work"
          icon={<Briefcase className="h-4 w-4" aria-hidden="true" />}
          action={
            actions ? (
              <>
                {actions.canChangeWork ? (
                  <Button type="button" variant="outline" size="sm" onClick={() => actions.onChangeWork("SHIFT_CHANGE")}>
                    Change shift
                  </Button>
                ) : null}
                {actions.canChangeWork ? (
                  <Button type="button" variant="outline" size="sm" onClick={() => actions.onChangeWork("")}>
                    <Pencil className="mr-1.5 h-3.5 w-3.5" aria-hidden="true" />
                    Change assignment
                  </Button>
                ) : null}
                <Button type="button" variant="outline" size="sm" onClick={openEmployment}>
                  Edit employment
                </Button>
              </>
            ) : null
          }
        >
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
                <DetailField label="Designation" value={work.designation} onEdit={changeWork("PROMOTION")} />
                <DetailField label="Department" value={work.department} onEdit={changeWork("TRANSFER")} />
                <DetailField label="Branch" value={work.branch} onEdit={changeWork("TRANSFER")} />
                <DetailField label="Reporting manager" value={work.manager?.name} onEdit={changeWork("MANAGER_CHANGE")} />
                <DetailField label="Shift" value={work.shift} onEdit={changeWork("SHIFT_CHANGE")} />
                <DetailField
                  label="Work location"
                  onEdit={changeWork("TRANSFER")}
                  value={
                    work.assignment?.work_location_type
                      ? (WORK_LOCATION_LABELS[work.assignment.work_location_type] ??
                        work.assignment.work_location_type)
                      : null
                  }
                />
                <DetailField
                  label="Joining date"
                  onEdit={openEmployment}
                  value={
                    work.employment ? formatCompanyDate(work.employment.joining_date, datePattern) : null
                  }
                />
                <DetailField
                  label="Probation ends"
                  onEdit={openEmployment}
                  value={
                    work.employment?.probation_end_date
                      ? formatCompanyDate(work.employment.probation_end_date, datePattern)
                      : null
                  }
                />
                <DetailField
                  label="Pay basis"
                  onEdit={openEmployment}
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

        {actions ? (
          <OverviewCard title="Other details" icon={<Pencil className="h-4 w-4" aria-hidden="true" />}>
            <p className="mb-3 text-xs text-foreground-secondary">
              Open a section to view or change it. What you can change in each depends on your access.
            </p>
            <ul className="grid grid-cols-1 gap-2 sm:grid-cols-2">
              {OTHER_EDITABLE_SECTIONS.map((section) => (
                <li key={section.key}>
                  <button
                    type="button"
                    onClick={() => actions.onOpenSection(section.key)}
                    className="flex w-full items-center justify-between gap-3 rounded-xl border border-border px-3.5 py-2.5 text-left transition-colors hover:bg-muted focus-visible:outline focus-visible:outline-2 focus-visible:outline-primary"
                  >
                    <span className="min-w-0">
                      <span className="block text-sm font-medium text-foreground">{section.label}</span>{" "}
                      <span className="block truncate text-xs text-foreground-muted">{section.hint}</span>
                    </span>
                    <Pencil className="h-3.5 w-3.5 shrink-0 text-foreground-muted" aria-hidden="true" />
                    <span className="sr-only">Edit {section.label.toLowerCase()}</span>
                  </button>
                </li>
              ))}
            </ul>
          </OverviewCard>
        ) : null}
      </div>
      <EmployeeSideCards employeeId={employee.id} />
    </div>
  );
}
