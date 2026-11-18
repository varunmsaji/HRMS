"use client";

import { Briefcase, Building2, CalendarCheck, Clock3, Hash, Mail, MapPin, Phone, UserRound } from "lucide-react";
import Link from "next/link";
import type { ReactNode } from "react";

import { CompanyDate } from "@/components/common/company-date";
import { computeInitials } from "@/components/employee/employee-identity";
import { EmployeeStatusBadge } from "@/components/employee/employee-status-badge";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { employeeFullName } from "@/lib/employee/names";
import type { Employee } from "@/lib/employee/types";
import type { EmployeeWorkSummary } from "@/lib/employee/use-employee-work-summary";
import { cn } from "@/lib/utils";

/** One tint per person, picked from the employee code so it never changes between visits. The
 * class strings are written out in full so Tailwind keeps them. */
const AVATAR_TINTS = [
  "bg-primary-subtle text-primary ring-primary-border",
  "bg-info-subtle text-info ring-info-border",
  "bg-success-subtle text-success ring-success-border",
  "bg-warning-subtle text-warning ring-warning-border",
  "bg-holiday-subtle text-holiday ring-holiday-border",
  "bg-on-leave-subtle text-on-leave ring-on-leave-border",
] as const;

function tintFor(seed: string): string {
  let hash = 0;
  for (let i = 0; i < seed.length; i += 1) hash = (hash * 31 + seed.charCodeAt(i)) | 0;
  return AVATAR_TINTS[Math.abs(hash) % AVATAR_TINTS.length];
}

const WORK_LOCATION_LABELS: Record<string, string> = {
  OFFICE: "Office",
  WFH: "Work from home",
  HYBRID: "Hybrid",
  FIELD: "Field",
};

/** "6 yrs 2 mos" from a joining date (YYYY-MM-DD), or null before the joining date. */
export function tenureLabel(joiningDate: string, today = new Date()): string | null {
  const [y, m, d] = joiningDate.split("-").map(Number);
  if (!y || !m || !d) return null;
  let months = (today.getFullYear() - y) * 12 + (today.getMonth() + 1 - m);
  if (today.getDate() < d) months -= 1;
  if (months < 0) return null;
  if (months === 0) return "Less than a month";
  const years = Math.floor(months / 12);
  const rest = months % 12;
  return [
    years ? `${years} ${years === 1 ? "yr" : "yrs"}` : null,
    rest ? `${rest} ${rest === 1 ? "mo" : "mos"}` : null,
  ]
    .filter(Boolean)
    .join(" ");
}

function Chip({ icon, children, mono = false }: { icon: ReactNode; children: ReactNode; mono?: boolean }) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full border border-border bg-surface/80 px-2.5 py-1 text-xs font-medium text-foreground-secondary",
        mono && "font-mono",
      )}
    >
      <span className="text-foreground-muted">{icon}</span>
      {children}
    </span>
  );
}

function Stat({ icon, label, children }: { icon: ReactNode; label: string; children: ReactNode }) {
  return (
    <div className="min-w-0 rounded-xl border border-border-subtle bg-surface-secondary/60 px-4 py-3">
      <dt className="flex items-center gap-1.5 text-xs font-medium text-foreground-muted">
        {icon}
        {label}
      </dt>
      <dd className="mt-1 truncate text-sm font-semibold text-foreground">{children}</dd>
    </div>
  );
}

function Missing() {
  return <span className="font-normal text-foreground-disabled">Not set</span>;
}

const CONTACT_LINK =
  "inline-flex min-w-0 max-w-full items-center gap-2 rounded-lg border border-border bg-surface px-3 py-1.5 text-sm text-foreground-secondary transition-colors hover:border-primary-border hover:bg-primary-subtle hover:text-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring";

