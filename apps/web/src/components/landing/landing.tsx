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

type MascotPose = "standing" | "waving" | "thinking" | "clipboard" | "celebrating" | "explaining" | "welcome" | "holding" | "holding-hands";

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
                <Mascot pose="holding" className="mascot-hero" />
                <div className="win">
                  <div className="win-bar"><i /><i /><i /></div>
                  <HeroDashboard />
                  {/* Shown instead of the animation under prefers-reduced-motion. */}
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img className="shot-img hd-still" src="/landing/product-dashboard.webp" width={1600} height={1000} loading="lazy" alt="The Krewoxa company dashboard: today's attendance, leave and items waiting on HR" />
                  <noscript><style>{".kx .hd *{animation:none!important}"}</style></noscript>
                </div>
                <Mascot pose="holding-hands" className="mascot-hero mascot-hands" />
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
