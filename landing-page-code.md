# Krewoxa landing page: full code

Every file that makes up the landing page (route `/`), copied as is. Stack: Next.js App Router, React, TypeScript, plain CSS scoped under `.kx`, `lucide-react` icons, and `next/font/google`.

The body font comes from `--font-inter`, set in `apps/web/src/app/layout.tsx`. The display font comes from `--font-display`, set in `landing.tsx`.

## Assets referenced (served from `apps/web/public`, not included here)

- `/brand/krewoxa-logo.svg`
- `/brand/krewoxa-logo-white.svg`
- `/landing/product-dashboard.webp`
- `/landing/product-employees.webp`
- `/landing/product-payroll.webp`
- `/mascot/penguin-{pose}.svg`, where the pose is set in `landing.tsx`. Files available:
  - `penguin-celebrating.svg`
  - `penguin-clipboard.svg`
  - `penguin-explaining.svg`
  - `penguin-holding-hands.svg`
  - `penguin-holding.svg`
  - `penguin-standing.svg`
  - `penguin-thinking.svg`
  - `penguin-waving.svg`
  - `penguin-welcome.svg`

## `apps/web/src/app/page.tsx`

````tsx
import type { Metadata } from "next";

import { Landing } from "@/components/landing/landing";

const title = "Krewoxa HRMS | Organize Your HR Operations";
const description =
  "Discover how Krewoxa helps businesses organize employee information and everyday HR workflows. Book a demo to explore the product.";

export const metadata: Metadata = {
  title,
  description,
  openGraph: { title, description, siteName: "Krewoxa", type: "website" },
  twitter: { card: "summary_large_image", title, description },
};

export default function HomePage() {
  return <Landing />;
}

````

## `apps/web/src/components/landing/landing.tsx`

````tsx
"use client";

import { useState, type FormEvent } from "react";

import { Plus_Jakarta_Sans } from "next/font/google";
import Link from "next/link";
import {
  ArrowRight,
  BarChart3,
  CalendarCheck,
  CalendarDays,
  Check,
  ClipboardPen,
  Clock,
  FileText,
  Fingerprint,
  History,
  Layers,
  Lock,
  Menu,
  Minus,
  Play,
  Plus,
  ScanFace,
  ShieldCheck,
  Smartphone,
  UserPlus,
  Users,
  Wallet,
  Workflow,
  X,
  Zap,
  type LucideIcon,
} from "lucide-react";

import { HeroDashboard } from "./hero-dashboard";
import { Tilt } from "./tilt";
import "./landing.css";

// Display face for headings; self-hosted by next/font so the CSP is unaffected.
const display = Plus_Jakarta_Sans({ subsets: ["latin"], weight: ["700", "800"], variable: "--font-display", display: "swap" });

const LOGO = "/brand/krewoxa-logo.svg";
const LOGO_WHITE = "/brand/krewoxa-logo-white.svg";

/** Brand logo (mark + KREWOXA wordmark) straight from /public/brand. */
function BrandLogo({ onDark = false }: { onDark?: boolean }) {
  return (
    // eslint-disable-next-line @next/next/no-img-element
    <img src={onDark ? LOGO_WHITE : LOGO} alt="Krewoxa" width={159} height={34} />
  );
}

const NAV: [string, string][] = [
  ["Platform", "#platform"],
  ["Payroll", "#payroll"],
  ["Workflows", "#workflows"],
  ["Mobile", "#mobile"],
  ["Security", "#security"],
  ["FAQ", "#faq"],
];

const CORE: string[] = [
  "Profiles, roles, departments and reporting lines",
  "Documents stored against each employee",
  "Live status: who is in, on leave or yet to check in",
];

const MOBILE: [LucideIcon, string, string][] = [
  [ScanFace, "Face punch check-in", "Employees mark attendance from their phone in seconds."],
  [CalendarDays, "Leave and shifts", "Apply for leave, track balances and see the upcoming roster."],
  [ClipboardPen, "Corrections and payslips", "Fix a missed punch and download payslips without emailing HR."],
];

const DEPTS: [string, number][] = [["Operations", 14], ["Customer Care", 11], ["Design", 9], ["People", 8], ["Finance", 6]];

const FEATS: [LucideIcon, string, string][] = [
  [Clock, "Attendance that feeds payroll", "Check-ins and corrections are reviewed once, then flow straight into payroll prep."],
  [CalendarCheck, "Leave adjusted automatically", "Approved leave updates balances and the payroll inputs without re-keying."],
  [ShieldCheck, "Review before every run", "Managers sign off on one summary, and every change leaves a record."],
];

const FLOWS: { icon: LucideIcon; title: string; text: string; items: [string, "ok" | "go" | "todo"][] }[] = [
  {
    icon: UserPlus,
    title: "Smooth onboarding",
    text: "Bring a new hire from offer to first day with a checklist everyone can see.",
    items: [["Profile created", "ok"], ["Documents collected", "ok"], ["Manager intro", "go"], ["Day-one access", "todo"]],
  },
  {
    icon: CalendarCheck,
    title: "Self-running approvals",
    text: "Requests move along a defined path, so nothing waits in someone's inbox.",
    items: [["Request submitted", "ok"], ["Team lead review", "ok"], ["HR approval", "go"], ["Balance updated", "todo"]],
  },
  {
    icon: Wallet,
    title: "Payroll prep, simplified",
    text: "Attendance and leave are reconciled before payroll ever reaches finance.",
    items: [["Attendance reviewed", "ok"], ["Leave applied", "ok"], ["Manager review", "go"], ["Final approval", "todo"]],
  },
];

const MODULES: [LucideIcon, string][] = [
  [Users, "Employees"],
  [Clock, "Attendance"],
  [CalendarCheck, "Leave"],
  [Wallet, "Payroll prep"],
  [UserPlus, "Recruitment"],
  [FileText, "Documents"],
  [Smartphone, "Mobile access"],
  [BarChart3, "Reports"],
];

const TRUST: [LucideIcon, string, string][] = [
  [Lock, "Role-based access", "Control what each person can see and do."],
  [Layers, "Organization data separation", "Each organization works in its own space."],
  [History, "Activity history", "Keep a record of important changes."],
  [Fingerprint, "Secure sign-in", "Authentication details shared in your demo."],
];

const FAQS: [string, string][] = [
  ["What is Krewoxa?", "Krewoxa is a Human Resource Management System that helps businesses organize employee information and everyday HR workflows in one workspace."],
  ["Which HR workflows does it support?", "Employee records, attendance, and leave are core areas. Payroll workflows, recruitment and documents are discussed in the demo so we can confirm what applies to you."],
  ["Is it suitable for a small or growing business?", "Krewoxa is designed for growing teams that need more structure than spreadsheets. A demo is the best way to judge the fit for your size."],
  ["Can employees and managers use it on mobile?", "Yes. Employees use the Krewoxa mobile app to check in, apply for leave, request corrections and download payslips. Ask during a demo which manager features fit your team."],
  ["How does onboarding work?", "Typically you set up the organization, add employee information, then configure the workflows you need. We will outline your specific steps in the demo."],
  ["How can we arrange a demo?", "Use the form at the bottom of this page and tell us where to reach you."],
];

const FOOT_PRODUCT: [string, string][] = [["Platform", "#platform"], ["Payroll", "#payroll"], ["Workflows", "#workflows"], ["Mobile", "#mobile"], ["Security", "#security"]];

// Illustrative, like the figures in the hero dashboard.
const HERO_CHIPS: { icon: LucideIcon; tint: string; title: string; note: string }[] = [
  { icon: ScanFace, tint: "green", title: "Arjun checked in", note: "Face verified · 9:24 AM" },
  { icon: Wallet, tint: "blue", title: "Pay run ready", note: "64 employees ready" },
  { icon: CalendarCheck, tint: "amber", title: "Leave approved", note: "Sara Thomas · 2 days" },
  { icon: BarChart3, tint: "cyan", title: "96% on time", note: "Up 3% this week" },
];

type MascotPose = "standing" | "waving" | "thinking" | "clipboard" | "celebrating" | "explaining" | "welcome";

// Decorative only: the penguin never carries information the copy doesn't.
function Mascot({ pose, className }: { pose: MascotPose; className: string }) {
  // eslint-disable-next-line @next/next/no-img-element
  return <img className={`mascot ${className}`} src={`/mascot/penguin-${pose}.svg`} width={240} height={290} alt="" aria-hidden="true" />;
}

