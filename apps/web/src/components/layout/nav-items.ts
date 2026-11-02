import {
  AlarmClock,
  Banknote,
  Briefcase,
  Building,
  Building2,
  CalendarCheck,
  CalendarClock,
  CalendarDays,
  CalendarHeart,
  CalendarOff,
  CalendarRange,
  ClipboardCheck,
  ClipboardEdit,
  ClipboardList,
  Clock,
  Coins,
  FileClock,
  FileText,
  GitMerge,
  Landmark,
  Layers,
  LayoutDashboard,
  LayoutList,
  Link2,
  ListChecks,
  Lock,
  MapPin,
  Network,
  Palmtree,
  Scale,
  Search,
  Settings,
  Tag,
  Timer,
  UserCircle,
  UserCog,
  UserPlus,
  Users,
  Wallet,
  type LucideIcon,
} from "lucide-react";

export interface NavItem {
  href: string;
  label: string;
  icon: LucideIcon;
  /** Only shown when true — currently just "does this user have a linked Employee record"
   * (`My Profile`, doc 41 Phase 4). Every other item is unconditional, matching this list's own
   * long-standing convention (docs/design/03_Navigation_System.md §5 — items the role/build
   * can't access yet are absent, not disabled) rather than per-permission filtering, which this
   * one item doesn't fit: it's gated on data (an Employee link), not a permission code. */
  requiresEmployeeId?: boolean;
  /** Highlight this item for every path under this prefix, when it differs from `href` (the landing view). */
  matchPrefix?: string;
}

export interface PrimaryNavGroup {
  label: string;
  items: NavItem[];
}

export const PRIMARY_NAV_GROUPS: PrimaryNavGroup[] = [
  {
    label: "Workspace",
    items: [
      { href: "/app/dashboard", label: "Dashboard", icon: LayoutDashboard },
      { href: "/app/me", label: "My Profile", icon: UserCircle, requiresEmployeeId: true },
      { href: "/app/me/calendar", label: "My Calendar", icon: CalendarDays, requiresEmployeeId: true },
      { href: "/app/me/payslips", label: "My Payslips", icon: FileText, requiresEmployeeId: true },
    ],
  },
  {
    label: "People",
    items: [
      { href: "/app/employees", label: "Employees", icon: Users },
      { href: "/app/onboarding", label: "Onboarding", icon: UserPlus },
    ],
  },
  {
    label: "Time & Attendance",
    items: [
      { href: "/app/attendance", label: "Attendance", icon: CalendarClock },
      { href: "/app/rosters/schedule", label: "Shift Rosters", icon: CalendarCheck, matchPrefix: "/app/rosters" },
      { href: "/app/regularizations", label: "Regularizations", icon: ClipboardEdit },
      { href: "/app/overtime", label: "Overtime", icon: AlarmClock },
    ],
  },
  {
    label: "Leave & Payroll",
    items: [
      { href: "/app/leave-applications", label: "Leave", icon: Palmtree },
      { href: "/app/leave-balances", label: "Leave Balances", icon: Wallet },
      { href: "/app/payroll/pay-runs", label: "Payroll", icon: Banknote },
    ],
  },
  {
    label: "Administration",
    items: [{ href: "/app/settings", label: "Settings", icon: Settings }],
  },
];

/** Flat sidebar for staff who only have a personal (employee) view — no admin groups. */
export const EMPLOYEE_NAV_ITEMS: NavItem[] = [
  { href: "/app/dashboard", label: "Dashboard", icon: LayoutDashboard },
  { href: "/app/attendance", label: "My Attendance", icon: Clock },
  { href: "/app/leave-applications", label: "Leave", icon: Palmtree },
  { href: "/app/leave-balances", label: "Leave Balances", icon: Wallet },
  { href: "/app/regularizations", label: "Corrections", icon: ClipboardEdit },
  { href: "/app/overtime", label: "Overtime", icon: AlarmClock },
  { href: "/app/me/calendar", label: "My Calendar", icon: CalendarDays },
  { href: "/app/me/payslips", label: "My Payslips", icon: Banknote },
  { href: "/app/me", label: "My Profile", icon: UserCircle },
];

