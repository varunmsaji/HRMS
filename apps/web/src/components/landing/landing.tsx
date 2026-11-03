"use client";

import { useState, type FormEvent } from "react";

import { Plus_Jakarta_Sans } from "next/font/google";
import Link from "next/link";
import {
  ArrowRight,
  BarChart3,
  CalendarCheck,
  Check,
  Clock,
  FileText,
  Fingerprint,
  History,
  LayoutDashboard,
  Layers,
  Lock,
  Menu,
  Minus,
  Play,
  Plus,
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

import "./landing.css";

// Display face for headings; self-hosted by next/font so the CSP is unaffected.
const display = Plus_Jakarta_Sans({ subsets: ["latin"], weight: ["700", "800"], variable: "--font-display", display: "swap" });

// Self-hosted in /public/landing (Unsplash licence) — the app CSP only allows same-origin images.
const IMG = (name: string) => `/landing/${name}.jpg`;
const LOGO = "/brand/krewoxa-logo.svg";
const LOGO_WHITE = "/brand/krewoxa-logo-white.svg";

/** Brand logo (mark + KREWOXA wordmark) straight from /public/brand. */
function BrandLogo({ onDark = false }: { onDark?: boolean }) {
  return (
    // eslint-disable-next-line @next/next/no-img-element
    <img src={onDark ? LOGO_WHITE : LOGO} alt="Krewoxa" width={159} height={34} />
  );
}

/** Decorative/sample imagery. */
function Img({ src, alt = "", className }: { src: string; alt?: string; className?: string }) {
  // eslint-disable-next-line @next/next/no-img-element
  return <img src={src} alt={alt} loading="lazy" className={className} />;
}

const NAV: [string, string][] = [
  ["Platform", "#platform"],
  ["Payroll", "#payroll"],
  ["Workflows", "#workflows"],
  ["Security", "#security"],
  ["FAQ", "#faq"],
];

const DAYS: [string, number][] = [["Mon", 94], ["Tue", 96], ["Wed", 91], ["Thu", 95], ["Fri", 88]];

const FEED: [string, string, string][] = [
  ["rahul-nair", "Rahul Nair checked in", "9:02 AM · Operations"],
  ["anjali-menon", "Leave request submitted", "Casual leave · 12–14 Nov"],
  ["fathima-rasheed", "Payroll review started", "Manager review"],
];

const PAY: [string, string, string, string, string][] = [
  ["anjali-menon", "Anjali Menon", "Design", "₹68,500", "ok"],
  ["rahul-nair", "Rahul Nair", "Operations", "₹82,000", "ok"],
  ["fathima-rasheed", "Fathima Rasheed", "People", "₹59,750", "wip"],
  ["joseph-thomas", "Joseph Thomas", "Finance", "₹74,200", "wip"],
  ["meera-pillai", "Meera Pillai", "Customer Care", "₹48,900", "wait"],
];
const PAY_TAG: Record<string, string> = { ok: "Approved", wip: "In review", wait: "Waiting" };

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
  ["Can employees and managers use it on mobile?", "Mobile access is part of our plans for employees and managers. Ask during a demo for what is available today."],
  ["How does onboarding work?", "Typically you set up the organization, add employee information, then configure the workflows you need. We will outline your specific steps in the demo."],
  ["How can we arrange a demo?", "Use the form at the bottom of this page and tell us where to reach you."],
];