export function Landing() {
  const [menuOpen, setMenuOpen] = useState(false);
  const [openFaq, setOpenFaq] = useState(-1);
  const [email, setEmail] = useState("");
  const [error, setError] = useState("");
  const [sent, setSent] = useState(false);

  const closeMenu = () => setMenuOpen(false);

  // Preview only: the demo form is not wired to a backend yet.
  const submit = (ev: FormEvent) => {
    ev.preventDefault();
    const ok = /^\S+@\S+\.\S+$/.test(email);
    setError(ok ? "" : "Please enter a valid work email.");
    setSent(ok);
  };

  return (
    <div className={`kx ${display.variable}`}>
      {/* HEADER */}
      <header className="hdr">
        <div className="wrap hdr-in">
          <a href="#top" className="logo" aria-label="Krewoxa home"><BrandLogo /></a>
          <nav className="nav" aria-label="Primary">
            {NAV.map(([label, href]) => <a key={href} href={href}>{label}</a>)}
          </nav>
          <div className="hdr-act">
            <Link href="/login" className="link-quiet hide-m">Log in</Link>
            <Link href="/register" className="btn btn-ghost btn-sm hide-m">Register</Link>
            <a href="#demo" className="btn btn-dark btn-sm">Book a demo</a>
            <button className="burger" onClick={() => setMenuOpen((o) => !o)} aria-label="Menu" aria-expanded={menuOpen} aria-controls="mobnav">
              {menuOpen ? <X size={20} /> : <Menu size={20} />}
            </button>
          </div>
        </div>
        {menuOpen && (
          <nav id="mobnav" className="mnav" aria-label="Mobile">
            {NAV.map(([label, href]) => <a key={href} href={href} onClick={closeMenu}>{label}</a>)}
            <Link href="/login" onClick={closeMenu}>Log in</Link>
            <Link href="/register" onClick={closeMenu} style={{ color: "#0657E6", fontWeight: 600 }}>Register</Link>
          </nav>
        )}
      </header>

      <main id="top">
        {/* HERO */}
        <section className="hero">
          <div className="wrap">
            <span className="pill up"><span className="dot" />People. Work. Simplified.</span>
            <h1 className="up d1">Attendance, leave and payroll, <span className="hl">finally in sync.</span></h1>
            <p className="lead up d2">Krewoxa brings employee records, attendance, leave and payroll prep into one connected workspace, so your HR team spends less time chasing and more time leading.</p>
            <div className="cta-row up d3">
              <a href="#demo" className="btn btn-dark">Book a demo <ArrowRight size={16} /></a>
              <a href="#workflows" className="btn btn-ghost"><Play size={14} /> See how it works</a>
            </div>

            <div className="win-stage up d3">
              <Tilt className="hold-stage" maxDegrees={2.5}>
                <div className="win">
                  <div className="win-bar"><i /><i /><i /></div>
                  <HeroDashboard />
                  {/* Shown instead of the animation under prefers-reduced-motion. */}
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img className="shot-img hd-still" src="/landing/product-dashboard.webp" width={1600} height={1000} loading="lazy" alt="The Krewoxa company dashboard: today's attendance, leave and items waiting on HR" />
                  <noscript><style>{".kx .hd *{animation:none!important}"}</style></noscript>
                </div>
                {HERO_CHIPS.map(({ icon: Icon, tint, title, note }, i) => (
                  <div key={title} className={`hero-chip hero-chip-${i + 1}`} aria-hidden="true">
                    <span className={`hero-chip-ico ${tint}`}><Icon size={18} /></span>
                    <span><b>{title}</b><small>{note}</small></span>
                  </div>
                ))}
              </Tilt>
            </div>
          </div>
        </section>

        {/* CORE HR */}
        <section id="platform" className="cap">
          <div className="wrap split">
            <div>
              <span className="pill"><Users size={14} /> CORE HR</span>
              <h2 className="h2" style={{ margin: "18px 0 16px" }}>Every employee record, <span className="mute">in one place.</span></h2>
              <p className="lead">Profiles, roles and departments live together instead of across files and chats, so every team starts from the same source of truth.</p>
              <ul className="ticks">
                {CORE.map((c) => <li key={c}><span className="tick"><Check size={12} /></span>{c}</li>)}
              </ul>
              <a href="#workflows" className="btn btn-dark">See how it works <ArrowRight size={16} /></a>
            </div>
            <Tilt className="card shot">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img className="shot-img" src="/landing/product-employees.webp" width={1600} height={1000} loading="lazy" alt="The Krewoxa employee directory with role, department, reporting manager, shift and status" />
            </Tilt>
          </div>
        </section>

        {/* PAYROLL */}
        <section id="payroll">
          <div className="wrap center">
            <span className="pill"><Wallet size={14} /> PAYROLL PREP</span>
            <h2 className="h2" style={{ margin: "18px 0 16px" }}>Payroll inputs, reconciled<br /><span className="mute">before they reach finance.</span></h2>
            <p className="lead">Attendance, leave and approvals come together in one summary. Managers review it once, and every change is on record.</p>

            <Tilt className="card shot shot-center" maxDegrees={3}>
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img className="shot-img" src="/landing/product-payroll.webp" width={1600} height={705} loading="lazy" alt="The Krewoxa pay runs list with month, status, employees paid and net pay" />
            </Tilt>

            <div className="grid3" style={{ marginTop: 20, textAlign: "left" }}>
              {FEATS.map(([Icon, t, p]) => (
                <div className="card feat" key={t}>
                  <div className="ico"><Icon size={22} /></div>
                  <h3>{t}</h3>
                  <p>{p}</p>
                </div>
              ))}
            </div>
          </div>
        </section>

        {/* CAPACITY */}
        <section>
          <div className="wrap split">
            <div>
              <span className="pill"><Zap size={14} /> WORKFORCE VISIBILITY</span>
              <h2 className="h2" style={{ margin: "18px 0 16px" }}>Who&apos;s in, who&apos;s away, <span className="mute">at a glance.</span></h2>
              <p className="lead">Headcount, attendance and approved leave by department, updated as people check in, so you can see where teams are stretched without compiling reports.</p>
              <div className="stats">
                <div><b>48</b><span>Employees</span></div>
                <div><b>41</b><span>Present today</span></div>
                <div><b>4</b><span>On approved leave</span></div>
              </div>
              <a href="#demo" className="btn btn-dark">Book a demo</a>
            </div>
            <div className="dark" role="img" aria-label="Illustrative headcount by department using sample data">
              <div className="dark-h"><b>Headcount by department</b><span>Sample data</span></div>
              {DEPTS.map(([d, n], i) => (
                <div className="row" key={d}>
                  <span>{d}</span>
                  <div className="trk"><i style={{ width: `${(n / 14) * 100}%`, animationDelay: `${i * 0.1}s` }} /></div>
                  <b>{n}</b>
                </div>
              ))}
              <div className="dark-f"><span className="live" /> 3 leave requests need review</div>
            </div>
          </div>
        </section>

        {/* WORKFLOWS */}
        <section id="workflows">
          <div className="wrap center">
            <span className="pill"><Workflow size={14} /> WORKFLOWS</span>
            <h2 className="h2" style={{ margin: "18px 0 16px" }}>Set the approval path once.<br /><span className="mute">Krewoxa keeps it moving.</span></h2>
            <p className="lead">Onboarding, leave and payroll prep follow a defined path, so nothing waits in an inbox and you can see where each request stands.</p>
            <div className="grid3" style={{ marginTop: 48, textAlign: "left" }}>
              {FLOWS.map(({ icon: Icon, title, text, items }) => (
                <div className="card wf" key={title}>
                  <div className="ico" style={{ marginBottom: 0 }}><Icon size={22} /></div>
                  <div><h3>{title}</h3><p>{text}</p></div>
                  <div className="mini">
                    {items.map(([label, st]) => (
                      <div key={label}>
                        <span>{label}</span>
                        <span className={`tick ${st === "ok" ? "" : st}`}>{st === "ok" ? <Check size={12} /> : st === "go" ? <Clock size={12} /> : <Minus size={12} />}</span>
                      </div>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          </div>
        </section>

        {/* MOBILE */}
        <section id="mobile" className="cap">
          <div className="wrap split">
            <div className="phone" role="img" aria-label="Illustrative Krewoxa mobile app home screen with a face punch check-in and quick actions, using sample data">
              <div className="scr">
                <div className="notch" />
                <div className="ph-top"><span>Good morning,</span><b>Anjali</b></div>
                <div className="today">
                  <small>Today · Shift 9:30 AM – 6:30 PM</small>
                  <b>Not punched in</b>
                  <span className="punch"><ScanFace size={18} /> Face punch</span>
                </div>
                <div className="qa">
                  {([[CalendarCheck, "Apply leave", "8 days left"], [ClipboardPen, "Correction", "Fix missed punch"], [FileText, "Payslip", "October"], [CalendarDays, "My shifts", "Upcoming roster"]] as [LucideIcon, string, string][]).map(([Icon, t, sub]) => (
                    <div key={t}><Icon size={17} /><b>{t}</b><small>{sub}</small></div>
                  ))}
                </div>
                <div className="month">
                  <small>Attendance this month</small>
                  <div><span><b>18</b>Present</span><span><b>1</b>Leave</span><span><b>2</b>Late</span></div>
                </div>
              </div>
            </div>
            <div>
              <span className="pill"><Smartphone size={14} /> MOBILE APP</span>
              <h2 className="h2" style={{ margin: "18px 0 16px" }}>HR in every employee&apos;s pocket.</h2>
              <p className="lead">The Krewoxa app gives employees the everyday self-service they need, so HR stops fielding the same questions.</p>
              <div className="mfeat">
                {MOBILE.map(([Icon, t, p]) => (
                  <div key={t}>
                    <div className="ico ico-soft"><Icon size={20} /></div>
                    <div><h3>{t}</h3><p>{p}</p></div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </section>

        {/* MODULES */}
        <section>
          <div className="wrap center">
            <h2 className="h2">Everything HR runs on, <span className="mute">in one workspace.</span></h2>
            <p className="lead" style={{ marginTop: 16 }}>No more switching between tools to answer a simple question about your people.</p>
            <div className="mods">
              {MODULES.map(([Icon, label]) => (
                <div className="card mod" key={label}><div className="ico ico-soft"><Icon size={22} /></div>{label}</div>
              ))}
            </div>
          </div>
        </section>

        {/* TRUST */}
        <section id="security" className="trust">
          <div className="wrap center" style={{ position: "relative" }}>
            <span className="pill" style={{ background: "rgba(255,255,255,.08)", borderColor: "rgba(255,255,255,.2)", color: "#9CCBFF" }}><ShieldCheck size={14} /> SECURITY</span>
            <h2 className="h2" style={{ margin: "18px 0 16px" }}>Employee data deserves careful handling.</h2>
            <p className="lead">HR records are sensitive. We&apos;ll walk you through how access, permissions and data handling work, and answer security questions directly during your demo.</p>
            <div className="tgrid" style={{ textAlign: "left" }}>
              {TRUST.map(([Icon, t, p]) => (
                <div className="t" key={t}>
                  <div className="ico" style={{ marginBottom: 0 }}><Icon size={22} /></div>
                  <h3>{t}</h3>
                  <p>{p}</p>
                </div>
              ))}
            </div>
          </div>
        </section>

        {/* FAQ */}
        <section id="faq">
          <div className="wrap center">
            <Mascot pose="thinking" className="mascot-faq" />
            <h2 className="h2">Common questions</h2>
            <div className="faq" style={{ textAlign: "left" }}>
              {FAQS.map(([q, a], i) => {
                const open = openFaq === i;
                return (
                  <div className="faq-i" key={q}>
                    <h3><button onClick={() => setOpenFaq(open ? -1 : i)} aria-expanded={open}>{q}<span aria-hidden="true" style={{ color: "#0657E6", flex: "none", display: "inline-flex" }}>{open ? <Minus size={20} /> : <Plus size={20} />}</span></button></h3>
                    {open && <p>{a}</p>}
                  </div>
                );
              })}
            </div>
          </div>
        </section>

        {/* CTA */}
        <section id="demo" className="cta">
          <div className="wrap">
            <div className="cta-card">
              <Mascot pose={sent ? "celebrating" : "welcome"} className="mascot-cta" />
              <h2>Ready to bring your HR <span style={{ color: "#5CC8FF" }}>into sync?</span></h2>
              <p>Leave your work email and we&apos;ll show you whether Krewoxa fits how you work. No pressure, no obligation.</p>
              {sent ? (
                <p role="status" className="cta-ok">Thanks. This form is a preview and isn&apos;t connected to a backend yet, so nothing was sent.</p>
              ) : (
                <form className="cta-form" onSubmit={submit} noValidate>
                  <label htmlFor="cta-email" style={{ position: "absolute", width: 1, height: 1, overflow: "hidden", clip: "rect(0 0 0 0)" }}>Work email</label>
                  <input id="cta-email" type="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="Enter your work email" autoComplete="email" aria-invalid={!!error} aria-describedby="cta-err" />
                  <button type="submit" className="btn btn-light">Book a demo</button>
                </form>
              )}
              <div id="cta-err" className="cta-err" role="alert">{error}</div>
            </div>
          </div>
        </section>
      </main>

      {/* FOOTER */}
      <footer className="ftr">
        <div className="wrap">
          <div className="ftr-top">
            <div>
              <BrandLogo onDark />
              <p>HR management for growing teams. Employee information and everyday workflows in one place.</p>
            </div>
            <div className="ftr-cols">
              <div>
                <h4>Product</h4>
                {FOOT_PRODUCT.map(([l, h]) => <a key={h} href={h}>{l}</a>)}
              </div>
              <div>
                <h4>Account</h4>
                <Link href="/login">Log in</Link>
                <Link href="/register">Register</Link>
                <a href="#demo">Book a demo</a>
              </div>
            </div>
          </div>
          <div className="ftr-bot">
            <span>© {new Date().getFullYear()} Krewoxa. All rights reserved.</span>
            <span>People. Work. Simplified.</span>
          </div>
        </div>
      </footer>
    </div>
  );
}

````

## `apps/web/src/components/landing/hero-dashboard.tsx`

````tsx
"use client";

import { useEffect, useRef, useState } from "react";

import {
  Activity,
  Bell,
  CalendarCheck,
  CalendarClock,
  CalendarDays,
  CalendarOff,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  ClipboardPen,
  Clock,
  Gift,
  LayoutGrid,
  Moon,
  Search,
  Settings,
  Timer,
  UserPlus,
  Users,
  Wallet,
  type LucideIcon,
} from "lucide-react";

// Illustrative figures for the landing page; nothing here reads from a real company.
const SIDEBAR: [string, [LucideIcon, string][]][] = [
  ["Workspace", [[LayoutGrid, "Dashboard"]]],
  ["People", [[Users, "Employees"], [UserPlus, "Onboarding"]]],
  ["Time & attendance", [[CalendarCheck, "Attendance"], [CalendarClock, "Shift Rosters"], [ClipboardPen, "Regularizations"], [Timer, "Overtime"]]],
  ["Leave & payroll", [[CalendarOff, "Leave"], [CalendarDays, "Leave Balances"], [Wallet, "Payroll"]]],
  ["Administration", [[Settings, "Settings"]]],
];

const TOTAL = 64;
const PRESENT_START = 50;
const NOT_IN_START = 5;
const CHECK_INS = ["Arjun Mehta", "Neha Kapoor", "Imran Sheikh", "Anita Rao"];
const FEED = [
  { name: "Sara Thomas", text: "Leave request approved", when: "5 min ago" },
  { name: "Rohan Das", text: "Correction submitted", when: "12 min ago" },
  { name: "Dev Malhotra", text: "Joined Engineering", when: "1 hour ago" },
];
const LEAVE = [
  { label: "Casual", value: 8, color: "#2563EB" },
  { label: "Earned", value: 4, color: "#15803D" },
  { label: "Sick", value: 3, color: "#B45309" },
];
const DEPARTMENTS: [string, number][] = [["Engineering", 21], ["Operations", 13], ["Sales", 11]];
const GROWTH: [string, number, number, number][] = [
  ["Jun", 48, 14, 92], ["Jul", 51, 72, 78], ["Aug", 55, 130, 60], ["Sep", 58, 188, 47], ["Oct", 61, 246, 33], ["Nov", 64, 304, 20],
];
const GROWTH_LINE = GROWTH.map(([, , x, y], i) => `${i ? "L" : "M"}${x} ${y}`).join(" ");

const CHECK_IN_EVERY_MS = 3400;
const COUNT_DELAY_MS = 250;
const COUNT_MS = 1500;

const delay = (seconds: number) => ({ animationDelay: `${seconds}s` });
const initials = (name: string) => name.split(" ").map((part) => part[0]).join("");

type Slice = { value: number; color: string };

/** Ring of slices, revealed by a mask that sweeps round once. r=15.915 makes the circumference 100. */
function Donut({ id, slices, total, sweepAt }: { id: string; slices: Slice[]; total: number; sweepAt: number }) {
  const sum = slices.reduce((acc, s) => acc + s.value, 0);
  const pcts = slices.map((s) => (s.value / sum) * 100);
  const startOf = (index: number) => pcts.slice(0, index).reduce((acc, p) => acc + p, 0);
  return (
    <svg className="hd-donut" viewBox="0 0 42 42">
      <mask id={id}>
        <circle className="hd-sweep" style={delay(sweepAt)} cx="21" cy="21" r="15.915" fill="none" stroke="#fff" strokeWidth="6" pathLength={100} transform="rotate(-90 21 21)" />
      </mask>
      <g mask={`url(#${id})`}>
        {slices.map((s, i) => (
          <circle key={s.color} className="hd-slice" cx="21" cy="21" r="15.915" fill="none" stroke={s.color} strokeWidth="5.4" strokeDasharray={`${pcts[i]} ${100 - pcts[i]}`} strokeDashoffset={25 - startOf(i)} />
        ))}
      </g>
      <text x="21" y="21.5" textAnchor="middle" className="hd-donut-n">{total}</text>
      <text x="21" y="27" textAnchor="middle" className="hd-donut-l">Total</text>
    </svg>
  );
}

/**
 * The landing page's animated hero: a hand-built copy of the company dashboard. Plays once when it
 * scrolls into view (cards rise, numbers count up, charts draw), then a few check-ins arrive and it
 * settles. Under prefers-reduced-motion CSS hides it in favour of the screenshot beside it.
 */
export function HeroDashboard() {
  const root = useRef<HTMLDivElement>(null);
  const [play, setPlay] = useState(false);
  const [progress, setProgress] = useState(1);
  const [checkIns, setCheckIns] = useState(0);

  useEffect(() => {
    const el = root.current;
    if (!el || window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    let inView = false;
    let raf = 0;
    let timer = 0;

    const countUp = (startedAt: number) => (now: number) => {
      const t = Math.min(1, Math.max(0, (now - startedAt - COUNT_DELAY_MS) / COUNT_MS));
      setProgress(1 - (1 - t) ** 3);
      if (t < 1) raf = requestAnimationFrame(countUp(startedAt));
    };

    const io = new IntersectionObserver(([entry]) => {
      inView = entry.isIntersecting;
      if (!inView || timer) return;
      setPlay(true);
      raf = requestAnimationFrame(countUp(performance.now()));
      let arrived = 0;
      timer = window.setInterval(() => {
        if (!inView) return;
        arrived += 1;
        setCheckIns(arrived);
        if (arrived === CHECK_INS.length) window.clearInterval(timer);
      }, CHECK_IN_EVERY_MS);
    }, { threshold: 0.2 });
    io.observe(el);

    return () => {
      io.disconnect();
      cancelAnimationFrame(raf);
      window.clearInterval(timer);
    };
  }, []);

  const count = (target: number) => Math.round(target * progress);
  const present = PRESENT_START + checkIns;
  const attendance = [
    { label: "Present", value: present, color: "#15803D" },
    { label: "On leave", value: 3, color: "#7C3AED" },
    { label: "Absent", value: 2, color: "#DC2626" },
    { label: "WFH", value: 3, color: "#0F766E" },
    { label: "On duty", value: 1, color: "#0369A1" },
    { label: "Others", value: NOT_IN_START - checkIns, color: "#CBD5E1" },
  ];
  const leaveTotal = LEAVE.reduce((acc, l) => acc + l.value, 0);
  const feed = [
    ...CHECK_INS.slice(0, checkIns).reverse().map((name) => ({ name, text: "Checked in", when: "Just now" })),
    ...FEED,
  ].slice(0, 3);

  return (
    <div ref={root} className={`hd${play ? " play" : ""}`} role="img" aria-label="The Krewoxa company dashboard: today's attendance, leave and items waiting on HR">
      <div className="hd-app" aria-hidden="true">
        <aside className="hd-side">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src="/brand/krewoxa-logo-white.svg" alt="" width={159} height={34} />
          {SIDEBAR.map(([group, items]) => (
            <div key={group}>
              <p>{group}</p>
              {items.map(([Icon, label]) => (
                <span key={label} className={label === "Dashboard" ? "on" : undefined}><Icon />{label}</span>
              ))}
            </div>
          ))}
        </aside>

        <div className="hd-main">
          <div className="hd-top">
            <b>Your Company</b><i />Dashboard
            <span className="hd-search"><Search />Search employees...</span>
            <Bell /><Moon />
            <span className="hd-av">AD</span>admin@yourcompany.com<ChevronDown />
          </div>

          <div className="hd-body">
            <div className="hd-head">
              <div>
                <h4>Dashboard</h4>
                <p>Here&apos;s what&apos;s happening in your company today.</p>
              </div>
              <span className="hd-live"><i />Live</span>
              <span className="hd-range"><CalendarDays />This month</span>
            </div>

            <div className="hd-kpis">
              <div className="hd-card hd-in" style={delay(0.2)}>
                <em className="blue"><Users /></em>
                <p>Total Employees</p>
                <div className="hd-kpi"><strong>{count(TOTAL)}</strong><small className="up">+4%</small> vs last month</div>
                <p className="hd-note">{count(TOTAL)} expected to work today</p>
              </div>
              <div className="hd-card hd-in" style={delay(0.3)}>
                <em className="green"><CheckCircle2 /></em>
                <p>Present Today</p>
                <div className="hd-kpi"><strong key={checkIns} className={checkIns ? "hd-bump" : undefined}>{checkIns ? present : count(present)}</strong><small className="up">+4%</small> vs yesterday</div>
                <p className="hd-note">2 late arrivals</p>
              </div>
              <div className="hd-card hd-in" style={delay(0.4)}>
                <em className="amber"><CalendarOff /></em>
                <p>On Leave Today</p>
                <div className="hd-kpi"><strong>{count(3)}</strong><small className="down">-1</small> vs yesterday</div>
                <p className="hd-note">2 returning tomorrow</p>
              </div>
              <div className="hd-card hd-in" style={delay(0.5)}>
                <em className="sky"><Clock /></em>
                <p>Pending Approvals</p>
                <div className="hd-kpi"><strong>{count(14)}</strong></div>
                <p className="hd-note">5 Leave · 6 Attendance · 3 Overtime</p>
              </div>
            </div>

            <div className="hd-charts">
              <div className="hd-card hd-in" style={delay(0.65)}>
                <div className="hd-title"><Users />Employee Growth<span className="hd-sel">Last 6 months<ChevronDown /></span></div>
                <div className="hd-big"><strong>{count(TOTAL)}</strong> employees <small className="up">+16 since Jun</small></div>
                <svg className="hd-growth" viewBox="0 0 320 124">
                  <path className="hd-area" style={delay(1.3)} d={`${GROWTH_LINE} L304 106 L14 106 Z`} />
                  <path className="hd-line" style={delay(0.8)} d={GROWTH_LINE} pathLength={1} />
                  {GROWTH.map(([month, value, x, y], i) => (
                    <g key={month} className="hd-point" style={delay(0.85 + i * 0.13)}>
                      <circle cx={x} cy={y} r={i === GROWTH.length - 1 ? 4 : 2.2} />
                      <text x={x} y={y - 8} textAnchor="middle">{value}</text>
                      <text x={x} y={120} textAnchor="middle" className="hd-axis">{month}</text>
                    </g>
                  ))}
                </svg>
              </div>

              <div className="hd-card hd-in" style={delay(0.75)}>
                <div className="hd-title"><Activity />Attendance Overview<span className="hd-link">View All<ChevronRight /></span></div>
                <div className="hd-split">
                  <Donut id="hd-mask-attendance" slices={attendance} total={count(TOTAL)} sweepAt={0.9} />
                  <ul>
                    {attendance.map((a) => (
                      <li key={a.label}><i style={{ background: a.color }} />{a.label}<b>{a.value}</b><small>{((a.value / TOTAL) * 100).toFixed(1)}%</small></li>
                    ))}
                  </ul>
                </div>
              </div>

              <div className="hd-card hd-in" style={delay(0.85)}>
                <div className="hd-title"><CalendarDays />Leave Statistics<span className="hd-sel">This Month<ChevronDown /></span></div>
                <div className="hd-split">
                  <Donut id="hd-mask-leave" slices={LEAVE} total={count(leaveTotal)} sweepAt={1.05} />
                  <ul>
                    {LEAVE.map((l) => (
                      <li key={l.label}><i style={{ background: l.color }} />{l.label}<b>{l.value}</b><small>{((l.value / leaveTotal) * 100).toFixed(1)}%</small></li>
                    ))}
                  </ul>
                </div>
              </div>
            </div>

            <div className="hd-lists">
              <div className="hd-card hd-in" style={delay(1)}>
                <div className="hd-title"><Gift />Upcoming Birthdays</div>
                <div className="hd-row"><span className="hd-av">PN</span><div><b>Priya Nair</b><small>Operations Executive</small></div><u>Today</u></div>
                <div className="hd-row"><span className="hd-av">FK</span><div><b>Farah Khan</b><small>Sales Lead</small></div><small>Next week</small></div>
              </div>
              <div className="hd-card hd-in" style={delay(1.1)}>
                <div className="hd-title"><Clock />Pending Approvals<span className="hd-link">View All<ChevronRight /></span></div>
                <div className="hd-row"><em className="amber"><Clock /></em><div><b>Regularization</b><small>Nisha Agarwal · 3 hours ago</small></div><ChevronRight /></div>
                <div className="hd-row"><em className="amber"><CalendarOff /></em><div><b>Casual leave</b><small>Ravi Gupta · 4 hours ago</small></div><ChevronRight /></div>
              </div>
              <div className="hd-card hd-in" style={delay(1.2)}>
                <div className="hd-title">Department Overview<span className="hd-link">View All<ChevronRight /></span></div>
                {DEPARTMENTS.map(([name, n], i) => (
                  <div key={name} className="hd-dept">
                    <span>{name}<b>{n}</b></span>
                    <div><i style={{ width: `${(n / DEPARTMENTS[0][1]) * 100}%`, ...delay(1.3 + i * 0.12) }} /></div>
                  </div>
                ))}
              </div>
              <div className="hd-card hd-in" style={delay(1.3)}>
                <div className="hd-title"><Activity />Recent Activities</div>
                {feed.map((item) => (
                  <div key={item.name} className={`hd-row${item.when === "Just now" ? " hd-new" : ""}`}>
                    <span className="hd-av">{initials(item.name)}</span>
                    <div><b>{item.text}</b><small>{item.name} · {item.when}</small></div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

````

## `apps/web/src/components/landing/tilt.tsx`

````tsx
"use client";

import { useRef, type PointerEvent, type ReactNode } from "react";

const MOUSE_ONLY = "(hover: hover) and (prefers-reduced-motion: no-preference)";

/** Leans its contents towards the mouse, and moves a soft sheen with it. Touch and reduced-motion visitors get a plain frame. */
export function Tilt({ className, maxDegrees = 4, children }: { className: string; maxDegrees?: number; children: ReactNode }) {
  // Measured once on entry: the tilt itself changes the frame's box, which would feed back into the angle.
  const rect = useRef<DOMRect | null>(null);

  const enter = (ev: PointerEvent<HTMLDivElement>) => {
    if (ev.pointerType !== "mouse" || !window.matchMedia(MOUSE_ONLY).matches) return;
    rect.current = ev.currentTarget.getBoundingClientRect();
    ev.currentTarget.classList.add("is-tilting");
  };

  const move = (ev: PointerEvent<HTMLDivElement>) => {
    const box = rect.current;
    if (!box) return;
    const x = (ev.clientX - box.left) / box.width;
    const y = (ev.clientY - box.top) / box.height;
    const { style } = ev.currentTarget;
    style.setProperty("--tilt-x", `${(0.5 - y) * 2 * maxDegrees}deg`);
    style.setProperty("--tilt-y", `${(x - 0.5) * 2 * maxDegrees}deg`);
    style.setProperty("--sheen-x", `${x * 100}%`);
    style.setProperty("--sheen-y", `${y * 100}%`);
  };

  const leave = (ev: PointerEvent<HTMLDivElement>) => {
    rect.current = null;
    ev.currentTarget.classList.remove("is-tilting");
    ev.currentTarget.style.removeProperty("--tilt-x");
    ev.currentTarget.style.removeProperty("--tilt-y");
  };

  return (
    <div className={`tilt ${className}`} onPointerEnter={enter} onPointerMove={move} onPointerLeave={leave}>
      {children}
    </div>
  );
}

````

## `apps/web/src/components/landing/landing.css`

````css
.kx{--navy:#0A1230;--navy-2:#0F1D45;--ink:#111827;--muted:#5B6578;--line:#E3E8F2;--blue:#0780F2;--blue-d:#0236A0;--cyan:#00C2FF;--soft:#F4F7FD;
  font-size:16px;line-height:1.6;overflow-x:hidden;color:var(--ink);background:#fff;-webkit-font-smoothing:antialiased}
.kx *{box-sizing:border-box}
.kx a{color:inherit;text-decoration:none}
.kx img{max-width:100%}
.kx :focus-visible{outline:3px solid var(--blue);outline-offset:2px;border-radius:6px}
html:has(.kx){scroll-behavior:smooth;scroll-padding-top:84px}
.kx .wrap{max-width:1200px;margin:0 auto;padding:0 clamp(18px,3vw,40px)}
.kx h1,.kx h2,.kx h3,.kx p{margin:0}
.kx h1,.kx .h2,.kx .cta-card h2{font-family:var(--font-display),var(--font-inter),system-ui,sans-serif;text-wrap:balance}

/* header */
.kx .hdr{position:sticky;top:0;z-index:30;background:rgba(255,255,255,.88);backdrop-filter:blur(14px);border-bottom:1px solid var(--line)}
.kx .hdr-in{height:72px;display:flex;align-items:center;justify-content:space-between;gap:24px}
.kx .logo{display:inline-flex;align-items:center}
.kx .logo img{height:34px;width:auto;display:block}
.kx .nav{display:flex;gap:30px}
.kx .nav a{font-size:15px;font-weight:500;color:#334155;transition:color .2s}
.kx .nav a:hover{color:var(--blue)}
.kx .hdr-act{display:flex;align-items:center;gap:10px}
.kx .burger{display:none;width:44px;height:44px;border:1px solid var(--line);background:#fff;border-radius:10px;align-items:center;justify-content:center;cursor:pointer;color:var(--ink)}
.kx .mnav{border-top:1px solid var(--line);padding:8px clamp(18px,3vw,40px) 16px;display:flex;flex-direction:column;background:#fff}
.kx .mnav a{padding:14px 0;font-weight:500;border-bottom:1px solid var(--line)}

/* buttons */
.kx .btn{display:inline-flex;align-items:center;justify-content:center;gap:8px;height:46px;padding:0 22px;border-radius:999px;font:inherit;font-size:15px;font-weight:600;border:1px solid transparent;cursor:pointer;transition:transform .2s,box-shadow .2s,background .2s,border-color .2s;white-space:nowrap}
.kx .btn:hover{transform:translateY(-2px)}
.kx .btn-dark{background:var(--navy);color:#fff!important;box-shadow:0 10px 24px -12px rgba(10,18,48,.6)}
.kx .btn-dark:hover{background:var(--navy-2)}
.kx .btn-blue{background:linear-gradient(135deg,#0A9BFF,#0657E6);color:#fff!important;box-shadow:0 12px 28px -12px rgba(7,128,242,.7)}
.kx .btn-ghost{background:#fff;border-color:#CBD5E5;color:var(--ink)}
.kx .btn-ghost:hover{border-color:var(--blue);color:var(--blue)}
.kx .btn-sm{height:40px;padding:0 18px;font-size:14px}
.kx .btn-light{background:#fff;color:var(--navy)!important}
.kx .link-quiet{font-size:15px;font-weight:500;color:#334155;padding:0 8px}

/* shared type */
.kx .pill{display:inline-flex;align-items:center;gap:8px;padding:6px 14px;border-radius:999px;background:#EAF3FF;border:1px solid #CFE3FF;color:#0657E6;font-size:12.5px;font-weight:600;letter-spacing:.04em}
.kx .pill .dot{width:7px;height:7px;border-radius:50%;background:var(--blue)}
.kx .h2{font-size:clamp(2rem,4vw,3.4rem);line-height:1.1;letter-spacing:-.025em;font-weight:800}
.kx .lead{color:var(--muted);font-size:clamp(1rem,1.3vw,1.15rem);max-width:640px}
.kx .center{text-align:center}
.kx .center .lead{margin-left:auto;margin-right:auto}
.kx .mute{color:#7A869C}
.kx .hl{display:inline-block;padding:0 .22em .06em;border-radius:.32em;background:linear-gradient(120deg,#0A9BFF,#0657E6);color:#fff;box-shadow:0 14px 34px -14px rgba(7,128,242,.8)}
.kx section{padding:clamp(60px,8vw,112px) 0}

/* hero */
.kx .hero{padding-bottom:clamp(40px,5vw,72px);background:radial-gradient(60% 50% at 50% 0,#DCEBFF 0,rgba(220,235,255,0) 70%),linear-gradient(180deg,#F5F9FF 0,#fff 100%);position:relative;text-align:center}
.kx .hero h1{font-size:clamp(2.6rem,6.2vw,5rem);line-height:1.08;letter-spacing:-.028em;font-weight:800;margin:22px auto 0;max-width:900px}
.kx .hero .lead{margin:22px auto 0}
.kx .cta-row{display:flex;flex-wrap:wrap;gap:12px;justify-content:center;margin-top:32px}

/* product window */
.kx .win{margin:clamp(40px,5vw,64px) auto 0;max-width:1060px;background:var(--navy);border-radius:22px;border:1px solid #1D2C5E;box-shadow:0 50px 90px -40px rgba(10,18,48,.7),0 0 0 8px rgba(255,255,255,.6);overflow:hidden;text-align:left;color:#E6ECFA}
.kx .win-bar{display:flex;align-items:center;gap:7px;padding:12px 16px;border-bottom:1px solid #1B2A58}
.kx .win-bar i{width:10px;height:10px;border-radius:50%;background:#2A3A6E}
.kx .win-body{display:grid;grid-template-columns:190px 1fr 250px;min-height:340px}
.kx .win-side{padding:18px 14px;border-right:1px solid #1B2A58;display:flex;flex-direction:column;gap:4px}
.kx .win-side img{height:26px;width:auto;margin:0 0 16px 6px;align-self:flex-start}
.kx .win-side span{display:flex;align-items:center;gap:10px;padding:9px 12px;border-radius:10px;font-size:13.5px;color:#9DB0DC}
.kx .win-side span.on{background:linear-gradient(120deg,#0A8BF5,#0657E6);color:#fff;font-weight:600}
.kx .win-main{padding:20px;min-width:0}
.kx .win-main h3{font-size:15px;font-weight:600;margin-bottom:14px;color:#fff}
.kx .kpis{display:grid;grid-template-columns:repeat(3,1fr);gap:10px}
.kx .kpi{background:#121F4A;border:1px solid #1D2C5E;border-radius:14px;padding:12px 14px}
.kx .kpi small{display:block;font-size:11.5px;color:#8FA3D4}
.kx .kpi b{font-size:22px;letter-spacing:-.02em;color:#fff}
.kx .kpi em{font-style:normal;font-size:11.5px;color:#4ADE80;margin-left:6px}
.kx .chart{margin-top:12px;background:#121F4A;border:1px solid #1D2C5E;border-radius:14px;padding:14px 16px 10px}
.kx .chart small{font-size:11.5px;color:#8FA3D4}
.kx .bars{display:flex;align-items:flex-end;gap:12px;height:132px;margin-top:10px}
.kx .bars div{flex:1;display:flex;flex-direction:column;align-items:center;gap:6px;height:100%;justify-content:flex-end;font-size:11px;color:#8FA3D4}
.kx .bars b{font-size:11.5px;font-weight:600;color:#E6ECFA}
.kx .bars span{width:100%;max-width:38px;min-height:4px;border-radius:8px 8px 3px 3px;background:linear-gradient(180deg,#00C2FF,#0657E6);transform-origin:bottom;animation:kBar .9s cubic-bezier(.16,1,.3,1) both}
.kx .feed{padding:20px 16px;border-left:1px solid #1B2A58;display:flex;flex-direction:column;gap:10px}
.kx .feed h3{font-size:13px;font-weight:600;color:#fff;display:flex;align-items:center;gap:8px}
.kx .live{width:8px;height:8px;border-radius:50%;background:#4ADE80;animation:kPulse 2s ease-in-out infinite}
.kx .feed-i{display:flex;gap:10px;align-items:center;background:#121F4A;border:1px solid #1D2C5E;border-radius:12px;padding:9px 11px;font-size:12.5px;line-height:1.35}
.kx .feed-i small{display:block;color:#8FA3D4;font-size:11.5px}

/* avatars (initials, sample people) */
.kx .av{width:38px;height:38px;border-radius:50%;flex:none;display:inline-flex;align-items:center;justify-content:center;color:#fff;font-size:13px;font-weight:700;letter-spacing:.02em}
.kx .av.sm{width:30px;height:30px;font-size:11px}

/* core hr: directory mock */
.kx .ticks{list-style:none;padding:0;margin:26px 0 30px;display:flex;flex-direction:column;gap:12px}
.kx .ticks li{display:flex;align-items:center;gap:12px;font-weight:500;color:#334155}
.kx .dir{overflow:hidden;padding-bottom:6px}
.kx .dir-h{display:flex;justify-content:space-between;align-items:center;gap:12px;padding:18px 22px;border-bottom:1px solid var(--line);font-size:13px;color:var(--muted)}
.kx .dir-h b{color:var(--ink);font-size:15px}
.kx .dir-search{display:flex;align-items:center;gap:8px;margin:16px 22px 8px;padding:10px 14px;border:1px solid var(--line);border-radius:12px;color:#94A3B8;font-size:13.5px;background:var(--soft)}
.kx .dir-row{display:grid;grid-template-columns:auto 1fr auto;gap:12px;align-items:center;padding:12px 22px}
.kx .dir-row+.dir-row{border-top:1px solid var(--line)}
.kx .dir-row b{display:block;font-size:14.5px;line-height:1.3}
.kx .dir-row small{display:block;color:var(--muted);font-size:12.5px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.kx .dir-row>div{min-width:0}
.kx .st{display:inline-flex;align-items:center;gap:6px;padding:3px 10px;border-radius:999px;font-size:12px;font-weight:600;white-space:nowrap}
.kx .st::before{content:"";width:6px;height:6px;border-radius:50%;background:currentColor}
.kx .st.in{background:#DCFCE7;color:#166534}.kx .st.leave{background:#FEF3C7;color:#92400E}.kx .st.out{background:#F1F5F9;color:#64748B}

/* payroll */
.kx .card{background:#fff;border:1px solid var(--line);border-radius:20px;box-shadow:0 30px 60px -36px rgba(10,18,48,.35)}
.kx .tbl{max-width:920px;margin:48px auto 0;padding:8px 0;overflow-x:auto}
.kx .tbl-h{display:flex;justify-content:space-between;align-items:center;padding:14px 24px;font-size:13px;color:var(--muted);gap:12px}
.kx .tbl-h b{color:var(--ink);font-size:15px}
.kx table{width:100%;border-collapse:collapse;min-width:620px;font-size:14px}
.kx th{text-align:left;font-weight:600;font-size:12px;color:var(--muted);text-transform:uppercase;letter-spacing:.06em;padding:10px 24px;background:var(--soft)}
.kx td{padding:14px 24px;border-top:1px solid var(--line)}
.kx td .who{display:flex;align-items:center;gap:10px;font-weight:600}
.kx .tag{display:inline-block;padding:3px 11px;border-radius:999px;font-size:12px;font-weight:600}
.kx .tag.ok{background:#DCFCE7;color:#166534}.kx .tag.wip{background:#FEF3C7;color:#92400E}.kx .tag.wait{background:#E0E7FF;color:#3730A3}
.kx .grid3{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,300px),1fr));gap:20px}
.kx .feat{padding:28px;transition:transform .3s cubic-bezier(.16,1,.3,1),box-shadow .3s,border-color .3s}
.kx .feat:hover{transform:translateY(-5px);border-color:#9CCBFF;box-shadow:0 30px 56px -28px rgba(7,128,242,.4)}
.kx .ico{width:46px;height:46px;border-radius:14px;display:flex;align-items:center;justify-content:center;color:#fff;background:linear-gradient(135deg,#0A9BFF,#0236A0);margin-bottom:18px;box-shadow:0 12px 24px -12px rgba(7,128,242,.8);flex:none}
.kx .ico-soft{background:#EAF3FF;color:#0657E6;box-shadow:none;border:1px solid #CFE3FF}
.kx .feat h3{font-size:1.2rem;letter-spacing:-.02em;margin-bottom:8px}
.kx .feat p{color:var(--muted);font-size:15px}

/* capacity */
.kx .cap{background:var(--soft)}
.kx .split{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,420px),1fr));gap:clamp(32px,5vw,72px);align-items:center}
.kx .stats{display:flex;flex-wrap:wrap;gap:12px 40px;margin:30px 0}
.kx .stats b{display:block;font-size:2.2rem;letter-spacing:-.04em;font-weight:800;line-height:1.1}
.kx .stats span{font-size:13.5px;color:var(--muted)}
.kx .dark{background:var(--navy);color:#E6ECFA;border-radius:22px;padding:clamp(20px,3vw,30px);border:1px solid #1D2C5E;box-shadow:0 40px 80px -40px rgba(10,18,48,.8)}
.kx .dark-h{display:flex;justify-content:space-between;align-items:center;margin-bottom:18px;font-size:13px;color:#8FA3D4}
.kx .dark-h b{color:#fff;font-size:15px}
.kx .row{display:grid;grid-template-columns:110px 1fr 40px;gap:12px;align-items:center;padding:10px 0;font-size:13.5px}
.kx .row .trk{height:9px;border-radius:99px;background:#1A2957;overflow:hidden}
.kx .row .trk i{display:block;height:100%;border-radius:99px;background:linear-gradient(90deg,#00C2FF,#0657E6);transform-origin:left;animation:kGrow 1s cubic-bezier(.16,1,.3,1) both}
.kx .row b{color:#fff;text-align:right}
.kx .dark-f{margin-top:14px;padding-top:14px;border-top:1px solid #1B2A58;display:flex;gap:10px;align-items:center;font-size:13px;color:#9DB0DC}

/* workflows */
.kx .wf{padding:24px;display:flex;flex-direction:column;gap:18px}
.kx .wf h3{font-size:1.25rem;letter-spacing:-.02em}
.kx .wf p{color:var(--muted);font-size:15px;margin-top:6px}
.kx .mini{background:var(--soft);border:1px solid var(--line);border-radius:14px;padding:14px;display:flex;flex-direction:column;gap:9px;font-size:13.5px;margin-top:auto}
.kx .mini div{display:flex;align-items:center;justify-content:space-between;gap:10px}
.kx .tick{width:20px;height:20px;border-radius:50%;display:inline-flex;align-items:center;justify-content:center;background:#DCFCE7;color:#166534;flex:none}
.kx .tick.todo{background:#E2E8F0;color:#64748B}
.kx .tick.go{background:#DBEAFE;color:#1D4ED8}

/* mobile app: phone mock */
.kx .phone{width:300px;max-width:100%;margin:0 auto;background:var(--navy);border-radius:46px;padding:11px;border:1px solid #1D2C5E;box-shadow:0 50px 90px -40px rgba(10,18,48,.7),0 0 0 6px rgba(255,255,255,.7)}
.kx .scr{background:var(--soft);border-radius:36px;overflow:hidden;padding:0 16px 20px;display:flex;flex-direction:column;gap:12px}
.kx .notch{width:100px;height:26px;background:var(--navy);border-radius:0 0 16px 16px;margin:0 auto 4px}
.kx .ph-top{font-size:13px;color:var(--muted);line-height:1.3}
.kx .ph-top b{display:block;font-size:20px;color:var(--ink);letter-spacing:-.02em}
.kx .today{background:linear-gradient(135deg,#0A1230,#0F2A6B 70%,#0657E6);color:#fff;border-radius:20px;padding:16px;display:flex;flex-direction:column;gap:4px}
.kx .today small{font-size:11.5px;color:#BFD0F2}
.kx .today b{font-size:17px}
.kx .punch{margin-top:10px;display:flex;align-items:center;justify-content:center;gap:8px;height:42px;border-radius:999px;background:#fff;color:var(--navy);font-weight:700;font-size:14px}
.kx .qa{display:grid;grid-template-columns:1fr 1fr;gap:8px}
.kx .qa div{background:#fff;border:1px solid var(--line);border-radius:14px;padding:11px 12px;color:#0657E6;line-height:1.3}
.kx .qa b{display:block;margin-top:6px;color:var(--ink);font-size:13px}
.kx .qa small{color:var(--muted);font-size:11px}
.kx .month{background:#fff;border:1px solid var(--line);border-radius:14px;padding:12px 14px}
.kx .month small{font-size:11.5px;color:var(--muted)}
.kx .month div{display:flex;justify-content:space-between;margin-top:6px}
.kx .month span{font-size:11.5px;color:var(--muted)}
.kx .month span b{display:block;font-size:18px;color:var(--ink);letter-spacing:-.02em}
.kx .mfeat{display:flex;flex-direction:column;gap:22px;margin-top:30px}
.kx .mfeat>div{display:flex;gap:16px;align-items:flex-start}
.kx .mfeat .ico{margin:0}
.kx .mfeat h3{font-size:1.08rem;letter-spacing:-.01em}
.kx .mfeat p{color:var(--muted);font-size:15px;margin-top:2px}

/* modules */
.kx .mods{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin-top:48px;max-width:960px;margin-left:auto;margin-right:auto}
.kx .mod{padding:22px 16px;text-align:center;display:flex;flex-direction:column;align-items:center;gap:10px;font-weight:600;font-size:14.5px}
.kx .mod .ico{margin:0}

/* trust */
.kx .trust{background:var(--navy);color:#fff;position:relative;overflow:hidden}
.kx .trust::before{content:"";position:absolute;inset:-30% -10% auto auto;width:560px;height:560px;background:radial-gradient(circle,rgba(7,128,242,.38),rgba(7,128,242,0) 65%)}
.kx .trust .lead{color:#AFC0E6}
.kx .tgrid{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,240px),1fr));gap:18px;margin-top:46px;position:relative}
.kx .t{padding:24px;border-radius:18px;background:rgba(255,255,255,.05);border:1px solid rgba(255,255,255,.1)}
.kx .t h3{font-size:1.05rem;margin:14px 0 6px}
.kx .t p{font-size:14.5px;color:#AFC0E6}

/* faq */
.kx .faq{max-width:820px;margin:44px auto 0;border-bottom:1px solid var(--line)}
.kx .faq-i{border-top:1px solid var(--line)}
.kx .faq button{width:100%;display:flex;justify-content:space-between;align-items:center;gap:16px;text-align:left;padding:20px 0;min-height:44px;background:none;border:0;font:inherit;font-size:1.08rem;font-weight:600;color:var(--ink);cursor:pointer}
.kx .faq p{color:var(--muted);padding:0 0 20px;max-width:680px}

/* cta */
.kx .cta{padding:0 0 clamp(56px,7vw,96px)}
.kx .cta-card{position:relative;overflow:hidden;background:linear-gradient(135deg,#0A1230,#0F2A6B 70%,#0657E6);border-radius:28px;padding:clamp(36px,6vw,80px) clamp(20px,5vw,64px);text-align:center;color:#fff}
.kx .cta-card::before{content:"";position:absolute;left:50%;top:-40%;width:720px;height:520px;transform:translateX(-50%);background:radial-gradient(circle,rgba(0,194,255,.35),rgba(0,194,255,0) 65%)}
.kx .cta-card>*{position:relative}
.kx .cta-card h2{font-size:clamp(2rem,4vw,3.3rem);line-height:1.08;letter-spacing:-.035em;font-weight:800;max-width:720px;margin:0 auto}
.kx .cta-card p{color:#BFD0F2;margin:16px auto 0;max-width:520px}
.kx .cta-form{display:flex;flex-wrap:wrap;gap:10px;max-width:520px;margin:32px auto 0;background:rgba(255,255,255,.1);border:1px solid rgba(255,255,255,.2);border-radius:999px;padding:6px}
.kx .cta-form input{flex:1;min-width:180px;height:46px;background:transparent;border:0;color:#fff;font:inherit;padding:0 18px;border-radius:999px}
.kx .cta-form input::placeholder{color:#9FB4E2}
.kx .cta-form input:focus-visible{outline:2px solid #fff;outline-offset:-2px}
.kx .cta-err{color:#FCA5A5;font-size:13.5px;margin-top:10px;min-height:20px}
.kx .cta-ok{margin-top:28px;font-weight:600}

/* footer */
.kx .ftr{background:var(--navy);color:#AFC0E6;padding:clamp(44px,5vw,72px) 0 28px}
.kx .ftr img{height:34px;width:auto;display:block}
.kx .ftr-top{display:flex;flex-wrap:wrap;justify-content:space-between;gap:36px}
.kx .ftr-top p{max-width:320px;margin-top:14px;font-size:15px}
.kx .ftr-cols{display:flex;flex-wrap:wrap;gap:36px 64px}
.kx .ftr-cols h4{margin:0 0 12px;color:#fff;font-size:14px}
.kx .ftr-cols a{display:block;padding:4px 0;font-size:14.5px;transition:color .2s}
.kx .ftr-cols a:hover{color:#fff}
.kx .ftr-bot{margin-top:40px;padding-top:20px;border-top:1px solid #1B2A58;display:flex;flex-wrap:wrap;justify-content:space-between;gap:8px;font-size:13.5px}

@keyframes kBar{from{transform:scaleY(.1);opacity:.3}to{transform:scaleY(1);opacity:1}}
@keyframes kGrow{from{transform:scaleX(0)}to{transform:scaleX(1)}}
@keyframes kPulse{0%,100%{transform:scale(1);opacity:1}50%{transform:scale(1.6);opacity:.4}}
@keyframes kUp{from{opacity:0;transform:translateY(22px)}to{opacity:1;transform:none}}
.kx .up{animation:kUp .8s cubic-bezier(.16,1,.3,1) both}
.kx .d1{animation-delay:.1s}.kx .d2{animation-delay:.2s}.kx .d3{animation-delay:.3s}

@media(max-width:960px){
  .kx .win-body{grid-template-columns:1fr}
  .kx .win-side,.kx .feed{display:none}
}
@media(max-width:720px){
  .kx .mods{grid-template-columns:1fr 1fr}
}
@media(max-width:600px){
  .kx table{min-width:0}
  .kx th:nth-child(2),.kx td:nth-child(2){display:none}
  .kx th,.kx td{padding-left:14px;padding-right:14px}
  .kx .tbl-h{padding:14px}
}
@media(max-width:880px){
  .kx .nav,.kx .hide-m{display:none!important}
  .kx .burger{display:inline-flex}
}
@media(max-width:520px){
  .kx .kpis{grid-template-columns:1fr 1fr}
  .kx .kpi:last-child{grid-column:span 2}
  .kx .dir-h span{display:none}
  .kx .row{grid-template-columns:90px 1fr 34px}
}
@media(prefers-reduced-motion:reduce){
  html:has(.kx){scroll-behavior:auto}
  .kx *,.kx *::before,.kx *::after{animation:none!important;transition:none!important}
}

/* real product screenshots */
.kx .shot-img{display:block;width:100%;height:auto}
.kx .win .shot-img{border-radius:0 0 21px 21px}
.kx .shot{overflow:hidden;padding:0}
.kx .shot-center{max-width:920px;margin:48px auto 32px}

/* mascot */
.kx .mascot{display:block;height:auto;pointer-events:none;user-select:none}
.kx .win-stage{position:relative;max-width:1060px;margin:clamp(40px,5vw,64px) auto 0}
.kx .win-stage .win{margin:0;position:relative}
.kx .hold-stage{position:relative}
.kx .hold-stage .win{z-index:1;box-shadow:0 50px 90px -40px rgba(10,18,48,.7)}
.kx .mascot-faq{width:112px;margin:0 auto 8px}
.kx .mascot-cta{position:absolute;right:clamp(12px,4vw,56px);bottom:-14px;width:clamp(120px,14vw,170px)}
@media(max-width:880px){.kx .mascot-cta{display:none}}

/* animated hero dashboard: sized in --u (1/1280 of its own width) so it scales like a screenshot */
.kx .hd{container-type:inline-size;aspect-ratio:16/9;overflow:hidden;border-radius:0 0 21px 21px;--u:calc(100cqw/1280)}
.kx .hd-still{display:none}
.kx .hd-app{display:grid;grid-template-columns:calc(var(--u)*210) 1fr;height:100%;background:#F8FAFC;color:#0F172A;font-size:calc(var(--u)*12.5);line-height:1.3}
.kx .hd svg{flex:none}
.kx .hd p{margin:0}
.kx .hd small{font-size:calc(var(--u)*11);font-weight:500;color:#64748B}
.kx .hd small.up{color:#15803D;font-weight:600}
.kx .hd small.down{color:#B45309;font-weight:600}
.kx .hd-side{background:#0B1533;padding:calc(var(--u)*18) calc(var(--u)*10);color:#CBD5E1;overflow:hidden}
.kx .hd-side img{display:block;height:calc(var(--u)*26);width:auto;margin:0 0 calc(var(--u)*8) calc(var(--u)*8)}
.kx .hd-side p{font-size:calc(var(--u)*10);letter-spacing:.06em;text-transform:uppercase;color:#7F8CAD;margin:calc(var(--u)*14) calc(var(--u)*10) calc(var(--u)*5)}
.kx .hd-side span{display:flex;align-items:center;gap:calc(var(--u)*10);padding:calc(var(--u)*6.5) calc(var(--u)*10);border-radius:calc(var(--u)*20)}
.kx .hd-side span.on{background:#00C2FF;color:#07132F;font-weight:600}
.kx .hd-side svg{width:calc(var(--u)*15);height:calc(var(--u)*15)}
.kx .hd-main{min-width:0;display:flex;flex-direction:column;overflow:hidden}
.kx .hd-top{display:flex;align-items:center;gap:calc(var(--u)*10);height:calc(var(--u)*52);flex:none;padding:0 calc(var(--u)*22);background:#fff;border-bottom:1px solid #E2E8F0}
.kx .hd-top b{font-weight:600}
.kx .hd-top>i{width:1px;height:calc(var(--u)*16);background:#E2E8F0}
.kx .hd-top>svg{width:calc(var(--u)*16);height:calc(var(--u)*16);color:#475569}
.kx .hd-search{display:flex;align-items:center;gap:calc(var(--u)*8);width:calc(var(--u)*240);margin:0 auto;padding:calc(var(--u)*7) calc(var(--u)*11);border-radius:calc(var(--u)*7);background:#F1F5F9;color:#64748B}
.kx .hd-search svg{width:calc(var(--u)*14);height:calc(var(--u)*14)}
.kx .hd-av{display:grid;place-items:center;flex:none;width:calc(var(--u)*28);height:calc(var(--u)*28);border-radius:50%;background:#EFF6FF;color:#1D4ED8;font-size:calc(var(--u)*10);font-weight:600}
.kx .hd-body{padding:calc(var(--u)*16) calc(var(--u)*22);display:flex;flex-direction:column;gap:calc(var(--u)*13)}
.kx .hd-head{display:flex;align-items:center;gap:calc(var(--u)*10)}
.kx .hd-head>div{margin-right:auto}
.kx .hd-head h4{margin:0;font-size:calc(var(--u)*20);font-weight:600;color:#0F172A}
.kx .hd-head p{color:#475569}
.kx .hd-live{display:flex;align-items:center;gap:calc(var(--u)*6);padding:calc(var(--u)*5) calc(var(--u)*10);border-radius:calc(var(--u)*20);background:#ECFDF5;color:#15803D;font-weight:600}
.kx .hd-live i{width:calc(var(--u)*7);height:calc(var(--u)*7);border-radius:50%;background:#16A34A;animation:kPulse 1.8s ease-in-out infinite}
.kx .hd-range{display:flex;align-items:center;gap:calc(var(--u)*7);padding:calc(var(--u)*6) calc(var(--u)*10);border-radius:calc(var(--u)*7);background:#fff;border:1px solid #E2E8F0}
.kx .hd-range svg{width:calc(var(--u)*14);height:calc(var(--u)*14);color:#2563EB}
.kx .hd-card{background:#fff;border:1px solid #E2E8F0;border-radius:calc(var(--u)*12);padding:calc(var(--u)*14);min-width:0}
.kx .hd em{display:grid;place-items:center;flex:none;width:calc(var(--u)*32);height:calc(var(--u)*32);border-radius:calc(var(--u)*8)}
.kx .hd em svg{width:calc(var(--u)*16);height:calc(var(--u)*16)}
.kx .hd em.blue{background:#EFF6FF;color:#2563EB}
.kx .hd em.green{background:#F0FDF4;color:#15803D}
.kx .hd em.amber{background:#FFFBEB;color:#B45309}
.kx .hd em.sky{background:#F0F9FF;color:#0369A1}
.kx .hd-kpis{display:grid;grid-template-columns:repeat(4,1fr);gap:calc(var(--u)*13)}
.kx .hd-kpis em{margin-bottom:calc(var(--u)*9)}
.kx .hd-kpi{display:flex;align-items:baseline;gap:calc(var(--u)*5);color:#64748B;font-size:calc(var(--u)*11);white-space:nowrap}
.kx .hd-kpi strong,.kx .hd-big strong{display:inline-block;font-size:calc(var(--u)*28);font-weight:700;color:#0F172A;font-variant-numeric:tabular-nums;line-height:1.25}
.kx .hd-note{color:#64748B;font-size:calc(var(--u)*11);white-space:nowrap}
.kx .hd-charts{display:grid;grid-template-columns:1fr 1fr 1fr;gap:calc(var(--u)*13)}
.kx .hd-title{display:flex;align-items:center;gap:calc(var(--u)*7);font-weight:600;font-size:calc(var(--u)*13);white-space:nowrap;margin-bottom:calc(var(--u)*8)}
.kx .hd-title>svg{width:calc(var(--u)*15);height:calc(var(--u)*15);color:#2563EB}
.kx .hd-sel,.kx .hd-link{display:flex;align-items:center;gap:calc(var(--u)*3);margin-left:auto;font-size:calc(var(--u)*11);font-weight:500}
.kx .hd-sel{padding:calc(var(--u)*4) calc(var(--u)*7);border:1px solid #E2E8F0;border-radius:calc(var(--u)*6)}
.kx .hd-link{color:#2563EB}
.kx .hd-sel svg,.kx .hd-link svg{width:calc(var(--u)*12);height:calc(var(--u)*12)}
.kx .hd-big{display:flex;align-items:baseline;gap:calc(var(--u)*6);color:#475569}
.kx .hd-growth{display:block;width:100%;height:auto;margin-top:calc(var(--u)*2)}
.kx .hd-growth text{font-size:8.5px;fill:#64748B}
.kx .hd-line{fill:none;stroke:#2563EB;stroke-width:1.8;stroke-linejoin:round;stroke-dasharray:1;animation:kHdLine 1.2s ease-out both paused}
.kx .hd-area{fill:#DBEAFE;fill-opacity:.65;animation:kHdFade .7s ease-out both paused}
.kx .hd-point circle{fill:#2563EB;stroke:#fff;stroke-width:1.2}
.kx .hd-point{animation:kHdFade .35s ease-out both paused}
.kx .hd-split{display:flex;align-items:center;gap:calc(var(--u)*12)}
.kx .hd-donut{width:calc(var(--u)*118);height:calc(var(--u)*118)}
.kx .hd-sweep{stroke-dasharray:100;animation:kHdDraw 1.1s cubic-bezier(.4,0,.2,1) both paused}
.kx .hd-slice{transition:stroke-dasharray .6s ease,stroke-dashoffset .6s ease}
.kx .hd-donut-n{font-size:7.5px;font-weight:700;fill:#0F172A;font-variant-numeric:tabular-nums}
.kx .hd-donut-l{font-size:3.2px;fill:#64748B}
.kx .hd-split ul{flex:1;min-width:0;list-style:none;margin:0;padding:0;display:grid;gap:calc(var(--u)*5)}
.kx .hd-split li{display:grid;grid-template-columns:calc(var(--u)*14) 1fr auto calc(var(--u)*38);align-items:center;white-space:nowrap;font-size:calc(var(--u)*11.5)}
.kx .hd-split li i{width:calc(var(--u)*8);height:calc(var(--u)*8);border-radius:50%}
.kx .hd-split li b{font-weight:600;font-variant-numeric:tabular-nums}
.kx .hd-split li small{text-align:right}
.kx .hd-lists{display:grid;grid-template-columns:repeat(4,1fr);gap:calc(var(--u)*13)}
.kx .hd-row{display:flex;align-items:center;gap:calc(var(--u)*9);padding:calc(var(--u)*5) 0}
.kx .hd-row>div{flex:1;min-width:0}
.kx .hd-row b,.kx .hd-row small{display:block;font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.kx .hd-row small{font-weight:500}
.kx .hd-row>small{flex:none}
.kx .hd-row>u{text-decoration:none;padding:calc(var(--u)*2) calc(var(--u)*7);border-radius:calc(var(--u)*5);background:#EFF6FF;color:#2563EB;font-size:calc(var(--u)*11)}
.kx .hd-row>svg{width:calc(var(--u)*14);height:calc(var(--u)*14);color:#64748B}
.kx .hd-dept{margin-bottom:calc(var(--u)*9)}
.kx .hd-dept span{display:flex;justify-content:space-between;margin-bottom:calc(var(--u)*4)}
.kx .hd-dept b{font-weight:600}
.kx .hd-dept div{height:calc(var(--u)*5);border-radius:calc(var(--u)*3);background:#E2E8F0;overflow:hidden}
.kx .hd-dept i{display:block;height:100%;border-radius:inherit;background:#2563EB;transform-origin:left;animation:kGrow .8s cubic-bezier(.16,1,.3,1) both paused}
.kx .hd-in{animation:kHdIn .7s cubic-bezier(.16,1,.3,1) both paused}
.kx .hd.play .hd-in,.kx .hd.play .hd-line,.kx .hd.play .hd-area,.kx .hd.play .hd-point,.kx .hd.play .hd-sweep,.kx .hd.play .hd-dept i{animation-play-state:running}
.kx .hd-bump{animation:kHdBump .55s ease-out}
.kx .hd-new{animation:kHdRow .5s cubic-bezier(.16,1,.3,1) both}
@keyframes kHdIn{from{opacity:0;transform:translateY(calc(var(--u)*14))}to{opacity:1;transform:none}}
@keyframes kHdDraw{from{stroke-dashoffset:100}to{stroke-dashoffset:0}}
@keyframes kHdLine{from{stroke-dashoffset:1}to{stroke-dashoffset:0}}
@keyframes kHdFade{from{opacity:0}to{opacity:1}}
@keyframes kHdBump{0%{transform:scale(1)}40%{transform:scale(1.14);color:#15803D}100%{transform:scale(1)}}
@keyframes kHdRow{from{opacity:0;transform:translateX(calc(var(--u)*12))}to{opacity:1;transform:none}}
@media(prefers-reduced-motion:reduce){
  .kx .hd{display:none}
  .kx .hd-still{display:block}
}

/* hover: screenshots lean towards the mouse, dashboard cards lift, the penguin hops */
@media(hover:hover) and (prefers-reduced-motion:no-preference){
  .kx .tilt{position:relative;overflow:hidden;transform:perspective(1400px) rotateX(var(--tilt-x,0deg)) rotateY(var(--tilt-y,0deg));transition:transform .5s cubic-bezier(.16,1,.3,1),box-shadow .3s ease}
  .kx .tilt.is-tilting{transition:transform .1s linear,box-shadow .3s ease;box-shadow:0 40px 70px -30px rgba(10,18,48,.45)}
  .kx .tilt::after{content:"";position:absolute;inset:0;pointer-events:none;opacity:0;background:radial-gradient(circle 340px at var(--sheen-x,50%) var(--sheen-y,50%),rgba(255,255,255,.14),transparent 70%);transition:opacity .3s ease}
  .kx .tilt.is-tilting::after{opacity:1}
  .kx .tilt .shot-img{transition:scale .5s cubic-bezier(.16,1,.3,1)}
  .kx .tilt.is-tilting .shot-img{scale:1.02}
  .kx .hd-card{transition:translate .25s ease,box-shadow .25s ease,border-color .25s ease}
  .kx .hd-card:hover{translate:0 calc(var(--u)*-3);border-color:#BFDBFE;box-shadow:0 calc(var(--u)*10) calc(var(--u)*22) calc(var(--u)*-10) rgba(37,99,235,.35)}
  .kx .hd-side span{transition:background-color .2s ease,color .2s ease}
  .kx .hd-side span:not(.on):hover{background:rgba(255,255,255,.09);color:#fff}
  .kx .mascot{pointer-events:auto;transition:scale .25s ease}
  .kx .mascot:hover{scale:1.07;animation:kHop .7s ease-in-out}
}
@keyframes kHop{0%,100%{transform:translateY(0) rotate(0)}30%{transform:translateY(-12px) rotate(-5deg)}60%{transform:translateY(-3px) rotate(4deg)}}
@media(hover:hover) and (prefers-reduced-motion:no-preference){
  /* The whole holding group leans as one, so only the window itself gets the frame effects. */
  .kx .tilt.hold-stage{overflow:visible}
  .kx .tilt.hold-stage::after{display:none}
  .kx .tilt.hold-stage.is-tilting{box-shadow:none}
  .kx .hold-stage .win::after{content:"";position:absolute;inset:0;z-index:1;pointer-events:none;opacity:0;background:radial-gradient(circle 340px at var(--sheen-x,50%) var(--sheen-y,50%),rgba(255,255,255,.14),transparent 70%);transition:opacity .3s ease}
  .kx .hold-stage.is-tilting .win::after{opacity:1}
}

/* hero setting: a soft tinted band behind the window's lower half, and cards floating over its edges */
.kx .hero::after{content:"";position:absolute;inset:auto 0 0;height:calc(clamp(40px,5vw,72px) + min(30vw,318px));border-radius:50% 50% 0 0/clamp(24px,5vw,72px) clamp(24px,5vw,72px) 0 0;background:radial-gradient(rgba(7,128,242,.16) 1.2px,transparent 1.3px) 0 0/22px 22px,radial-gradient(55% 80% at 50% 0,rgba(0,194,255,.2),transparent 75%),linear-gradient(180deg,#E6F0FF,#F4F7FD)}
.kx .hero .wrap{position:relative;z-index:1}
.kx .hero-chip{display:none}
@media(min-width:1360px){
  .kx .hero-chip{position:absolute;z-index:3;display:flex;align-items:center;gap:11px;width:206px;padding:11px 13px;background:#fff;border:1px solid #E3E8F2;border-radius:14px;box-shadow:0 22px 44px -18px rgba(10,18,48,.45);text-align:left;pointer-events:none;--chip-out:calc(-1*min(176px,(100vw - 1092px)/2));animation:kChipIn .7s var(--chip-at) cubic-bezier(.16,1,.3,1) both,kFloat 5s calc(var(--chip-at) + .7s) ease-in-out infinite}
  .kx .hero-chip b,.kx .hero-chip small{display:block;white-space:nowrap}
  .kx .hero-chip b{font-size:13.5px;font-weight:600;color:#111827}
  .kx .hero-chip small{font-size:11.5px;color:#5B6578}
  .kx .hero-chip-ico{display:grid;place-items:center;flex:none;width:36px;height:36px;border-radius:10px}
  .kx .hero-chip-ico.green{background:#ECFDF5;color:#15803D}
  .kx .hero-chip-ico.blue{background:#EFF6FF;color:#2563EB}
  .kx .hero-chip-ico.amber{background:#FFFBEB;color:#B45309}
  .kx .hero-chip-ico.cyan{background:#ECFEFF;color:#0E7490}
  .kx .hero-chip-1{--chip-at:.9s;left:var(--chip-out);top:17%}
  .kx .hero-chip-2{--chip-at:1.15s;left:var(--chip-out);top:68%}
  .kx .hero-chip-3{--chip-at:1.05s;right:var(--chip-out);top:30%}
  .kx .hero-chip-4{--chip-at:1.3s;right:var(--chip-out);top:76%}
}
@keyframes kChipIn{from{opacity:0;transform:translateY(18px) scale(.94)}to{opacity:1;transform:none}}
@keyframes kFloat{0%,100%{transform:translateY(0)}50%{transform:translateY(-7px)}}

````
