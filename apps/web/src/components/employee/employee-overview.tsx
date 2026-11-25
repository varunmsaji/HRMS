"use client";

import { ArrowRight, Briefcase, Pencil, ScrollText, UserRound } from "lucide-react";
import type { ReactNode } from "react";

import { EmployeeSideCards } from "@/components/employee/employee-side-cards";
import type { EmployeeSectionKey } from "@/components/employee/employee-section-nav";
import { Button } from "@/components/ui/button";
import { ErrorState } from "@/components/common/error-state";
import { LoadingState } from "@/components/common/loading-state";
import { formatCompanyDate } from "@/lib/dates/company-date";
import { useCompanyDatePattern } from "@/lib/dates/use-company-date";
import { ApiError, describeApiError } from "@/lib/api/errors";
import type { AssignmentChangeType, Employee } from "@/lib/employee/types";
import { PAY_BASIS_LABELS, type PayBasis } from "@/lib/employee/types";
import type { EmployeeWorkSummary } from "@/lib/employee/use-employee-work-summary";

const WORK_LOCATION_LABELS: Record<string, string> = {
  OFFICE: "Office",
  WFH: "Work from home",
  HYBRID: "Hybrid",
  FIELD: "Field",
};

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

/** Sections with their own editors, offered on the Overview so everything editable is reachable
 * from here. The section itself shows what the user may do in it. */
const OTHER_EDITABLE_SECTIONS: ReadonlyArray<{ key: EmployeeSectionKey; label: string }> = [
  { key: "compensation", label: "Compensation" },
  { key: "salary", label: "Salary" },
  { key: "statutory", label: "Statutory" },
  { key: "banking", label: "Banking" },
  { key: "identity", label: "Identity" },
  { key: "experience", label: "Experience" },
  { key: "education", label: "Education" },
  { key: "dependents", label: "Dependents" },
  { key: "documents", label: "Documents" },
];

function Section({
  title,
  icon,
  description,
  action,
  children,
}: {
  title: string;
  icon: ReactNode;
  description?: string;
  action?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section aria-label={title} className="rounded-2xl border border-border bg-surface shadow-elevation-1">
      <header className="flex flex-wrap items-start justify-between gap-3 border-b border-border-subtle px-5 py-4">
        <div className="flex items-start gap-3">
          <span className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-primary-subtle text-primary">
            {icon}
          </span>
          <div>
            <h2 className="text-base font-semibold text-foreground">{title}</h2>
            {description ? <p className="text-xs text-foreground-muted">{description}</p> : null}
          </div>
        </div>
        {action ? <div className="flex flex-wrap items-center gap-2">{action}</div> : null}
      </header>
      <div className="px-5 py-2">{children}</div>
    </section>
  );
}

/** One labelled value on its own line, with an optional edit button at the end of the row. */
function Row({
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
  onEdit?: () => void;
}) {
  const hasValue = Boolean(value && value.trim());
  return (
    <div className="group flex min-h-[3rem] items-center gap-4 border-b border-border-subtle py-2.5 last:border-b-0">
      <dt className="w-36 shrink-0 text-sm text-foreground-muted sm:w-44">{label}</dt>
      <dd className="min-w-0 flex-1 text-sm">
        {hasValue ? (
          <span className={`break-words font-medium text-foreground ${mono ? "font-mono" : ""}`}>{value}</span>
        ) : (
          <span className="text-foreground-disabled">Not set</span>
        )}
        {hasValue && hint ? <span className="ml-1.5 text-foreground-muted">{hint}</span> : null}
      </dd>
      {onEdit ? (
        <button
          type="button"
          onClick={onEdit}
          aria-label={`Edit ${label.toLowerCase()}`}
          title={`Edit ${label.toLowerCase()}`}
          className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-foreground-muted transition-colors hover:bg-primary-subtle hover:text-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring sm:opacity-60 sm:group-hover:opacity-100 sm:focus-visible:opacity-100"
        >
          <Pencil className="h-3.5 w-3.5" aria-hidden="true" />
        </button>
      ) : null}
    </div>
  );
}

function SubHeading({ children }: { children: ReactNode }) {
  return (
    <h3 className="pb-1 pt-4 text-2xs font-semibold uppercase tracking-wider text-foreground-muted first:pt-2">
      {children}
    </h3>
  );
}

