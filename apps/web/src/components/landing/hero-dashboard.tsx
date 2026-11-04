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