/** The top of an employee's profile: who they are, what they do, and how to reach them. */
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
  const tenure = work?.employment ? tenureLabel(work.employment.joining_date) : null;
  const location = work?.assignment?.work_location_type
    ? (WORK_LOCATION_LABELS[work.assignment.work_location_type] ?? work.assignment.work_location_type)
    : null;

  return (
    <section
      aria-label="Employee summary"
      className="relative overflow-hidden rounded-2xl border border-border bg-surface shadow-elevation-1"
    >
      {/* A soft wash behind the identity block, so the header has a focal point without an empty band. */}
      <div
        aria-hidden="true"
        className="pointer-events-none absolute inset-x-0 top-0 h-44 bg-gradient-to-br from-primary-subtle via-primary-subtle/30 to-transparent"
      />
      <div className="relative p-5 sm:p-6">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="flex min-w-0 items-center gap-4 sm:gap-5">
            {employee.photo_url ? (
              // eslint-disable-next-line @next/next/no-img-element -- arbitrary uploaded URL
              <img
                src={employee.photo_url}
                alt=""
                className="h-20 w-20 shrink-0 rounded-2xl object-cover shadow-elevation-1 ring-4 ring-surface sm:h-24 sm:w-24"
              />
            ) : (
              <span
                aria-hidden="true"
                className={cn(
                  "inline-flex h-20 w-20 shrink-0 select-none items-center justify-center rounded-2xl text-2xl font-semibold tracking-tight shadow-elevation-1 ring-1 sm:h-24 sm:w-24 sm:text-3xl",
                  tintFor(employee.employee_code || name),
                )}
              >
                {computeInitials(name, employee.employee_code)}
              </span>
            )}
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-2">
                <h1 className="truncate text-2xl font-semibold tracking-tight text-foreground">{name}</h1>
                <EmployeeStatusBadge status={employee.status} />
                {!employee.is_active ? <Badge variant="outline">Inactive</Badge> : null}
              </div>
              <div className="mt-1 text-sm text-foreground-secondary">
                {workLoading ? (
                  <Skeleton className="h-4 w-48" />
                ) : work?.designation || work?.department ? (
                  <p>
                    <span className="font-medium text-foreground">{work?.designation ?? "No designation"}</span>
                    {work?.department ? <span> · {work.department}</span> : null}
                  </p>
                ) : (
                  <p className="text-foreground-muted">No designation or department yet</p>
                )}
              </div>
              <div className="mt-3 flex flex-wrap gap-1.5">
                <Chip icon={<Hash className="h-3 w-3" aria-hidden="true" />} mono>
                  {employee.employee_code}
                </Chip>
                {!workLoading && work?.branch ? (
                  <Chip icon={<MapPin className="h-3 w-3" aria-hidden="true" />}>{work.branch}</Chip>
                ) : null}
                {!workLoading && location ? (
                  <Chip icon={<Briefcase className="h-3 w-3" aria-hidden="true" />}>{location}</Chip>
                ) : null}
                {!workLoading && work?.company ? (
                  <Chip icon={<Building2 className="h-3 w-3" aria-hidden="true" />}>{work.company}</Chip>
                ) : null}
              </div>
            </div>
          </div>
          {actions ? <div className="flex flex-wrap items-center gap-2">{actions}</div> : null}
        </div>

        <dl className="mt-6 grid grid-cols-2 gap-3 lg:grid-cols-4">
          <Stat icon={<UserRound className="h-3.5 w-3.5" aria-hidden="true" />} label="Reports to">
            {workLoading ? (
              <Skeleton className="h-4 w-24" />
            ) : work?.manager ? (
              <Link href={`/app/employees/${work.manager.id}`} className="hover:text-primary hover:underline">
                {work.manager.name}
              </Link>
            ) : (
              <Missing />
            )}
          </Stat>
          <Stat icon={<Clock3 className="h-3.5 w-3.5" aria-hidden="true" />} label="Shift">
            {workLoading ? <Skeleton className="h-4 w-24" /> : (work?.shift ?? <Missing />)}
          </Stat>
          <Stat icon={<CalendarCheck className="h-3.5 w-3.5" aria-hidden="true" />} label="Joined">
            {workLoading ? (
              <Skeleton className="h-4 w-24" />
            ) : work?.employment ? (
              <CompanyDate value={work.employment.joining_date} />
            ) : (
              <Missing />
            )}
          </Stat>
          <Stat icon={<Briefcase className="h-3.5 w-3.5" aria-hidden="true" />} label="With the company">
            {workLoading ? <Skeleton className="h-4 w-24" /> : (tenure ?? <Missing />)}
          </Stat>
        </dl>

        {employee.personal_email || employee.personal_mobile ? (
          <div className="mt-4 flex flex-wrap items-center gap-2">
            {employee.personal_email ? (
              <a href={`mailto:${employee.personal_email}`} className={CONTACT_LINK}>
                <Mail className="h-4 w-4 shrink-0" aria-hidden="true" />
                <span className="truncate">{employee.personal_email}</span>
              </a>
            ) : null}
            {employee.personal_mobile ? (
              <a href={`tel:${employee.personal_mobile}`} className={cn(CONTACT_LINK, "tabular-nums")}>
                <Phone className="h-4 w-4 shrink-0" aria-hidden="true" />
                {employee.personal_mobile}
              </a>
            ) : null}
          </div>
        ) : null}
      </div>
    </section>
  );
}
