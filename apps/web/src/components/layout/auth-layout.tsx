import { Lock } from "lucide-react";
import Link from "next/link";
import type { ReactNode } from "react";

import { Logo } from "@/components/brand/logo";

interface AuthLayoutProps {
  title: string;
  description?: string;
  children: ReactNode;
  footer?: ReactNode;
}

/** Split-screen chrome for the public auth flows (no sidebar/top bar) — the "public surfaces"
 * pattern in docs/design/03_Navigation_System.md §13. The form sits on the left; the product
 * preview panel is lg+ only, so smaller screens get the form alone. */
export function AuthLayout({ title, description, children, footer }: AuthLayoutProps) {
  return (
    <div className="flex min-h-screen bg-surface">
      <div className="flex flex-1 flex-col">
        <header className="px-6 py-6 sm:px-10">
          <Link href="/" className="inline-flex items-center gap-2">
            <Logo size={30} />
          </Link>
        </header>

        <main className="flex flex-1 items-center justify-center px-6 py-8 sm:px-10">
          <div className="w-full max-w-[400px]">
            <div className="mb-8">
              <h1 className="text-2xl font-semibold tracking-tight text-foreground">{title}</h1>
              {description ? (
                <p className="mt-2 text-md text-foreground-secondary">{description}</p>
              ) : null}
            </div>
            {children}
            {footer ? (
              <div className="mt-8 border-t border-border pt-6 text-sm text-foreground-secondary">{footer}</div>
            ) : null}
          </div>
        </main>

        <footer className="flex flex-wrap items-center justify-between gap-2 px-6 pb-6 text-xs text-foreground-muted sm:px-10">
          <span>© {new Date().getFullYear()} Krewoxa. All rights reserved.</span>
          <span className="inline-flex items-center gap-1.5">
            <Lock className="h-3.5 w-3.5" aria-hidden="true" />
            256-bit encrypted connection
          </span>
        </footer>
      </div>

      <aside className="hidden p-3 lg:block lg:w-[48%] lg:max-w-[760px]">
        <div className="flex h-full flex-col justify-center rounded-2xl bg-muted px-10 py-12 xl:px-16">
          <div className="max-w-[440px]">
            <p className="text-sm font-medium text-primary">Krewoxa HRMS</p>
            <h2 className="mt-3 text-[28px] font-semibold leading-tight tracking-tight text-foreground">
              Attendance, leave and payroll in one place.
            </h2>
            <p className="mt-3 text-md text-foreground-secondary">
              See who&apos;s in, approve requests and keep payroll inputs up to date — without
              switching between spreadsheets.
            </p>
          </div>
          <ProductPreview />
        </div>
      </aside>
    </div>
  );
}

const ATTENDANCE = [
  { label: "Present", value: 42, className: "bg-success" },
  { label: "On leave", value: 3, className: "bg-on-leave" },
  { label: "Late", value: 2, className: "bg-warning" },
  { label: "Absent", value: 1, className: "bg-danger" },
] as const;

/** Static, decorative sketch of the dashboard (sample data) — built from the app's own tokens so
 * it stays sharp at any size and follows light/dark theme. Hidden from assistive tech. */
function ProductPreview() {
  const total = ATTENDANCE.reduce((sum, item) => sum + item.value, 0);
  return (
    <div aria-hidden="true" className="mt-10 max-w-[440px] select-none space-y-3">
      <div className="rounded-xl border border-border bg-surface p-5 shadow-sm">
        <div className="flex items-baseline justify-between">
          <p className="text-sm font-medium text-foreground">Today&apos;s attendance</p>
          <p className="text-xs text-foreground-muted">48 employees</p>
        </div>
        <div className="mt-4 flex h-2 overflow-hidden rounded-full bg-muted">
          {ATTENDANCE.map((item) => (
            <span key={item.label} className={item.className} style={{ width: `${(item.value / total) * 100}%` }} />
          ))}
        </div>
        <dl className="mt-4 grid grid-cols-4 gap-2">
          {ATTENDANCE.map((item) => (
            <div key={item.label}>
              <dt className="flex items-center gap-1.5 text-xs text-foreground-muted">
                <span className={`h-2 w-2 rounded-full ${item.className}`} />
                {item.label}
              </dt>
              <dd className="mt-0.5 text-lg font-semibold text-foreground">{item.value}</dd>
            </div>
          ))}
        </dl>
      </div>

      <div className="ml-8 rounded-xl border border-border bg-surface p-4 shadow-sm">
        <div className="flex items-center gap-3">
          <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-primary-subtle text-sm font-semibold text-primary">
            AM
          </span>
          <div className="min-w-0 flex-1">
            <p className="text-sm font-medium text-foreground">Casual leave · 2 days</p>
            <p className="text-xs text-foreground-muted">Thu 12 – Fri 13 · Pending your approval</p>
          </div>
        </div>
        <div className="mt-3 flex justify-end gap-2">
          <span className="rounded-md border border-border px-3 py-1 text-xs font-medium text-foreground-secondary">
            Decline
          </span>
          <span className="rounded-md bg-primary px-3 py-1 text-xs font-medium text-on-primary">Approve</span>
        </div>
      </div>
    </div>
  );
}
