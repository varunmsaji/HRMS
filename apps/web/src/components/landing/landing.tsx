"use client";

import { Fragment, useState, type ChangeEvent, type CSSProperties, type FormEvent, type ReactNode } from "react";

import Link from "next/link";

import "./landing.css";

// Self-hosted in /public/landing (Unsplash licence) — the app CSP only allows same-origin images.
const IMG = (name: string) => `/landing/${name}.jpg`;
const slug = (name: string) => name.toLowerCase().replace(/\s+/g, "-");
const avatarOf = (name: string) => IMG(`avatar-${slug(name)}`);
const avatar = (i: number) => avatarOf(people[i][0]);

/** Decorative/sample imagery. */
function Img({ src, alt, style }: { src: string; alt: string; style?: CSSProperties }) {
  return (
    // eslint-disable-next-line @next/next/no-img-element
    <img src={src} alt={alt} loading="lazy" style={style} />
  );
}

const NAV = ["Dashboard", "Employees", "Attendance", "Leave", "Payroll", "Recruitment"];

const DAYS: [string, number][] = [["Mon", 94], ["Tue", 96], ["Wed", 91], ["Thu", 95], ["Fri", 88]];

const STATUS: Record<string, [string, string]> = {
  Pending: ["#FDF3E3", "#9A5A12"],
  Approved: ["#DBEAFE", "#1E40AF"],
  Declined: ["#FBE9EB", "#B42332"],
  Present: ["#DBEAFE", "#1E40AF"],
  Late: ["#FDF3E3", "#9A5A12"],
  "On leave": ["#E0F2FE", "#0369A1"],
  Absent: ["#FBE9EB", "#B42332"],
};

const values = [
  ["01", "More organized employee information", "Profiles, roles and departments live together instead of across files and chats."],
  ["02", "Clearer HR workflows", "Requests, approvals and follow-ups move through a defined path."],
  ["03", "Better visibility into daily activity", "Spot attendance and leave patterns without compiling reports by hand."],
];

const people = [
  ["Anjali Menon", "Product Designer", "Design"],
  ["Rahul Nair", "Operations Manager", "Operations"],
  ["Fathima Rasheed", "HR Executive", "People"],
  ["Joseph Thomas", "Accountant", "Finance"],
  ["Meera Pillai", "Support Lead", "Customer Care"],
];

const attendance = [
  ["Rahul Nair", "9:02 AM", "Present"],
  ["Fathima Rasheed", "9:15 AM", "Late"],
  ["Joseph Thomas", "Sick leave", "On leave"],
  ["Meera Pillai", "8:58 AM", "Present"],
  ["Anjali Menon", "Not checked in", "Absent"],
];

const payroll: [string, string, number][] = [
  ["Attendance reviewed", "Done", 2],
  ["Leave adjustments applied", "Done", 2],
  ["Manager review", "In progress", 1],
  ["Final approval", "Waiting", 0],
];

const modules = [
  ["Recruitment", "Track candidates through your hiring stages.", IMG("recruitment")],
  ["Employee documents", "Keep employee paperwork attached to the right profile.", IMG("documents")],
  ["Mobile access", "Let employees and managers handle requests on the go.", IMG("mobile")],
];

const steps = [
  ["1", "Set up your organization", "Add your company structure and bring in employee information."],
  ["2", "Configure your workflows", "Choose how attendance, leave and approvals should run for your team."],
  ["3", "Review and follow up", "Check activity in one place and act on what needs attention."],
];

const depts: [string, number][] = [["Operations", 14], ["Design", 9], ["Customer Care", 11], ["Finance", 6], ["People", 8]];
const months: [string, number][] = [["Jun", 92], ["Jul", 93], ["Aug", 90], ["Sep", 94], ["Oct", 95], ["Nov", 93]];

const actions = [
  ["3 leave requests awaiting approval", "Oldest submitted 2 days ago"],
  ["2 attendance corrections", "Submitted by team members"],
  ["1 new candidate to review", "Operations Executive role"],
  ["Payroll review in progress", "Manager review pending"],
];

const trust = [
  ["Role-based access", "Control what each person can see and do."],
  ["Organization data separation", "Each organization works in its own space."],
  ["Activity history", "Keep a record of important changes."],
  ["Secure sign-in", "Authentication details shared in your demo."],
];

const FAQS = [
  ["What is Krewoxa?", "Krewoxa is a Human Resource Management System that helps businesses organize employee information and everyday HR workflows in one workspace."],
  ["Which HR workflows does it support?", "Employee records, attendance, and leave are core areas. Payroll workflows, recruitment and documents are discussed in the demo so we can confirm what applies to you."],
  ["Is it suitable for a small or growing business?", "Krewoxa is designed for growing teams that need more structure than spreadsheets. A demo is the best way to judge the fit for your size."],
  ["Can employees and managers use it on mobile?", "Mobile access is part of our plans for employees and managers. Ask during a demo for what is available today."],
  ["How does onboarding work?", "Typically you set up the organization, add employee information, then configure the workflows you need. We will outline your specific steps in the demo."],
  ["How can we arrange a demo?", "Use the Book a demo form on this page and tell us a little about your team."],
];

const wrap: CSSProperties = { maxWidth: "1240px", margin: "0 auto", padding: "0 clamp(18px,3vw,40px)" };
const eyebrow: CSSProperties = { margin: "0 0 12px", fontSize: "14px", fontWeight: 600, letterSpacing: ".06em", textTransform: "uppercase", color: "#1D4ED8" };
const h2: CSSProperties = { margin: 0, fontSize: "clamp(2rem,3.2vw,3.1rem)", lineHeight: 1.12, letterSpacing: "-.03em", fontWeight: 700, color: "#102A43" };
const h3Story: CSSProperties = { margin: "0 0 14px", fontSize: "clamp(1.5rem,2.4vw,2.1rem)", lineHeight: 1.18, letterSpacing: "-.025em", color: "#102A43" };
const kicker: CSSProperties = { margin: "0 0 10px", fontWeight: 600, color: "#1D4ED8" };
const storyP: CSSProperties = { margin: "0 0 20px", color: "#5D6B78", maxWidth: "480px" };
const storyGrid: CSSProperties = { display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(min(100%,380px),1fr))", gap: "clamp(28px,5vw,72px)", alignItems: "center", marginBottom: "clamp(56px,7vw,104px)" };
const mockCard: CSSProperties = { background: "#fff", border: "1px solid #E2E8EF", borderRadius: "18px", padding: "20px", boxShadow: "0 18px 40px -26px rgba(16,42,67,.3)", minWidth: 0 };
const pill = (bg: string, c: string): CSSProperties => ({ fontSize: "12.5px", fontWeight: 600, padding: "3px 10px", borderRadius: "99px", background: bg, color: c });
const inputStyle: CSSProperties = { width: "100%", height: "46px", padding: "0 14px", border: "1px solid #C9D4DF", borderRadius: "10px", font: "inherit", color: "#172B3A" };
const labelStyle: CSSProperties = { display: "block", fontSize: "14px", fontWeight: 600, marginBottom: "6px", color: "#102A43" };
const navLink: CSSProperties = { color: "#172B3A", fontWeight: 500, fontSize: "15px" };
const mobLink: CSSProperties = { padding: "14px 0", color: "#172B3A", fontWeight: 500, borderBottom: "1px solid #E2E8EF" };

