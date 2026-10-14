import { Lock } from "lucide-react";
import Link from "next/link";
import type { ReactNode } from "react";

interface AuthLayoutProps {
  title: string;
  description?: string;
  children: ReactNode;
  footer?: ReactNode;
}

/** Minimal chrome (logo only, no sidebar/top bar) — the "public surfaces" pattern in
 * docs/design/03_Navigation_System.md §13 for single-purpose flows outside the authenticated shell.
 * Visual language follows the Stitch "Staff Spectrum HRMS" design system (technobeala project). */
export function AuthLayout({ title, description, children, footer }: AuthLayoutProps) {
  return (
    <div className="flex min-h-screen flex-col bg-background">
      <header className="border-b border-border bg-surface px-6 py-3">
        <Link href="/" className="inline-flex items-center gap-2">
          <span className="text-lg font-semibold tracking-tight text-foreground">Spectrum</span>
          <span className="rounded-full border border-border bg-muted px-1.5 py-0.5 text-[11px] font-semibold tracking-wide text-foreground-secondary">
            HRMS
          </span>
        </Link>
      </header>
      <main className="flex flex-1 items-center justify-center px-4 py-12">
        <div className="w-full max-w-[420px]">
          <div className="mb-6 text-center">
            <h1 className="text-xl font-semibold tracking-tight text-foreground">{title}</h1>
            {description ? (
              <p className="mt-1 text-sm text-foreground-secondary">{description}</p>
            ) : null}
          </div>
          <div className="rounded-xl border border-border bg-surface p-6 shadow-sm sm:p-8">
            {children}
          </div>
          {footer ? <div className="mt-4 text-center text-sm text-foreground-secondary">{footer}</div> : null}
        </div>
      </main>
      <footer className="flex flex-col items-center gap-3 px-4 pb-6 text-center">
        <div className="inline-flex items-center gap-1.5 rounded-full border border-border bg-muted px-3 py-1 text-xs text-foreground-secondary">
          <Lock className="h-3.5 w-3.5" aria-hidden="true" />
          <span>Protected by enterprise grade 256-bit encryption</span>
        </div>
        <span className="text-xs text-foreground-muted">
          © {new Date().getFullYear()} Spectrum HRMS. All rights reserved.
        </span>
      </footer>
    </div>
  );
}