/** Day-to-day items, kept directly in the sidebar. Configuration/admin screens live under
 * Settings (`SETTINGS_NAV_GROUPS` below) instead of crowding the primary nav. */
export const NAV_ITEMS: NavItem[] = PRIMARY_NAV_GROUPS.flatMap((group) => group.items);

export interface SettingsNavGroup {
  label: string;
  description?: string;
  items: NavItem[];
}

/** Configuration/admin screens, reachable via the Settings hub (`/app/settings`) rather than the
 * primary sidebar. Grouping mirrors the categories on that hub page. */
export const SETTINGS_NAV_GROUPS: SettingsNavGroup[] = [
  {
    label: "Organisation",
    description: "Company profile, legal entities, branches, departments, designations, and grades.",
    items: [
      { href: "/app/company", label: "Company Profile", icon: Building2 },
      { href: "/app/legal-entities", label: "Companies", icon: Landmark },
      { href: "/app/branches", label: "Branches", icon: Building },
      { href: "/app/departments", label: "Departments", icon: Network },
      { href: "/app/designations", label: "Designations", icon: Briefcase },
      { href: "/app/grades", label: "Grades", icon: Layers },
    ],
  },
  {
    label: "Attendance & Time",
    description: "Shift schedules, attendance periods, work calendars, holidays, and time policies.",
    items: [
      { href: "/app/shifts", label: "Shifts", icon: Clock },
      { href: "/app/attendance-periods", label: "Attendance Periods", icon: Lock },
      { href: "/app/work-calendars", label: "Work Calendars", icon: CalendarRange },
      { href: "/app/holiday-calendars", label: "Holiday Calendars", icon: CalendarDays },
      { href: "/app/weekly-off-patterns", label: "Weekly-Off Patterns", icon: CalendarOff },
      { href: "/app/attendance-policies", label: "Attendance Policies", icon: ClipboardList },
      { href: "/app/attendance-geofences", label: "Workplace Geofences", icon: MapPin },
      { href: "/app/overtime-policies", label: "Overtime Policies", icon: Timer },
      { href: "/app/regularization-policies", label: "Regularization Policies", icon: FileClock },
    ],
  },
  {
    label: "Leave",
    description: "Leave types, accrual policies, combination rules, leave year, and statutory minimums.",
    items: [
      { href: "/app/leave-types", label: "Leave Types", icon: Tag },
      { href: "/app/leave-policies", label: "Leave Policies", icon: ClipboardCheck },
      { href: "/app/leave-combination-rules", label: "Leave Combination Rules", icon: GitMerge },
      { href: "/app/leave-year-setting", label: "Leave Year", icon: CalendarHeart },
      { href: "/app/statutory-leave-minimums", label: "Statutory Minimums", icon: Scale },
    ],
  },
  {
    label: "Payroll",
    description: "Earnings and deduction components, salary structures, and statutory tax/PF/ESI rates.",
    items: [
      { href: "/app/payroll/salary-components", label: "Salary Components", icon: Coins },
      { href: "/app/payroll/salary-structures", label: "Salary Structures", icon: LayoutList },
      { href: "/app/payroll/statutory-rates", label: "Statutory Rates", icon: Landmark },
    ],
  },
  {
    label: "Policies",
    description: "Scope-based policy assignments and effective policy resolution inspector.",
    items: [
      { href: "/app/policy-assignments", label: "Policy Assignments", icon: Link2 },
      { href: "/app/policy-resolution", label: "Policy Resolution", icon: Search },
    ],
  },
  {
    label: "Administration",
    description: "Initial tenant setup checklist and user account access management.",
    items: [
      { href: "/app/setup", label: "Setup", icon: ListChecks },
      { href: "/app/users", label: "Users", icon: UserCog },
    ],
  },
];

export const SETTINGS_ITEMS: NavItem[] = SETTINGS_NAV_GROUPS.flatMap((group) => group.items);
