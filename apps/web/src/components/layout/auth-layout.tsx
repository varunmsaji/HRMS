import Link from "next/link";
import type { ReactNode } from "react";

interface AuthLayoutProps {
  title: string;
  description?: string;
  children: ReactNode;
  footer?: ReactNode;
}

/** Minimal chrome (logo only, no sidebar/top bar) — the "public surfaces" pattern in
 * docs/design/03_Navigation_System.md §13 for single-purpose flows outside the authenticated shell. */
export function AuthLayout({ title, description, children, footer }: AuthLayoutProps) {
  return (
    <div className="flex min-h-screen flex-col bg-background">
      <header className="border-b border-border px-6 py-4">
        <Link href="/" className="text-md font-semibold text-foreground">
          HRMS Platform
        </Link>
      </header>
      <main className="flex flex-1 items-center justify-center px-4 py-12">
        <div className="w-full max-w-md">
          <div className="mb-6 text-center">
            <h1 className="text-xl font-semibold text-foreground">{title}</h1>
            {description ? (
              <p className="mt-1 text-sm text-foreground-secondary">{description}</p>
            ) : null}
          </div>
          <div className="rounded-lg border border-border bg-surface p-6 shadow-sm sm:p-8">
            {children}
          </div>
          {footer ? <div className="mt-4 text-center text-sm text-foreground-secondary">{footer}</div> : null}
        </div>
      </main>
    </div>
  );
}
