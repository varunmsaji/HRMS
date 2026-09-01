import {
  AlarmClock,
  Briefcase,
  Building,
  Building2,
  CalendarCheck,
  CalendarClock,
  CalendarDays,
  CalendarOff,
  CalendarRange,
  ClipboardEdit,
  ClipboardList,
  Clock,
  FileClock,
  Landmark,
  LayoutDashboard,
  Layers,
  Link2,
  ClipboardCheck,
  ListChecks,
  Lock,
  Network,
  Palmtree,
  Search,
  Tag,
  Timer,
  Users,
  Wallet,
  type LucideIcon,
} from "lucide-react";

export interface NavItem {
  href: string;
  label: string;
  icon: LucideIcon;
}

/** Navigation for screens that exist today (docs/design/03_Navigation_System.md §5 —
 * items the role/build can't access yet are absent, not disabled). */
export const NAV_ITEMS: NavItem[] = [
  { href: "/app/dashboard", label: "Dashboard", icon: LayoutDashboard },
  { href: "/app/company", label: "Company", icon: Building2 },
  { href: "/app/employees", label: "Employees", icon: Users },
  { href: "/app/legal-entities", label: "Legal Entities", icon: Landmark },
  { href: "/app/branches", label: "Branches", icon: Building },
  { href: "/app/departments", label: "Departments", icon: Network },
  { href: "/app/designations", label: "Designations", icon: Briefcase },
  { href: "/app/grades", label: "Grades", icon: Layers },
  { href: "/app/shifts", label: "Shifts", icon: Clock },
  { href: "/app/rosters", label: "Shift Rosters", icon: CalendarCheck },
  { href: "/app/attendance", label: "Attendance", icon: CalendarClock },
  { href: "/app/regularizations", label: "Regularizations", icon: ClipboardEdit },
  { href: "/app/overtime", label: "Overtime", icon: AlarmClock },
  { href: "/app/leave-applications", label: "Leave", icon: Palmtree },
  { href: "/app/leave-balances", label: "Leave Balances", icon: Wallet },
  { href: "/app/attendance-periods", label: "Attendance Periods", icon: Lock },
  { href: "/app/work-calendars", label: "Work Calendars", icon: CalendarRange },
  { href: "/app/holiday-calendars", label: "Holiday Calendars", icon: CalendarDays },
  { href: "/app/weekly-off-patterns", label: "Weekly-Off Patterns", icon: CalendarOff },
  { href: "/app/attendance-policies", label: "Attendance Policies", icon: ClipboardList },
  { href: "/app/overtime-policies", label: "Overtime Policies", icon: Timer },
  { href: "/app/regularization-policies", label: "Regularization Policies", icon: FileClock },
  { href: "/app/leave-types", label: "Leave Types", icon: Tag },
  { href: "/app/leave-policies", label: "Leave Policies", icon: ClipboardCheck },
  { href: "/app/policy-assignments", label: "Policy Assignments", icon: Link2 },
  { href: "/app/policy-resolution", label: "Policy Resolution", icon: Search },
  { href: "/app/setup", label: "Setup", icon: ListChecks },
];