const FOOT_PRODUCT: [string, string][] = [["Platform", "#platform"], ["Payroll", "#payroll"], ["Workflows", "#workflows"], ["Security", "#security"]];

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
            <h1 className="up d1">Shift your enterprise into <span className="hl">perfect sync.</span></h1>
            <p className="lead up d2">Krewoxa brings employee records, attendance, leave and payroll prep into one connected workspace, so your HR team spends less time chasing and more time leading.</p>
            <div className="cta-row up d3">
              <a href="#demo" className="btn btn-dark">Book a demo <ArrowRight size={16} /></a>
              <a href="#workflows" className="btn btn-ghost"><Play size={14} /> See how it works</a>
            </div>

            <div className="win up d3" role="img" aria-label="Illustrative Krewoxa dashboard showing headcount, attendance and live activity, using sample data">
              <div className="win-bar"><i /><i /><i /></div>
              <div className="win-body">
                <div className="win-side">
                  <Img src={LOGO_WHITE} />
                  <span className="on"><LayoutDashboard size={15} /> Dashboard</span>
                  <span><Users size={15} /> Employees</span>
                  <span><Clock size={15} /> Attendance</span>
                  <span><CalendarCheck size={15} /> Leave</span>
                  <span><Wallet size={15} /> Payroll</span>
                </div>
                <div className="win-main">
                  <h3>Workforce overview</h3>
                  <div className="kpis">
                    <div className="kpi"><small>Headcount</small><b>48</b><em>+3</em></div>
                    <div className="kpi"><small>Present today</small><b>41</b><em>85%</em></div>
                    <div className="kpi"><small>Pending approvals</small><b>3</b></div>
                  </div>
                  <div className="chart">
                    <small>Weekly attendance rate (%)</small>
                    <div className="bars">
                      {DAYS.map(([d, v], i) => (
                        <div key={d}>
                          <span style={{ height: `${v}%`, animationDelay: `${i * 0.08}s` }} />
                          {d}
                        </div>
                      ))}
                    </div>
                  </div>
                </div>
                <div className="feed">
                  <h3><span className="live" /> Live activity</h3>
                  {FEED.map(([img, t, s]) => (
                    <div className="feed-i" key={t}>
                      <Img src={IMG(`avatar-${img}`)} />
                      <div>{t}<small>{s}</small></div>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          </div>
        </section>

        {/* CORE HR */}
        <section id="platform" className="collage">
          <div className="ph ph1"><Img src={IMG("avatar-anjali-menon")} alt="Product designer" /></div>
          <div className="ph ph2"><Img src={IMG("team")} alt="Team collaborating" /></div>
          <div className="ph ph3"><Img src={IMG("avatar-rahul-nair")} alt="Operations manager" /></div>
          <div className="ph ph4"><Img src={IMG("hero")} alt="HR workspace" /></div>
          <div className="wrap">
            <div className="collage-in">
              <h2 className="h2">Core HR <span className="grad">solutions</span></h2>
              <p className="lead" style={{ margin: "18px auto 0" }}>Profiles, roles and departments live together instead of across files and chats, so every team starts from the same source of truth.</p>
              <div className="chips">
                {["Employee records", "Attendance", "Leave", "Documents", "Recruitment"].map((c) => <span className="chip" key={c}>{c}</span>)}
              </div>
              <div className="cta-row"><a href="#demo" className="btn btn-blue">Explore the platform</a></div>
            </div>
          </div>
        </section>

        {/* PAYROLL */}
        <section id="payroll">
          <div className="wrap center">
            <span className="pill"><Wallet size={14} /> PAYROLL PREP</span>
            <h2 className="h2" style={{ margin: "18px 0 16px" }}>Payroll prep at the speed of light.<br /><span className="grad">Zero spreadsheet friction.</span></h2>
            <p className="lead">Attendance, leave and approvals are reconciled before payroll reaches finance. One review, one clean summary.</p>

            <div className="card tbl" role="img" aria-label="Illustrative payroll review table using sample data" style={{ textAlign: "left" }}>
              <div className="tbl-h"><b>November payroll review</b><span>Sample data</span></div>
              <table>
                <thead><tr><th>Employee</th><th>Department</th><th>Net pay</th><th>Status</th></tr></thead>
                <tbody>
                  {PAY.map(([img, name, dept, amt, st]) => (
                    <tr key={name}>
                      <td><span className="who"><Img src={IMG(`avatar-${img}`)} />{name}</span></td>
                      <td>{dept}</td>
                      <td>{amt}</td>
                      <td><span className={`tag ${st}`}>{PAY_TAG[st]}</span></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

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
        <section className="cap">
          <div className="wrap split">
            <div>
              <span className="pill"><Zap size={14} /> WORKFORCE VISIBILITY</span>
              <h2 className="h2" style={{ margin: "18px 0 16px" }}>Dynamic capacity &amp; <span className="grad">headcount architecture.</span></h2>
              <p className="lead">See who is in, who is away and where teams are stretched, without compiling reports by hand.</p>
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
            <h2 className="h2" style={{ margin: "18px 0 16px" }}>Autonomous HR workflows.<br /><span className="grad">Zero busywork.</span></h2>
            <p className="lead">Define the path once. Krewoxa keeps requests moving and shows you exactly where each one stands.</p>
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

        {/* MODULES */}
        <section style={{ background: "var(--soft)" }}>
          <div className="wrap center">
            <h2 className="h2">Connects every part of HR <span className="grad">in one workspace.</span></h2>
            <p className="lead" style={{ marginTop: 16 }}>No more switching between tools to answer a simple question about your people.</p>
            <div className="mods">
              {MODULES.map(([Icon, label]) => (
                <div className="card mod" key={label}><div className="ico"><Icon size={22} /></div>{label}</div>
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
              <h2>Ready to shift your workforce into <span style={{ color: "#5CC8FF" }}>perfect sync?</span></h2>
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
            <span>© 2026 Krewoxa. Legal entity name to be confirmed.</span>
            <span>Privacy policy and terms: links to be added once published.</span>
          </div>
        </div>
      </footer>
    </div>
  );
}
