"use client";

import { Building2, CalendarCheck, Mail, MapPin, Phone, UserRound } from "lucide-react";
import Link from "next/link";
import type { ReactNode } from "react";

import { CompanyDate } from "@/components/common/company-date";
import { EmployeeAvatar } from "@/components/employee/employee-identity";
import { EmployeeStatusBadge } from "@/components/employee/employee-status-badge";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { employeeFullName } from "@/lib/employee/names";
import type { Employee } from "@/lib/employee/types";
import type { EmployeeWorkSummary } from "@/lib/employee/use-employee-work-summary";

function Fact({ icon, label, children }: { icon: ReactNode; label: string; children: ReactNode }) {
  return (
    <div className="flex min-w-0 items-start gap-2.5">
      <span className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-surface-secondary text-foreground-muted">
        {icon}
      </span>
      <div className="min-w-0">
        <dt className="text-2xs font-medium uppercase tracking-wider text-foreground-muted">{label}</dt>
        <dd className="truncate text-sm font-medium text-foreground">{children}</dd>
      </div>
    </div>
  );
}

function Empty() {
  return <span className="font-normal text-foreground-disabled">—</span>;
}

/** The top of an employee's profile: who they are, where they sit, and how to reach them. */
export function EmployeeProfileHero({
  employee,
  work,
  workLoading,
  actions,
}: {
  employee: Employee;
  work: EmployeeWorkSummary | null;
  workLoading: boolean;
  actions?: ReactNode;
}) {
  const name = employeeFullName(employee) || employee.employee_code;
  const role = [work?.designation, work?.department].filter(Boolean).join(" · ");

  return (
    <section
      aria-label="Employee summary"
      className="overflow-hidden rounded-2xl border border-border bg-surface shadow-elevation-1"
    >
      <div className="h-16 bg-gradient-to-r from-primary-subtle via-primary-subtle/60 to-transparent sm:h-20" />
      <div className="px-5 pb-5 sm:px-6">
        <div className="-mt-10 flex flex-wrap items-end justify-between gap-4">
          <div className="flex min-w-0 items-end gap-4">
            {employee.photo_url ? (
              // eslint-disable-next-line @next/next/no-img-element -- arbitrary uploaded URL
              <img
                src={employee.photo_url}
                alt=""
                className="h-20 w-20 shrink-0 rounded-2xl border-4 border-surface object-cover shadow-elevation-1"
              />
            ) : (
              <EmployeeAvatar
                name={name}
                code={employee.employee_code}
                className="h-20 w-20 rounded-2xl border-4 border-surface text-2xl shadow-elevation-1"
              />
            )}
            <div className="min-w-0 pb-1">
              <div className="flex flex-wrap items-center gap-2">
                <h1 className="truncate text-xl font-semibold tracking-tight text-foreground">{name}</h1>
                <EmployeeStatusBadge status={employee.status} />
                {!employee.is_active ? <Badge variant="outline">Inactive</Badge> : null}
              </div>
              <div className="mt-0.5 flex flex-wrap items-center gap-x-2 text-sm text-foreground-secondary">
                <span className="font-mono text-xs text-foreground-muted">{employee.employee_code}</span>
                {workLoading ? (
                  <Skeleton className="h-4 w-40" />
                ) : role ? (
                  <>
                    <span aria-hidden="true" className="text-foreground-muted">·</span>
                    <span className="truncate">{role}</span>
                  </>
                ) : null}
              </div>
            </div>
          </div>
          {actions ? <div className="flex flex-wrap items-center gap-2 pb-1">{actions}</div> : null}
        </div>

        <dl className="mt-5 grid gap-4 border-t border-border pt-5 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5">
          <Fact icon={<Mail className="h-3.5 w-3.5" aria-hidden="true" />} label="Email">
            {employee.personal_email ? (
              <a href={`mailto:${employee.personal_email}`} className="hover:text-primary hover:underline">
                {employee.personal_email}
              </a>
            ) : (
              <Empty />
            )}
          </Fact>
          <Fact icon={<Phone className="h-3.5 w-3.5" aria-hidden="true" />} label="Mobile">
            {employee.personal_mobile ? (
              <a href={`tel:${employee.personal_mobile}`} className="tabular-nums hover:text-primary hover:underline">
                {employee.personal_mobile}
              </a>
            ) : (
              <Empty />
            )}
          </Fact>
          <Fact icon={<UserRound className="h-3.5 w-3.5" aria-hidden="true" />} label="Reports to">
            {workLoading ? (
              <Skeleton className="h-4 w-24" />
            ) : work?.manager ? (
              <Link href={`/app/employees/${work.manager.id}`} className="hover:text-primary hover:underline">
                {work.manager.name}
              </Link>
            ) : (
              <Empty />
            )}
          </Fact>
          <Fact icon={<MapPin className="h-3.5 w-3.5" aria-hidden="true" />} label="Branch">
            {workLoading ? <Skeleton className="h-4 w-24" /> : work?.branch ?? <Empty />}
          </Fact>
          <Fact icon={<CalendarCheck className="h-3.5 w-3.5" aria-hidden="true" />} label="Joined">
            {workLoading ? (
              <Skeleton className="h-4 w-24" />
            ) : work?.employment ? (
              <CompanyDate value={work.employment.joining_date} />
            ) : (
              <Empty />
            )}
          </Fact>
        </dl>
        {!workLoading && work?.company ? (
          <p className="mt-4 inline-flex items-center gap-1.5 text-xs text-foreground-muted">
            <Building2 className="h-3.5 w-3.5" aria-hidden="true" />
            {work.company}
          </p>
        ) : null}
      </div>
    </section>
  );
}