/** A filled-in fact in the personal grid. Empty facts are not shown here; they are listed once,
 * below, so the card is not a column of "Not provided". */
function Fact({ label, value, hint }: { label: string; value: string; hint?: string | null }) {
  return (
    <div className="min-w-0 rounded-xl bg-surface-secondary/60 px-3.5 py-2.5">
      <dt className="text-xs text-foreground-muted">{label}</dt>
      <dd className="mt-0.5 break-words text-sm font-medium text-foreground">
        {value}
        {hint ? <span className="ml-1.5 font-normal text-foreground-muted">{hint}</span> : null}
      </dd>
    </div>
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
  actions,
}: {
  employee: Employee;
  work: EmployeeWorkSummary | null;
  workLoading: boolean;
  workError: ApiError | null;
  actions?: OverviewActions;
}) {
  const datePattern = useCompanyDatePattern();
  const age = employee.date_of_birth ? ageOn(employee.date_of_birth) : null;
  const legalName = [employee.first_name, employee.middle_name, employee.last_name].filter(Boolean).join(" ");

  const editDetails = actions?.canEditDetails ? actions.onEditDetails : undefined;
  const changeWork = (type: AssignmentChangeType | "") =>
    actions?.canChangeWork ? () => actions.onChangeWork(type) : undefined;
  const openEmployment = actions ? () => actions.onOpenSection("employment") : undefined;

  const personal: Array<{ label: string; value: string | null | undefined; hint?: string | null }> = [
    { label: "Legal name", value: legalName },
    ...(employee.display_name?.trim() && employee.display_name.trim() !== legalName
      ? [{ label: "Display name", value: employee.display_name }]
      : []),
    {
      label: "Date of birth",
      value: employee.date_of_birth ? formatCompanyDate(employee.date_of_birth, datePattern) : null,
      hint: age !== null ? `${age} yrs` : null,
    },
    { label: "Gender", value: employee.gender },
    { label: "Marital status", value: employee.marital_status },
    { label: "Blood group", value: employee.blood_group },
    { label: "Nationality", value: employee.nationality },
  ];
  const contact: Array<{ label: string; value: string | null | undefined }> = [
    { label: "Personal email", value: employee.personal_email },
    { label: "Personal mobile", value: employee.personal_mobile },
  ];
  const filled = <T extends { value: string | null | undefined }>(list: T[]) =>
    list.filter((f): f is T & { value: string } => Boolean(f.value && f.value.trim()));
  const missing = [...personal, ...contact].filter((f) => !(f.value && f.value.trim())).map((f) => f.label);

  const editButton = (label: string) =>
    editDetails ? (
      <Button type="button" variant="outline" size="sm" onClick={editDetails} aria-label={label}>
        <Pencil className="mr-1.5 h-3.5 w-3.5" aria-hidden="true" />
        Edit
      </Button>
    ) : null;

  return (
    <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_20rem]">
      <div className="grid min-w-0 content-start gap-6">
        <Section
          title="Work and role"
          icon={<Briefcase className="h-4 w-4" aria-hidden="true" />}
          description="Where they sit, who they report to and when they work."
          action={
            actions?.canChangeWork ? (
              <>
                <Button type="button" variant="outline" size="sm" onClick={() => actions.onChangeWork("SHIFT_CHANGE")}>
                  Change shift
                </Button>
                <Button type="button" size="sm" onClick={() => actions.onChangeWork("")}>
                  Change assignment
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
                  : describeApiError(workError)
              }
            />
          ) : null}

          {!workLoading && !workError && work ? (
            <>
              <SubHeading>Role</SubHeading>
              <dl>
                <Row label="Designation" value={work.designation} onEdit={changeWork("PROMOTION")} />
                <Row label="Department" value={work.department} onEdit={changeWork("TRANSFER")} />
                <Row label="Reporting manager" value={work.manager?.name} onEdit={changeWork("MANAGER_CHANGE")} />
              </dl>

              <SubHeading>Place and time</SubHeading>
              <dl>
                <Row label="Branch" value={work.branch} onEdit={changeWork("TRANSFER")} />
                <Row
                  label="Work location"
                  value={
                    work.assignment?.work_location_type
                      ? (WORK_LOCATION_LABELS[work.assignment.work_location_type] ??
                        work.assignment.work_location_type)
                      : null
                  }
                  onEdit={changeWork("TRANSFER")}
                />
                <Row label="Shift" value={work.shift} onEdit={changeWork("SHIFT_CHANGE")} />
              </dl>

              <div className="mt-2 flex flex-wrap items-center justify-between gap-2 border-t border-border-subtle pt-2">
                <SubHeading>Employment</SubHeading>
                {openEmployment ? (
                  <Button type="button" variant="ghost" size="sm" onClick={openEmployment}>
                    <ScrollText className="mr-1.5 h-3.5 w-3.5" aria-hidden="true" />
                    Edit employment
                  </Button>
                ) : null}
              </div>
              <dl>
                <Row label="Company" value={work.company} />
                <Row
                  label="Joining date"
                  value={work.employment ? formatCompanyDate(work.employment.joining_date, datePattern) : null}
                  onEdit={openEmployment}
                />
                <Row
                  label="Probation ends"
                  value={
                    work.employment?.probation_end_date
                      ? formatCompanyDate(work.employment.probation_end_date, datePattern)
                      : null
                  }
                  onEdit={openEmployment}
                />
                <Row
                  label="Pay basis"
                  value={
                    work.employment
                      ? (PAY_BASIS_LABELS[work.employment.pay_basis as PayBasis] ?? work.employment.pay_basis)
                      : null
                  }
                  onEdit={openEmployment}
                />
              </dl>

              {!work.employment ? (
                <p className="my-3 rounded-xl border border-dashed border-border bg-surface-secondary/50 px-3.5 py-2.5 text-xs text-foreground-secondary">
                  This employee has no employment record yet. Add one from the Employment section.
                </p>
              ) : null}
            </>
          ) : null}
        </Section>

        <Section
          title="Personal details"
          icon={<UserRound className="h-4 w-4" aria-hidden="true" />}
          description="Identity and contact details."
          action={editButton("Edit personal details")}
        >
          <dl className="grid grid-cols-1 gap-2 py-3 sm:grid-cols-2 2xl:grid-cols-3">
            {filled(personal).map((f) => (
              <Fact key={f.label} label={f.label} value={f.value} hint={f.hint} />
            ))}
          </dl>
          {filled(contact).length > 0 ? (
            <section aria-label="Contact">
              <SubHeading>Contact</SubHeading>
              {/* The email gets the room it needs; a mobile number is short. */}
              <dl className="grid grid-cols-1 gap-2 pb-3 lg:grid-cols-[minmax(0,1fr)_auto]">
                {filled(contact).map((f) => (
                  <Fact key={f.label} label={f.label} value={f.value} />
                ))}
              </dl>
            </section>
          ) : null}
          {missing.length > 0 ? (
            <div className="mb-3 flex flex-wrap items-center justify-between gap-2 rounded-xl border border-dashed border-border px-3.5 py-2.5">
              <p className="text-xs text-foreground-secondary">
                <span className="font-medium text-foreground">Not added yet:</span> {missing.join(", ")}
              </p>
              {editDetails ? (
                <button
                  type="button"
                  onClick={editDetails}
                  className="text-xs font-medium text-primary hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                >
                  Add details
                </button>
              ) : null}
            </div>
          ) : null}
        </Section>

        {actions ? (
          <section
            aria-label="More to edit"
            className="rounded-2xl border border-border bg-surface px-5 py-4 shadow-elevation-1"
          >
            <h2 className="text-sm font-semibold text-foreground">More to edit</h2>
            <p className="mt-0.5 text-xs text-foreground-muted">
              Each opens its own section. What you can change there depends on your access.
            </p>
            <ul className="mt-3 flex flex-wrap gap-2">
              {OTHER_EDITABLE_SECTIONS.map((section) => (
                <li key={section.key}>
                  <button
                    type="button"
                    onClick={() => actions.onOpenSection(section.key)}
                    className="group inline-flex items-center gap-1.5 rounded-full border border-border bg-surface px-3 py-1.5 text-sm font-medium text-foreground-secondary transition-colors hover:border-primary-border hover:bg-primary-subtle hover:text-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                  >
                    {section.label}
                    <ArrowRight
                      className="h-3.5 w-3.5 text-foreground-muted transition-transform group-hover:translate-x-0.5 group-hover:text-primary"
                      aria-hidden="true"
                    />
                  </button>
                </li>
              ))}
            </ul>
          </section>
        ) : null}
      </div>
      <EmployeeSideCards employeeId={employee.id} />
    </div>
  );
}