export function Landing() {
  const [menuOpen, setMenuOpen] = useState(false);
  const [openFaq, setOpenFaq] = useState(-1);
  const [activeNav, setActiveNav] = useState(0);
  const [leaveDecision, setLeaveDecision] = useState("Pending");
  const [sent, setSent] = useState(false);
  const [form, setForm] = useState({ name: "", email: "" });
  const [errors, setErrors] = useState<{ name?: string; email?: string }>({});

  const closeMenu = () => setMenuOpen(false);
  const [decBg, decColor] = STATUS[leaveDecision];

  const stats = [
    ["Employees", "48", "Sample headcount"],
    ["Present today", "41", "of 48 checked in"],
    ["On leave", "4", "Approved today"],
    ["Pending approvals", leaveDecision === "Pending" ? "3" : "2", "Needs review"],
  ];
  const leaves = [
    ["Anjali Menon", "Casual leave", "12–14 Nov", leaveDecision],
    ["Joseph Thomas", "Sick leave", "10 Nov", "Approved"],
    ["Meera Pillai", "Earned leave", "18–22 Nov", "Pending"],
  ];

  // Preview only: the demo form is not wired to a backend yet.
  const submit = (ev: FormEvent) => {
    ev.preventDefault();
    const er: { name?: string; email?: string } = {};
    if (!form.name.trim()) er.name = "Please enter your name.";
    if (!/^\S+@\S+\.\S+$/.test(form.email)) er.email = "Please enter a valid work email.";
    setErrors(er);
    setSent(!Object.keys(er).length);
  };

  return (
    <div className="kx">
      {/* HEADER */}
      <header style={{ position: "sticky", top: 0, zIndex: 20, background: "rgba(255,255,255,.96)", borderBottom: "1px solid #E2E8EF" }}>
        <div style={{ ...wrap, height: "76px", display: "flex", alignItems: "center", justifyContent: "space-between", gap: "24px" }}>
          <a href="#top" aria-label="Krewoxa home" style={{ fontSize: "25px", fontWeight: 700, letterSpacing: "-.03em", color: "#102A43" }}>Krewoxa<span style={{ color: "#2563EB" }}>.</span></a>
          <nav className="k-links" aria-label="Primary" style={{ display: "flex", gap: "32px" }}>
            <a href="#features" style={navLink}>Features</a>
            <a href="#solutions" style={navLink}>Solutions</a>
            <a href="#how" style={navLink}>How it works</a>
            <a href="#faq" style={navLink}>FAQ</a>
          </nav>
          <div style={{ display: "flex", alignItems: "center", gap: "12px" }}>
            <Link href="/login" className="k-hidem" style={{ ...navLink, padding: "0 8px" }}>Log in</Link>
            <Link href="/register" className="k-hidem kx-hover-3" style={{ display: "inline-flex", alignItems: "center", height: "44px", padding: "0 18px", borderRadius: "10px", border: "1px solid #C9D4DF", background: "#fff", color: "#102A43", fontWeight: 600, fontSize: "15px" }}>Register</Link>
            <a href="#demo" className="kx-hover-1" style={{ display: "inline-flex", alignItems: "center", height: "44px", padding: "0 20px", borderRadius: "10px", background: "#1D4ED8", color: "#fff", fontWeight: 600, fontSize: "15px", transition: "background .2s" }}>Book a demo</a>
            <button className="k-burger" onClick={() => setMenuOpen((o) => !o)} aria-label="Menu" aria-expanded={menuOpen} aria-controls="mobnav" style={{ width: "44px", height: "44px", border: "1px solid #E2E8EF", background: "#fff", borderRadius: "10px", alignItems: "center", justifyContent: "center", cursor: "pointer", fontSize: "20px", color: "#102A43" }}>{menuOpen ? "✕" : "☰"}</button>
          </div>
        </div>
        {menuOpen && (
          <nav id="mobnav" aria-label="Mobile" style={{ borderTop: "1px solid #E2E8EF", padding: "8px clamp(18px,3vw,40px) 16px", display: "flex", flexDirection: "column", background: "#fff" }}>
            <a href="#features" onClick={closeMenu} style={mobLink}>Features</a>
            <a href="#solutions" onClick={closeMenu} style={mobLink}>Solutions</a>
            <a href="#how" onClick={closeMenu} style={mobLink}>How it works</a>
            <a href="#faq" onClick={closeMenu} style={mobLink}>FAQ</a>
            <Link href="/login" onClick={closeMenu} style={mobLink}>Log in</Link>
            <Link href="/register" onClick={closeMenu} style={{ padding: "14px 0", color: "#1D4ED8", fontWeight: 600 }}>Register</Link>
          </nav>
        )}
      </header>

      <main id="top">
        {/* HERO */}
        <section style={{ background: "radial-gradient(circle at 85% 15%,#DBEAFE 0%,rgba(219,234,254,0) 48%),linear-gradient(180deg,#EFF6FF 0,#fff 100%)", padding: "clamp(48px,7vw,88px) 0 clamp(40px,6vw,80px)", position: "relative" }}>
          <div style={wrap}>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(min(100%,420px),1fr))", gap: "clamp(32px,4vw,56px)", alignItems: "center" }}>
              <div className="k-anim-up">
                <div style={{ margin: "0 0 20px", display: "inline-flex", alignItems: "center", gap: "10px", padding: "6px 14px", borderRadius: "99px", background: "#DBEAFE", border: "1px solid #BFDBFE", fontSize: "13px", fontWeight: 600, letterSpacing: ".04em", textTransform: "uppercase", color: "#1D4ED8" }}>
                  <span className="k-pulse" style={{ width: "8px", height: "8px", borderRadius: "50%", background: "#2563EB" }}></span>
                  HR management for growing teams
                </div>
                <h1 style={{ margin: 0, fontSize: "clamp(2.5rem,4.8vw,4.35rem)", lineHeight: 1.05, letterSpacing: "-.035em", fontWeight: 700, color: "#102A43" }}>Better HR. Clearer workflows. <span style={{ color: "#2563EB" }}>Stronger teams.</span></h1>
                <p style={{ margin: "24px 0 0", maxWidth: "580px", fontSize: "clamp(1.05rem,1.4vw,1.2rem)", color: "#5D6B78" }}>Bring your everyday HR operations together with Krewoxa. Organize employee information and simplify workforce workflows in one connected workspace.</p>
                <div style={{ marginTop: "32px", display: "flex", flexWrap: "wrap", gap: "12px" }}>
                  <a href="#demo" className="kx-hover-2" style={{ display: "inline-flex", alignItems: "center", justifyContent: "center", gap: "8px", height: "52px", padding: "0 28px", borderRadius: "10px", background: "#1D4ED8", color: "#fff", fontWeight: 600, boxShadow: "0 12px 24px -10px rgba(29,78,216,.55)", transition: "background .2s,transform .2s" }}>Book a demo <span>→</span></a>
                  <a href="#features" className="kx-hover-3" style={{ display: "inline-flex", alignItems: "center", justifyContent: "center", height: "52px", padding: "0 28px", borderRadius: "10px", border: "1px solid #C9D4DF", background: "#fff", color: "#102A43", fontWeight: 600, transition: "border-color .2s,color .2s" }}>Explore features</a>
                </div>
                <div style={{ marginTop: "26px", display: "flex", alignItems: "center", gap: "14px", flexWrap: "wrap" }}>
                  <div style={{ display: "flex", alignItems: "center" }}>
                    {[0, 1, 2, 3].map((i) => (
                      <Img key={i} src={avatar(i)} alt="Team member portrait" style={{ width: "36px", height: "36px", borderRadius: "50%", border: "2px solid #fff", marginLeft: i ? "-10px" : 0, objectFit: "cover" }} />
                    ))}
                  </div>
                  <p style={{ margin: 0, fontSize: "14px", color: "#5D6B78" }}>See how Krewoxa fits your HR workflow in a guided walkthrough.</p>
                </div>
              </div>

              {/* product visual collage */}
              <div className="k-anim-up k-delay-1" style={{ position: "relative", padding: "18px 10px" }}>
                <div className="k-img-zoom" style={{ borderRadius: "22px", border: "1px solid #DBEAFE", boxShadow: "0 28px 60px -24px rgba(16,42,67,.28)", background: "#EFF6FF", position: "relative", height: "clamp(280px,34vw,390px)" }}>
                  <Img src={IMG("hero")} alt="Modern HR and operations team collaborating at a bright desk" />
                  <div style={{ position: "absolute", inset: 0, background: "linear-gradient(180deg,rgba(16,42,67,0) 45%,rgba(16,42,67,.72) 100%)" }}></div>
                  <div style={{ position: "absolute", bottom: "20px", left: "22px", right: "22px", color: "#fff" }}>
                    <span style={{ fontSize: "12px", fontWeight: 600, textTransform: "uppercase", letterSpacing: ".06em", padding: "4px 10px", borderRadius: "99px", background: "rgba(37,99,235,.85)" }}>Connected Workspace</span>
                    <div style={{ fontSize: "17px", fontWeight: 600, marginTop: "8px" }}>Built for people operations &amp; team leads</div>
                  </div>
                </div>
                <div className="k-float" style={{ position: "absolute", top: 0, left: 0, background: "#fff", border: "1px solid #DBEAFE", borderRadius: "14px", padding: "12px 16px", boxShadow: "0 18px 38px -12px rgba(16,42,67,.22)", display: "flex", alignItems: "center", gap: "12px", maxWidth: "250px" }}>
                  <div style={{ width: "38px", height: "38px", borderRadius: "10px", background: "#DBEAFE", color: "#1D4ED8", display: "flex", alignItems: "center", justifyContent: "center", fontWeight: 700, flex: "none" }}>✓</div>
                  <div>
                    <div style={{ fontSize: "13px", fontWeight: 600, color: "#102A43" }}>41 / 48 Checked in</div>
                    <div style={{ fontSize: "12px", color: "#5D6B78" }}>Live morning attendance</div>
                  </div>
                </div>
                <div className="k-float-alt" style={{ position: "absolute", bottom: "4px", right: 0, background: "#fff", border: "1px solid #DBEAFE", borderRadius: "14px", padding: "12px 16px", boxShadow: "0 18px 38px -12px rgba(16,42,67,.22)", display: "flex", alignItems: "center", gap: "12px", maxWidth: "265px" }}>
                  <Img src={avatar(0)} alt="Anjali Menon" style={{ width: "36px", height: "36px", borderRadius: "50%", objectFit: "cover", flex: "none" }} />
                  <div>
                    <div style={{ fontSize: "13px", fontWeight: 600, color: "#102A43" }}>Leave request approved</div>
                    <div style={{ fontSize: "11.5px", color: "#2563EB", fontWeight: 500 }}>Anjali M. · Casual leave</div>
                  </div>
                </div>
              </div>
            </div>

            {/* interactive hero dashboard */}
            <div role="img" aria-label="Illustrative Krewoxa dashboard showing headcount, attendance and leave requests, using sample data" className="k-anim-up k-delay-2" style={{ marginTop: "clamp(40px,5vw,64px)", background: "#fff", border: "1px solid #E2E8EF", borderRadius: "20px", boxShadow: "0 30px 70px -30px rgba(16,42,67,.35)", overflow: "hidden" }}>
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", flexWrap: "wrap", gap: "8px", padding: "12px 18px", borderBottom: "1px solid #E2E8EF", background: "#F7F9FB" }}>
                <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                  <span style={{ width: "10px", height: "10px", borderRadius: "50%", background: "#93C5FD" }}></span><span style={{ width: "10px", height: "10px", borderRadius: "50%", background: "#60A5FA" }}></span><span style={{ width: "10px", height: "10px", borderRadius: "50%", background: "#2563EB" }}></span>
                  <span style={{ marginLeft: "10px", fontSize: "12.5px", color: "#5D6B78" }}>Illustrative interface · click sidebar modules to preview</span>
                </div>
                <span style={{ fontSize: "12px", fontWeight: 600, color: "#1D4ED8", background: "#EFF6FF", padding: "4px 10px", borderRadius: "99px", border: "1px solid #DBEAFE" }}>Active view: {NAV[activeNav]}</span>
              </div>
              <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(min(100%,200px),1fr))" }}>
                <aside style={{ padding: "20px 16px", borderRight: "1px solid #E2E8EF", background: "#fff", display: "flex", flexDirection: "column", gap: "6px" }}>
                  <div style={{ fontWeight: 700, color: "#102A43", fontSize: "17px", padding: "0 10px 12px", letterSpacing: "-.02em" }}>Krewoxa<span style={{ color: "#2563EB" }}>.</span></div>
                  {NAV.map((label, i) => (
                    <button key={label} type="button" onClick={() => setActiveNav(i)} style={{ textAlign: "left", border: 0, cursor: "pointer", padding: "9px 12px", borderRadius: "8px", font: "inherit", fontSize: "14px", fontWeight: 500, background: i === activeNav ? "#DBEAFE" : "transparent", color: i === activeNav ? "#1E40AF" : "#5D6B78", transition: "background .2s,color .2s", display: "flex", alignItems: "center", justifyContent: "space-between" }}>
                      <span>{label}</span>
                      <span style={{ fontSize: "11px", opacity: i === activeNav ? 1 : 0 }}>●</span>
                    </button>
                  ))}
                </aside>
                <div style={{ gridColumn: "span 3", minWidth: 0, padding: "clamp(16px,2.4vw,28px)", background: "#F7F9FB", display: "flex", flexDirection: "column", gap: "16px" }}>
                  <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(min(100%,150px),1fr))", gap: "12px" }}>
                    {stats.map(([label, value, note]) => (
                      <div key={label} className="k-card" style={{ background: "#fff", border: "1px solid #E2E8EF", borderRadius: "14px", padding: "16px" }}>
                        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                          <div style={{ fontSize: "13px", color: "#5D6B78" }}>{label}</div>
                          <span style={{ width: "8px", height: "8px", borderRadius: "50%", background: "#DBEAFE" }}></span>
                        </div>
                        <div style={{ fontSize: "30px", fontWeight: 700, letterSpacing: "-.03em", color: "#102A43", marginTop: "2px" }}>{value}</div>
                        <div style={{ fontSize: "12.5px", color: "#2563EB", fontWeight: 500 }}>{note}</div>
                      </div>
                    ))}
                  </div>
                  <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(min(100%,300px),1fr))", gap: "12px" }}>
                    <div className="k-card" style={{ background: "#fff", border: "1px solid #E2E8EF", borderRadius: "14px", padding: "18px" }}>
                      <div style={{ display: "flex", justifyContent: "space-between", fontSize: "14px", fontWeight: 600, color: "#102A43" }}><span>Attendance this week</span><span style={{ fontWeight: 450, color: "#5D6B78" }}>% present</span></div>
                      <div style={{ display: "flex", alignItems: "flex-end", gap: "10px", height: "130px", marginTop: "16px" }}>
                        {DAYS.map(([day, v]) => (
                          <div key={day} style={{ flex: 1, display: "flex", flexDirection: "column", alignItems: "center", gap: "6px", justifyContent: "flex-end", height: "100%" }}>
                            <span style={{ fontSize: "11px", fontWeight: 600, color: "#1D4ED8" }}>{v}%</span>
                            <div className="k-bar" style={{ width: "100%", borderRadius: "6px 6px 0 0", background: day === "Fri" ? "#93C5FD" : "#2563EB", height: `${v}%` }}></div>
                            <span style={{ fontSize: "12px", color: "#5D6B78" }}>{day}</span>
                          </div>
                        ))}
                      </div>
                    </div>
                    <div className="k-card" style={{ background: "#fff", border: "1px solid #E2E8EF", borderRadius: "14px", padding: "18px" }}>
                      <div style={{ fontSize: "14px", fontWeight: 600, color: "#102A43", marginBottom: "8px" }}>Leave requests</div>
                      {leaves.map(([name, type, dates, status], i) => (
                        <div key={name} style={{ display: "flex", alignItems: "center", gap: "12px", padding: "10px 0", borderTop: "1px solid #E2E8EF" }}>
                          <Img src={avatarOf(name)} alt={name} style={{ width: "36px", height: "36px", borderRadius: "50%", objectFit: "cover", flex: "none", border: "1px solid #DBEAFE" }} />
                          <div style={{ flex: 1, minWidth: 0 }}><div style={{ fontSize: "14px", fontWeight: 500, color: "#172B3A" }}>{name}</div><div style={{ fontSize: "12.5px", color: "#5D6B78" }}>{type} · {dates}</div></div>
                          <span style={pill(STATUS[status][0], STATUS[status][1])}>{status}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </section>

        {/* VALUE */}
        <section id="solutions" style={{ padding: "clamp(56px,7vw,96px) 0", borderTop: "1px solid #E2E8EF" }}>
          <div style={{ ...wrap, display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(min(100%,360px),1fr))", gap: "clamp(32px,5vw,72px)", alignItems: "center" }}>
            <div>
              <p style={eyebrow}>Why Krewoxa</p>
              <h2 style={{ ...h2, marginBottom: "20px" }}>Less chasing. More clarity about your people.</h2>
              <div className="k-card" style={{ background: "radial-gradient(circle at 50% 50%,#DBEAFE 0%,#EFF6FF 48%,#fff 100%)", border: "1px solid #BFDBFE", borderRadius: "18px", padding: "22px 20px 18px", marginTop: "24px", boxShadow: "0 16px 36px -22px rgba(29,78,216,.25)" }}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "8px", padding: "0 4px" }}>
                  <span style={{ fontSize: "11.5px", fontWeight: 600, letterSpacing: ".05em", textTransform: "uppercase", color: "#1D4ED8", display: "inline-flex", alignItems: "center", gap: "6px" }}>
                    <span className="k-pulse" style={{ width: "7px", height: "7px", borderRadius: "50%", background: "#2563EB" }}></span>
                    Live workflow sync
                  </span>
                  <span style={{ fontSize: "11.5px", color: "#5D6B78" }}>Real-time data flow</span>
                </div>
                <HubDiagram />
              </div>
            </div>
            <div style={{ display: "flex", flexDirection: "column" }}>
              {values.map(([n, t, d]) => (
                <div key={n} style={{ display: "grid", gridTemplateColumns: "48px 1fr", gap: "16px", padding: "24px 0", borderTop: "1px solid #E2E8EF" }}>
                  <span style={{ width: "36px", height: "36px", borderRadius: "10px", background: "#EFF6FF", border: "1px solid #DBEAFE", display: "flex", alignItems: "center", justifyContent: "center", fontSize: "14px", fontWeight: 700, color: "#2563EB" }}>{n}</span>
                  <div><h3 style={{ margin: "0 0 6px", fontSize: "1.3rem", letterSpacing: "-.015em", color: "#102A43" }}>{t}</h3><p style={{ margin: 0, color: "#5D6B78" }}>{d}</p></div>
                </div>
              ))}
            </div>
          </div>
        </section>

        {/* FEATURES */}
        <section id="features" style={{ background: "#F7F9FB", padding: "clamp(56px,7vw,104px) 0", borderTop: "1px solid #E2E8EF" }}>
          <div style={wrap}>
            <div style={{ maxWidth: "720px", marginBottom: "clamp(40px,5vw,72px)" }}>
              <p style={eyebrow}>Features</p>
              <h2 style={h2}>Everyday HR workflows, in the same workspace.</h2>
            </div>

            {/* employees */}
            <div style={storyGrid}>
              <div>
                <p style={kicker}>Employee records</p>
                <h3 style={h3Story}>One place for every employee profile.</h3>
                <p style={storyP}>Keep job details, departments, reporting lines and contact information organized, so HR and managers always look at the same record.</p>
                <a href="#demo" style={{ fontWeight: 600 }}>See employee records in a demo →</a>
              </div>
              <div role="img" aria-label="Illustrative employee directory with sample data" className="k-card" style={mockCard}>
                <div className="k-img-zoom" style={{ height: "110px", marginBottom: "16px", position: "relative", border: "1px solid #DBEAFE" }}>
                  <Img src={IMG("team")} alt="Team members working together" />
                  <div style={{ position: "absolute", inset: 0, background: "linear-gradient(90deg,rgba(16,42,67,.75) 0%,rgba(16,42,67,.2) 100%)", display: "flex", alignItems: "center", padding: "0 18px", color: "#fff" }}>
                    <div>
                      <div style={{ fontSize: "12px", textTransform: "uppercase", letterSpacing: ".05em", color: "#93C5FD", fontWeight: 600 }}>Organization Directory</div>
                      <div style={{ fontSize: "16px", fontWeight: 700 }}>48 Active Team Members</div>
                    </div>
                  </div>
                </div>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: "8px", marginBottom: "12px" }}><strong style={{ color: "#102A43" }}>Employees</strong><span style={{ fontSize: "13px", padding: "5px 12px", border: "1px solid #E2E8EF", borderRadius: "8px", color: "#5D6B78" }}>Search by name…</span></div>
                {people.map(([name, role, dept], i) => (
                  <div key={name} style={{ display: "grid", gridTemplateColumns: "38px minmax(0,1.4fr) minmax(0,1fr)", gap: "12px", alignItems: "center", padding: "11px 0", borderTop: "1px solid #E2E8EF" }}>
                    <Img src={avatarOf(name)} alt={name} style={{ width: "38px", height: "38px", borderRadius: "50%", objectFit: "cover", border: "1px solid #DBEAFE" }} />
                    <div style={{ minWidth: 0 }}><div style={{ fontSize: "14.5px", fontWeight: 500 }}>{name}</div><div style={{ fontSize: "12.5px", color: "#5D6B78" }}>{role}</div></div>
                    <div style={{ fontSize: "13px", color: "#1D4ED8", fontWeight: 500 }}>{dept}</div>
                  </div>
                ))}
              </div>
            </div>

            {/* attendance */}
            <div style={storyGrid}>
              <div role="img" aria-label="Illustrative daily attendance list with sample data" className="k-card" style={{ ...mockCard, order: 2 }}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "12px" }}>
                  <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                    <span className="k-pulse" style={{ width: "9px", height: "9px", borderRadius: "50%", background: "#2563EB" }}></span>
                    <strong style={{ color: "#102A43" }}>Today&apos;s attendance</strong>
                  </div>
                  <span style={{ fontSize: "12.5px", color: "#1D4ED8", background: "#EFF6FF", padding: "3px 10px", borderRadius: "99px", fontWeight: 600 }}>85% Present</span>
                </div>
                {attendance.map(([name, time, status]) => (
                  <div key={name} style={{ display: "grid", gridTemplateColumns: "minmax(0,1.3fr) minmax(0,1fr) auto", gap: "12px", alignItems: "center", padding: "11px 0", borderTop: "1px solid #E2E8EF" }}>
                    <span style={{ fontSize: "14.5px", fontWeight: 500 }}>{name}</span>
                    <span style={{ fontSize: "13px", color: "#5D6B78" }}>{time}</span>
                    <span style={pill(STATUS[status][0], STATUS[status][1])}>{status}</span>
                  </div>
                ))}
              </div>
              <div style={{ order: 1 }}>
                <p style={kicker}>Attendance</p>
                <h3 style={h3Story}>See who&apos;s in, who&apos;s out, and who needs follow-up.</h3>
                <p style={storyP}>Track work time and review daily attendance without gathering updates from spreadsheets and messages.</p>
                <a href="#demo" style={{ fontWeight: 600 }}>See attendance in a demo →</a>
              </div>
            </div>

            {/* leave */}
            <div style={storyGrid}>
              <div>
                <p style={kicker}>Leave management</p>
                <h3 style={h3Story}>Requests and approvals that don&apos;t get lost.</h3>
                <p style={storyP}>Employees raise requests, managers review them, and HR keeps a clear record of the outcome. Try clicking Approve or Decline on the sample card.</p>
                <a href="#demo" style={{ fontWeight: 600 }}>See leave workflows in a demo →</a>
              </div>
              <div role="img" aria-label="Illustrative leave approval card with sample data" className="k-card" style={{ ...mockCard, padding: "22px" }}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: "8px" }}>
                  <strong style={{ color: "#102A43" }}>Leave request</strong>
                  <span style={pill(decBg, decColor)}>{leaveDecision}</span>
                </div>
                <div style={{ display: "flex", gap: "14px", alignItems: "center", margin: "18px 0" }}>
                  <Img src={avatar(0)} alt="Anjali Menon" style={{ width: "46px", height: "46px", borderRadius: "50%", objectFit: "cover", border: "2px solid #DBEAFE" }} />
                  <div><div style={{ fontWeight: 600 }}>Anjali Menon</div><div style={{ fontSize: "13px", color: "#5D6B78" }}>Design · Reports to R. Nair</div></div>
                </div>
                <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(110px,1fr))", gap: "12px", padding: "14px", background: "#F7F9FB", borderRadius: "12px", fontSize: "14px" }}>
                  <div><div style={{ color: "#5D6B78", fontSize: "12.5px" }}>Type</div>Casual leave</div>
                  <div><div style={{ color: "#5D6B78", fontSize: "12.5px" }}>Dates</div>12–14 Nov</div>
                  <div><div style={{ color: "#5D6B78", fontSize: "12.5px" }}>Days</div>3</div>
                </div>
                <div style={{ display: "flex", gap: "10px", marginTop: "18px" }}>
                  <button type="button" onClick={() => setLeaveDecision("Approved")} className="kx-hover-5" style={{ flex: 1, textAlign: "center", padding: "11px", border: 0, borderRadius: "10px", background: "#1D4ED8", color: "#fff", font: "inherit", fontWeight: 600, fontSize: "14px", cursor: "pointer", transition: "background .2s" }}>Approve</button>
                  <button type="button" onClick={() => setLeaveDecision("Declined")} className="kx-hover-3" style={{ flex: 1, textAlign: "center", padding: "11px", borderRadius: "10px", border: "1px solid #C9D4DF", background: "#fff", color: "#102A43", font: "inherit", fontWeight: 600, fontSize: "14px", cursor: "pointer", transition: "border-color .2s" }}>Decline</button>
                </div>
              </div>
            </div>

            {/* payroll */}
            <div style={{ ...storyGrid, marginBottom: "clamp(48px,6vw,80px)" }}>
              <div role="img" aria-label="Illustrative payroll workflow checklist with sample data" className="k-card" style={{ ...mockCard, order: 2, padding: "22px" }}>
                <div style={{ display: "flex", justifyContent: "space-between", marginBottom: "10px" }}><strong style={{ color: "#102A43" }}>Monthly payroll review</strong><span style={{ fontSize: "13px", color: "#5D6B78" }}>Sample data</span></div>
                {payroll.map(([label, state, p]) => (
                  <div key={label} style={{ display: "flex", alignItems: "center", gap: "12px", padding: "12px 0", borderTop: "1px solid #E2E8EF" }}>
                    <span style={{ width: "22px", height: "22px", borderRadius: "50%", flex: "none", display: "flex", alignItems: "center", justifyContent: "center", fontSize: "12px", fontWeight: 700, background: p === 2 ? "#2563EB" : "#fff", color: p === 2 ? "#fff" : "#1D4ED8", border: p === 2 ? "0" : `2px solid ${p ? "#1D4ED8" : "#C9D4DF"}` }}>{p === 2 ? "✓" : p === 1 ? "•" : ""}</span>
                    <span style={{ flex: 1, fontSize: "14.5px" }}>{label}</span>
                    <span style={{ fontSize: "13px", color: "#5D6B78" }}>{state}</span>
                  </div>
                ))}
              </div>
              <div style={{ order: 1 }}>
                <p style={kicker}>Payroll workflows</p>
                <h3 style={h3Story}>Bring payroll-related steps into view.</h3>
                <p style={storyP}>Connect attendance and leave information to payroll preparation so reviewers can follow what&apos;s ready and what&apos;s pending. <em style={{ fontStyle: "normal", fontSize: "14px" }}>Scope to be confirmed with the team.</em></p>
                <a href="#demo" style={{ fontWeight: 600 }}>Ask about payroll in a demo →</a>
              </div>
            </div>

            {/* secondary modules */}
            <div style={{ borderTop: "1px solid #C9D4DF", paddingTop: "36px", display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(min(100%,280px),1fr))", gap: "24px" }}>
              {modules.map(([t, d, img]) => (
                <div key={t} className="k-card" style={{ background: "#fff", border: "1px solid #E2E8EF", borderRadius: "16px", padding: "18px", display: "flex", flexDirection: "column", gap: "12px" }}>
                  <div className="k-img-zoom" style={{ height: "140px", border: "1px solid #EFF6FF" }}>
                    <Img src={img} alt={t} />
                  </div>
                  <div>
                    <h3 style={{ margin: "0 0 6px", fontSize: "1.1rem", color: "#102A43" }}>{t}</h3>
                    <p style={{ margin: 0, color: "#5D6B78", fontSize: "15px" }}>{d}</p>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </section>

        {/* HOW */}
        <section id="how" style={{ padding: "clamp(56px,7vw,104px) 0" }}>
          <div style={wrap}>
            <div style={{ maxWidth: "720px", marginBottom: "clamp(36px,5vw,64px)" }}>
              <p style={eyebrow}>How it works</p>
              <h2 style={h2}>From scattered records to one workspace, in three steps.</h2>
            </div>
            <ol style={{ listStyle: "none", margin: 0, padding: 0, display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(min(100%,300px),1fr))", gap: 0 }}>
              {steps.map(([n, t, d]) => (
                <li key={n} style={{ padding: "0 32px 8px 0", position: "relative" }}>
                  <div style={{ display: "flex", alignItems: "center", marginBottom: "22px" }}><span style={{ width: "44px", height: "44px", borderRadius: "50%", background: "#102A43", color: "#fff", fontWeight: 600, display: "flex", alignItems: "center", justifyContent: "center", flex: "none" }}>{n}</span><span style={{ flex: 1, height: "2px", background: "#DBEAFE" }}></span></div>
                  <h3 style={{ margin: "0 0 8px", fontSize: "1.35rem", letterSpacing: "-.015em", color: "#102A43" }}>{t}</h3>
                  <p style={{ margin: 0, color: "#5D6B78" }}>{d}</p>
                </li>
              ))}
            </ol>
          </div>
        </section>

        {/* PRODUCT PREVIEW */}
        <section style={{ background: "#102A43", padding: "clamp(56px,7vw,104px) 0", color: "#fff" }}>
          <div style={wrap}>
            <div style={{ maxWidth: "720px", marginBottom: "clamp(32px,4vw,56px)" }}>
              <p style={{ ...eyebrow, color: "#93C5FD" }}>Product preview</p>
              <h2 style={{ ...h2, color: "#fff", marginBottom: "14px" }}>A workspace your whole HR team can read at a glance.</h2>
              <p style={{ margin: 0, color: "#C5D3E0", fontSize: "1.1rem" }}>Illustrative mockup with sample data. Not a verified screenshot of the live application.</p>
            </div>
            <div role="img" aria-label="Illustrative Krewoxa workforce overview with department headcount, monthly attendance trend and pending actions, using sample data" style={{ background: "#F7F9FB", color: "#172B3A", borderRadius: "20px", padding: "clamp(16px,2.4vw,28px)", display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(min(100%,320px),1fr))", gap: "14px" }}>
              <div style={{ background: "#fff", border: "1px solid #E2E8EF", borderRadius: "14px", padding: "20px", minWidth: 0 }}>
                <strong style={{ color: "#102A43" }}>Headcount by department</strong>
                <div style={{ display: "flex", flexDirection: "column", gap: "14px", marginTop: "18px" }}>
                  {depts.map(([name, n]) => (
                    <div key={name}><div style={{ display: "flex", justifyContent: "space-between", fontSize: "14px", marginBottom: "5px" }}><span>{name}</span><span style={{ color: "#5D6B78" }}>{n}</span></div><div style={{ height: "8px", borderRadius: "4px", background: "#E2E8EF" }}><div style={{ height: "8px", borderRadius: "4px", background: "#2563EB", width: `${(n / 14) * 100}%` }}></div></div></div>
                  ))}
                </div>
              </div>
              <div style={{ background: "#fff", border: "1px solid #E2E8EF", borderRadius: "14px", padding: "20px", minWidth: 0 }}>
                <div style={{ display: "flex", justifyContent: "space-between" }}><strong style={{ color: "#102A43" }}>Attendance, last 6 months</strong><span style={{ fontSize: "13px", color: "#5D6B78" }}>% present</span></div>
                <div style={{ display: "flex", alignItems: "flex-end", gap: "12px", height: "180px", marginTop: "18px", borderBottom: "1px solid #E2E8EF" }}>
                  {months.map(([m, v]) => (
                    <div key={m} style={{ flex: 1, display: "flex", flexDirection: "column", justifyContent: "flex-end", alignItems: "center", height: "100%", gap: "4px" }}><span style={{ fontSize: "12px", color: "#5D6B78" }}>{v}%</span><div style={{ width: "100%", borderRadius: "6px 6px 0 0", background: "#1D4ED8", height: `${(v - 80) * 9}%` }}></div></div>
                  ))}
                </div>
                <div style={{ display: "flex", gap: "12px", marginTop: "8px" }}>{months.map(([m]) => (<span key={m} style={{ flex: 1, textAlign: "center", fontSize: "12px", color: "#5D6B78" }}>{m}</span>))}</div>
              </div>
              <div style={{ background: "#fff", border: "1px solid #E2E8EF", borderRadius: "14px", padding: "20px", minWidth: 0 }}>
                <strong style={{ color: "#102A43" }}>Needs your attention</strong>
                {actions.map(([t, d]) => (
                  <div key={t} style={{ display: "flex", gap: "12px", alignItems: "flex-start", padding: "12px 0", borderTop: "1px solid #E2E8EF" }}>
                    <span style={{ marginTop: "7px", width: "8px", height: "8px", borderRadius: "50%", background: "#2563EB", flex: "none" }}></span>
                    <div><div style={{ fontSize: "14.5px", fontWeight: 500 }}>{t}</div><div style={{ fontSize: "13px", color: "#5D6B78" }}>{d}</div></div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </section>

        {/* TRUST */}
        <section style={{ padding: "clamp(56px,7vw,104px) 0" }}>
          <div style={{ ...wrap, display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(min(100%,360px),1fr))", gap: "clamp(32px,5vw,72px)" }}>
            <div>
              <p style={eyebrow}>Trust and security</p>
              <h2 style={{ ...h2, marginBottom: "16px" }}>Employee data deserves careful handling.</h2>
              <p style={{ margin: 0, color: "#5D6B78", maxWidth: "480px" }}>HR records are sensitive. We&apos;ll walk you through how access, permissions and data handling work in Krewoxa, and answer security questions directly during your demo.</p>
            </div>
            <div style={{ display: "flex", flexDirection: "column" }}>
              {trust.map(([t, d]) => (
                <div key={t} style={{ padding: "20px 0", borderTop: "1px solid #E2E8EF", display: "grid", gridTemplateColumns: "28px 1fr", gap: "14px" }}>
                  <span style={{ color: "#2563EB", fontWeight: 700 }} aria-hidden="true">✓</span>
                  <div><h3 style={{ margin: "0 0 4px", fontSize: "1.1rem", color: "#102A43" }}>{t}</h3><p style={{ margin: 0, color: "#5D6B78", fontSize: "15px" }}>{d}</p></div>
                </div>
              ))}
              <p style={{ margin: 0, paddingTop: "16px", borderTop: "1px solid #E2E8EF", fontSize: "14px", color: "#5D6B78" }}>Specific capabilities are confirmed before publishing. No certifications or compliance claims are made on this page.</p>
            </div>
          </div>
        </section>

        {/* DEMO */}
        <section id="demo" style={{ background: "#EFF6FF", padding: "clamp(56px,7vw,104px) 0", borderTop: "1px solid #DBEAFE", borderBottom: "1px solid #DBEAFE" }}>
          <div style={{ ...wrap, display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(min(100%,380px),1fr))", gap: "clamp(32px,5vw,80px)", alignItems: "center" }}>
            <div>
              <h2 style={{ ...h2, fontSize: "clamp(2rem,3.4vw,3.3rem)", lineHeight: 1.1, marginBottom: "16px" }}>Ready to bring your HR workflows together?</h2>
              <p style={{ margin: "0 0 20px", color: "#5D6B78", fontSize: "1.1rem", maxWidth: "480px" }}>Tell us a little about your team and we&apos;ll show you whether Krewoxa fits how you work. No pressure, no obligation.</p>
              <p style={{ margin: 0, fontSize: "14px", color: "#5D6B78" }}>Prefer email? Contact details will appear here once confirmed.</p>
            </div>
            <div style={{ background: "#fff", border: "1px solid #E2E8EF", borderRadius: "18px", padding: "clamp(20px,3vw,32px)", boxShadow: "0 18px 40px -28px rgba(16,42,67,.3)" }}>
              {sent ? (
                <div role="status" style={{ padding: "12px 0" }}>
                  <div style={{ width: "44px", height: "44px", borderRadius: "50%", background: "#DBEAFE", color: "#1D4ED8", display: "flex", alignItems: "center", justifyContent: "center", fontWeight: 700, fontSize: "20px" }}>✓</div>
                  <h3 style={{ margin: "16px 0 8px", fontSize: "1.4rem", color: "#102A43" }}>Thanks, {form.name}.</h3>
                  <p style={{ margin: 0, color: "#5D6B78" }}>Form preview only. This form isn&apos;t connected to a backend yet, so nothing was sent.</p>
                </div>
              ) : (
                <form onSubmit={submit} noValidate style={{ display: "flex", flexDirection: "column", gap: "18px" }}>
                  <div>
                    <label htmlFor="f-name" style={labelStyle}>Full name <span style={{ color: "#B42332" }}>*</span></label>
                    <input id="f-name" name="name" value={form.name} onChange={(e: ChangeEvent<HTMLInputElement>) => setForm((f) => ({ ...f, name: e.target.value }))} autoComplete="name" aria-describedby="e-name" aria-invalid={!!errors.name} className="kx-focus-4" style={inputStyle} />
                    <div id="e-name" style={{ color: "#B42332", fontSize: "13.5px", marginTop: "4px" }}>{errors.name}</div>
                  </div>
                  <div>
                    <label htmlFor="f-email" style={labelStyle}>Work email <span style={{ color: "#B42332" }}>*</span></label>
                    <input id="f-email" name="email" type="email" value={form.email} onChange={(e: ChangeEvent<HTMLInputElement>) => setForm((f) => ({ ...f, email: e.target.value }))} autoComplete="email" aria-describedby="e-email" aria-invalid={!!errors.email} className="kx-focus-4" style={inputStyle} />
                    <div id="e-email" style={{ color: "#B42332", fontSize: "13.5px", marginTop: "4px" }}>{errors.email}</div>
                  </div>
                  <div>
                    <label htmlFor="f-size" style={labelStyle}>Team size <span style={{ fontWeight: 450, color: "#5D6B78" }}>(optional)</span></label>
                    <select id="f-size" style={{ ...inputStyle, padding: "0 12px", background: "#fff" }}><option>1–25 employees</option><option>26–100 employees</option><option>101–500 employees</option><option>500+ employees</option></select>
                  </div>
                  <button type="submit" className="kx-hover-5" style={{ height: "52px", border: 0, borderRadius: "10px", background: "#1D4ED8", color: "#fff", font: "inherit", fontWeight: 600, cursor: "pointer", transition: "background .2s" }}>Book a demo</button>
                </form>
              )}
            </div>
          </div>
        </section>

        {/* FAQ */}
        <section id="faq" style={{ padding: "clamp(56px,7vw,104px) 0" }}>
          <div style={{ ...wrap, display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(min(100%,340px),1fr))", gap: "clamp(32px,5vw,72px)" }}>
            <div>
              <p style={eyebrow}>FAQ</p>
              <h2 style={h2}>Common questions</h2>
            </div>
            <div style={{ borderBottom: "1px solid #E2E8EF" }}>
              {FAQS.map(([q, a], i) => {
                const open = openFaq === i;
                return (
                  <Fragment key={q}>
                    <div style={{ borderTop: "1px solid #E2E8EF" }}>
                      <h3 style={{ margin: 0 }}><button onClick={() => setOpenFaq(open ? -1 : i)} aria-expanded={open} style={{ width: "100%", display: "flex", justifyContent: "space-between", alignItems: "center", gap: "16px", textAlign: "left", padding: "20px 0", minHeight: "44px", background: "none", border: 0, font: "inherit", fontSize: "1.1rem", fontWeight: 600, color: "#102A43", cursor: "pointer" }}>{q}<span aria-hidden="true" style={{ fontSize: "22px", color: "#1D4ED8", flex: "none" }}>{open ? "−" : "+"}</span></button></h3>
                      {open && <p style={{ margin: "0 0 20px", color: "#5D6B78", maxWidth: "600px" }}>{a}</p>}
                    </div>
                  </Fragment>
                );
              })}
            </div>
          </div>
        </section>

        {/* FINAL CTA */}
        <section style={{ padding: "0 0 clamp(56px,7vw,96px)" }}>
          <div style={wrap}>
            <div style={{ background: "#102A43", borderRadius: "20px", padding: "clamp(32px,5vw,64px)", display: "flex", flexWrap: "wrap", gap: "24px", alignItems: "center", justifyContent: "space-between", color: "#fff" }}>
              <div style={{ maxWidth: "620px" }}><h2 style={{ margin: "0 0 10px", fontSize: "clamp(1.7rem,2.8vw,2.5rem)", lineHeight: 1.15, letterSpacing: "-.025em" }}>Give your HR team one clear place to work.</h2><p style={{ margin: 0, color: "#C5D3E0" }}>See Krewoxa with your own workflows in mind.</p></div>
              <a href="#demo" className="kx-hover-6" style={{ display: "inline-flex", alignItems: "center", height: "52px", padding: "0 28px", borderRadius: "10px", background: "#fff", color: "#102A43", fontWeight: 600 }}>Book a demo</a>
            </div>
          </div>
        </section>
      </main>

      <footer style={{ background: "#F7F9FB", borderTop: "1px solid #E2E8EF", padding: "clamp(40px,5vw,64px) 0 28px" }}>
        <div style={wrap}>
          <div style={{ display: "flex", flexWrap: "wrap", justifyContent: "space-between", gap: "32px" }}>
            <div style={{ maxWidth: "340px" }}><div style={{ fontSize: "24px", fontWeight: 700, letterSpacing: "-.03em", color: "#102A43" }}>Krewoxa<span style={{ color: "#2563EB" }}>.</span></div><p style={{ margin: "10px 0 0", color: "#5D6B78", fontSize: "15px" }}>HR management for growing teams. Employee information and everyday workflows in one place.</p></div>
            <nav aria-label="Footer" style={{ display: "flex", flexWrap: "wrap", gap: "12px 32px", alignSelf: "flex-start" }}>
              <a href="#features" style={{ color: "#172B3A", fontWeight: 500 }}>Features</a><a href="#solutions" style={{ color: "#172B3A", fontWeight: 500 }}>Solutions</a><a href="#how" style={{ color: "#172B3A", fontWeight: 500 }}>How it works</a><a href="#faq" style={{ color: "#172B3A", fontWeight: 500 }}>FAQ</a><a href="#demo" style={{ color: "#172B3A", fontWeight: 500 }}>Book a demo</a><Link href="/login" style={{ color: "#172B3A", fontWeight: 500 }}>Log in</Link><Link href="/register" style={{ color: "#172B3A", fontWeight: 500 }}>Register</Link>
            </nav>
          </div>
          <div style={{ marginTop: "36px", paddingTop: "20px", borderTop: "1px solid #E2E8EF", display: "flex", flexWrap: "wrap", justifyContent: "space-between", gap: "8px", fontSize: "14px", color: "#5D6B78" }}>
            <span>© 2026 Krewoxa. Legal entity name to be confirmed.</span><span>Privacy policy and terms: links to be added once published.</span>
          </div>
        </div>
      </footer>
    </div>
  );
}

/** Animated "HR hub" diagram: four modules feeding the central Krewoxa node. */
function HubDiagram() {
  const nodes: { cls: string; x: number; y: number; title: string; sub: string; subColor: string; dotX: number; dotY: number; icon: ReactNode }[] = [
    { cls: "k-node-1", x: 10, y: 20, title: "Profiles", sub: "48 synced", subColor: "#5D6B78", dotX: 118, dotY: 46, icon: (<><circle cx="30" cy="43" r="3.5" fill="#2563EB" /><path d="M24 52 C24 48.5, 36 48.5, 36 52" stroke="#2563EB" strokeWidth="1.8" strokeLinecap="round" fill="none" /></>) },
    { cls: "k-node-2", x: 10, y: 132, title: "Attendance", sub: "Live check-in", subColor: "#2563EB", dotX: 118, dotY: 158, icon: (<><circle cx="30" cy="158" r="6" stroke="#2563EB" strokeWidth="1.6" fill="none" /><path d="M30 154.5 V158 L32.5 159.5" stroke="#2563EB" strokeWidth="1.6" strokeLinecap="round" fill="none" /></>) },
    { cls: "k-node-3", x: 320, y: 20, title: "Leave", sub: "Auto-routed", subColor: "#5D6B78", dotX: 322, dotY: 46, icon: (<><rect x="334.5" y="41" width="11" height="10" rx="2" stroke="#2563EB" strokeWidth="1.6" fill="none" /><path d="M337 39.5 V42 M343 39.5 V42" stroke="#2563EB" strokeWidth="1.6" strokeLinecap="round" /></>) },
    { cls: "k-node-4", x: 320, y: 132, title: "Payroll Prep", sub: "Ready to run", subColor: "#2563EB", dotX: 322, dotY: 158, icon: (<path d="M336 158.5 L339 161.5 L344.5 155.5" stroke="#2563EB" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" fill="none" />) },
  ];
  const paths = [
    { id: "kPathTL", d: "M118 46 C168 46, 174 102, 220 102", grad: "kLineGradL", cls: "k-flow-line", dur: "2.4s", begin: "0s", pts: "0;1", fill: "#2563EB" },
    { id: "kPathBL", d: "M118 158 C168 158, 174 102, 220 102", grad: "kLineGradL", cls: "k-flow-line", dur: "2.7s", begin: "0.6s", pts: "0;1", fill: "#2563EB" },
    { id: "kPathTR", d: "M322 46 C272 46, 266 102, 220 102", grad: "kLineGradR", cls: "k-flow-line", dur: "2.5s", begin: "1.1s", pts: "0;1", fill: "#2563EB" },
    { id: "kPathBR", d: "M322 158 C272 158, 266 102, 220 102", grad: "kLineGradR", cls: "k-flow-line-rev", dur: "2.6s", begin: "0.3s", pts: "1;0", fill: "#1D4ED8" },
  ];
  return (
    <svg viewBox="0 0 440 204" style={{ width: "100%", height: "auto", display: "block", overflow: "visible" }} role="img" aria-label="Animated diagram connecting Profiles, Attendance, Leave, and Payroll Prep into the central Krewoxa HR Hub">
      <defs>
        <linearGradient id="kHubGrad" x1="0" y1="0" x2="1" y2="1"><stop offset="0%" stopColor="#3B82F6" /><stop offset="55%" stopColor="#2563EB" /><stop offset="100%" stopColor="#1E3A8A" /></linearGradient>
        <linearGradient id="kLineGradL" x1="0" y1="0" x2="1" y2="0"><stop offset="0%" stopColor="#93C5FD" /><stop offset="100%" stopColor="#2563EB" /></linearGradient>
        <linearGradient id="kLineGradR" x1="1" y1="0" x2="0" y2="0"><stop offset="0%" stopColor="#93C5FD" /><stop offset="100%" stopColor="#2563EB" /></linearGradient>
        <filter id="kPacketGlow" x="-60%" y="-60%" width="220%" height="220%"><feDropShadow dx="0" dy="0" stdDeviation="3" floodColor="#2563EB" floodOpacity="0.75" /></filter>
        <filter id="kCardShadow" x="-15%" y="-15%" width="130%" height="140%"><feDropShadow dx="0" dy="6" stdDeviation="6" floodColor="#102A43" floodOpacity="0.08" /></filter>
      </defs>
      <circle cx="220" cy="102" r="82" fill="none" stroke="#DBEAFE" strokeWidth="1" strokeDasharray="3 5" />
      <circle cx="220" cy="102" r="60" fill="none" stroke="#DBEAFE" strokeWidth="1" />
      {paths.map((p) => (<path key={p.id} id={p.id} d={p.d} stroke="#DBEAFE" strokeWidth="3" fill="none" strokeLinecap="round" />))}
      {paths.map((p) => (<path key={`f-${p.id}`} className={p.cls} d={p.d} stroke={`url(#${p.grad})`} strokeWidth="2.2" fill="none" strokeLinecap="round" />))}
      {paths.map((p) => (
        <circle key={`c-${p.id}`} r="4" fill={p.fill} filter="url(#kPacketGlow)">
          <animateMotion dur={p.dur} begin={p.begin} repeatCount="indefinite" keyPoints={p.pts} keyTimes="0;1" calcMode="spline" keySplines="0.4 0 0.2 1"><mpath href={`#${p.id}`} /></animateMotion>
        </circle>
      ))}
      {nodes.map((n) => {
        const cy = n.y + 26;
        const tx = n.x + 37;
        return (
          <g key={n.title} className={n.cls} filter="url(#kCardShadow)">
            <rect className="k-node-box" x={n.x} y={n.y} width="110" height="52" rx="12" fill="#fff" stroke="#BFDBFE" strokeWidth="1.5" />
            <circle cx={n.x + 20} cy={cy} r="11" fill="#EFF6FF" />
            {n.icon}
            <text x={tx} y={cy - 3} fontSize="12" fontWeight="700" fill="#102A43">{n.title}</text>
            <text x={tx} y={cy + 10} fontSize="9.5" fontWeight="500" fill={n.subColor}>{n.sub}</text>
            <circle cx={n.dotX} cy={n.dotY} r="4" fill="#3B82F6" stroke="#fff" strokeWidth="1.5" />
          </g>
        );
      })}
      <circle className="k-hub-ring" cx="220" cy="102" r="40" fill="none" stroke="#60A5FA" strokeWidth="2" />
      <circle className="k-hub-ring-2" cx="220" cy="102" r="40" fill="none" stroke="#93C5FD" strokeWidth="1.5" />
      <circle cx="220" cy="102" r="45" fill="#DBEAFE" opacity="0.7" />
      <circle cx="220" cy="102" r="37" fill="url(#kHubGrad)" filter="url(#kCardShadow)" />
      <circle cx="220" cy="102" r="33" fill="none" stroke="rgba(255,255,255,0.25)" strokeWidth="1" />
      <text x="220" y="99" textAnchor="middle" fontSize="12.5" fontWeight="700" fill="#fff" letterSpacing="-0.02em">Krewoxa</text>
      <text x="220" y="113" textAnchor="middle" fontSize="9.5" fontWeight="600" fill="#BFDBFE" letterSpacing="0.04em">HR HUB</text>
    </svg>
  );
}
