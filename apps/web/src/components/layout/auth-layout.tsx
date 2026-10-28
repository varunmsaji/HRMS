import { CalendarCheck, Clock, Lock, Wallet } from "lucide-react";
import Image from "next/image";
import Link from "next/link";
import type { ReactNode } from "react";

import { Logo } from "@/components/brand/logo";

interface AuthLayoutProps {
  title: string;
  description?: string;
  children: ReactNode;
  footer?: ReactNode;
}

const HIGHLIGHTS = [
  { icon: Clock, title: "Attendance", text: "Shifts, rosters and regularisations, tracked accurately." },
  { icon: CalendarCheck, title: "Leave", text: "Policy-driven balances with simple approvals." },
  { icon: Wallet, title: "Payroll", text: "Clean inputs so every pay run closes on time." },
] as const;

/** Split-screen chrome for the public auth flows (no sidebar/top bar) — the "public surfaces"
 * pattern in docs/design/03_Navigation_System.md §13. The form sits on the right; the brand panel
 * is lg+ only, so smaller screens get the form alone. */
export function AuthLayout({ title, description, children, footer }: AuthLayoutProps) {
  return (
    <div className="flex min-h-screen bg-surface">
      <aside className="relative hidden overflow-hidden bg-[#0b1530] lg:flex lg:w-[46%] lg:max-w-[720px]">
        <Image
          src="/landing/hero.jpg"
          alt=""
          fill
          priority
          sizes="720px"
          className="object-cover"
        />
        <div
          aria-hidden="true"
          className="absolute inset-0 bg-gradient-to-b from-[#0b1530]/55 via-[#0b1530]/60 to-[#0b1530]/90"
        />
        <div
          aria-hidden="true"
          className="absolute -right-32 -top-32 h-96 w-96 rounded-full bg-primary/25 blur-3xl"
        />

        <div className="relative z-10 flex w-full flex-col justify-between px-12 py-10 xl:px-16">
          <Link href="/" className="inline-flex w-fit items-center">
            <Logo size={30} onDark />
          </Link>

          <div className="max-w-[460px]">
            <h2 className="text-[34px] font-semibold leading-[1.15] tracking-tight text-white">
              The people platform for growing teams.
            </h2>
            <p className="mt-4 text-base leading-relaxed text-slate-300">
              One workspace for attendance, leave and payroll — so HR spends less time chasing
              spreadsheets and more time with people.
            </p>

            <ul className="mt-10 space-y-5">
              {HIGHLIGHTS.map(({ icon: Icon, title: itemTitle, text }) => (
                <li key={itemTitle} className="flex items-start gap-4">
                  <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg border border-white/15 bg-white/5">
                    <Icon className="h-5 w-5 text-blue-300" aria-hidden="true" />
                  </span>
                  <div>
                    <p className="text-sm font-semibold text-white">{itemTitle}</p>
                    <p className="mt-0.5 text-sm text-slate-400">{text}</p>
                  </div>
                </li>
              ))}
            </ul>
          </div>

          <p className="text-xs text-slate-500">© {new Date().getFullYear()} Krewoxa. All rights reserved.</p>
        </div>
      </aside>

      <div className="flex flex-1 flex-col">
        <header className="px-6 py-6 sm:px-10 lg:hidden">
          <Link href="/" className="inline-flex items-center gap-2">
            <Logo size={30} />
          </Link>
        </header>

        <main className="flex flex-1 items-center justify-center px-6 py-10 sm:px-10">
          <div className="w-full max-w-[400px]">
            <div className="mb-8">
              <h1 className="text-[28px] font-semibold tracking-tight text-foreground">{title}</h1>
              {description ? (
                <p className="mt-2 text-md text-foreground-secondary">{description}</p>
              ) : null}
            </div>
            {children}
            {footer ? (
              <div className="mt-8 border-t border-border pt-6 text-center text-sm text-foreground-secondary">
                {footer}
              </div>
            ) : null}
          </div>
        </main>

        <footer className="flex flex-wrap items-center justify-between gap-2 px-6 pb-6 text-xs text-foreground-muted sm:px-10 lg:justify-center">
          <span className="lg:hidden">© {new Date().getFullYear()} Krewoxa. All rights reserved.</span>
          <span className="inline-flex items-center gap-1.5">
            <Lock className="h-3.5 w-3.5" aria-hidden="true" />
            Secured with encrypted connection
          </span>
        </footer>
      </div>
    </div>
  );
}
