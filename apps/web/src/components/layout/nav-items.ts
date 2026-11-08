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
  /** Rarely needed. The Settings hub tucks these behind "Show more" until searched for. */
  advanced?: boolean;
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

export type SettingsModuleSlug = "organisation" | "attendance" | "leave" | "payroll" | "access";

/** Kinds of policy whose company-wide setting a module summarises (mirrors
 * `lib/policy-assignment/types.ts` — kept as strings here so the nav has no API imports). */
export type SettingsPolicyKind =
  | "WORK_CALENDAR"
  | "WEEKLY_OFF"
  | "ATTENDANCE_POLICY"
  | "OVERTIME_POLICY"
  | "REGULARIZATION_POLICY"
  | "LEAVE_POLICY";

/** One area of Settings, e.g. Attendance, with everything it needs on one page. Sections are in
 * the order an admin sets them up. */
export interface SettingsModule {
  slug: SettingsModuleSlug;
  label: string;
  description: string;
  icon: LucideIcon;
  sections: SettingsNavGroup[];
  /** Codes from the setup checklist (`/companies/current/setup-checklist`) that belong here. */
  checklistCodes: string[];
  /** When set, the module page shows which of these policies the whole company follows, and
   * where to change who follows what. */
  followsKinds?: SettingsPolicyKind[];
  /** The section the "who follows which rules" step comes after; the end when unset. */
  followsAfter?: string;
}

export const SETTINGS_MODULES: SettingsModule[] = [
  {
    slug: "organisation",
    label: "Company & structure",
    description: "Your company, legal entities, offices, departments, job titles and grades.",
    icon: Building2,
    checklistCodes: ["BRANCH"],
    sections: [
      {
        label: "Company",
        description: "Your company, its legal entities and offices.",
        items: [
          { href: "/app/company", label: "Company Profile", icon: Building2 },
          { href: "/app/legal-entities", label: "Legal Entities", icon: Landmark },
          { href: "/app/branches", label: "Branches", icon: Building },
        ],
      },
      {
        label: "People structure",
        description: "Departments, job titles and pay levels.",
        items: [
          { href: "/app/departments", label: "Departments", icon: Network },
          { href: "/app/designations", label: "Designations", icon: Briefcase },
          { href: "/app/grades", label: "Grades", icon: Layers },
        ],
      },
    ],
  },
  {
    slug: "attendance",
    label: "Attendance",
    description:
      "Where and when people work, the rules that judge each day, who follows them, and closing the month.",
    icon: CalendarClock,
    checklistCodes: ["SHIFT", "WORK_CALENDAR", "ATTENDANCE_POLICY", "REGULARIZATION_POLICY", "OVERTIME_POLICY"],
    followsKinds: [
      "WORK_CALENDAR",
      "ATTENDANCE_POLICY",
      "OVERTIME_POLICY",
      "REGULARIZATION_POLICY",
      "WEEKLY_OFF",
    ],
    followsAfter: "Attendance rules",
    sections: [
      {
        label: "When people work",
        description: "Working hours, working days, holidays and weekly offs.",
        items: [
          { href: "/app/shifts", label: "Shifts", icon: Clock },
          { href: "/app/work-calendars", label: "Work Calendars", icon: CalendarRange },
          { href: "/app/holiday-calendars", label: "Holiday Calendars", icon: CalendarDays },
          { href: "/app/weekly-off-patterns", label: "Weekly-Off Patterns", icon: CalendarOff },
        ],
      },
      {
        label: "Where people punch",
        description: "Approved workplaces for location checks. Office addresses are under Branches.",
        items: [{ href: "/app/attendance-geofences", label: "Workplace Geofences", icon: MapPin }],
      },
      {
        label: "Attendance rules",
        description:
          "How punches, overtime and corrections are judged and approved. Open a policy to choose who follows it.",
        items: [
          { href: "/app/attendance-policies", label: "Attendance Policies", icon: ClipboardList },
          { href: "/app/overtime-policies", label: "Overtime Policies", icon: Timer },
          { href: "/app/regularization-policies", label: "Correction Policies", icon: FileClock },
        ],
      },
      {
        label: "Closing the month",
        description: "Lock a month once attendance is final, before payroll uses it.",
        items: [{ href: "/app/attendance-periods", label: "Attendance Periods", icon: Lock }],
      },
    ],
  },
  {
    slug: "leave",
    label: "Leave",
    description: "Leave types, the rules for earning and using them, and who follows which rules.",
    icon: Palmtree,
    checklistCodes: ["LEAVE_POLICY"],
    followsKinds: ["LEAVE_POLICY"],
    sections: [
      {
        label: "Leave types and rules",
        description: "Each leave type has its own policy. Open a policy to choose who follows it.",
        items: [
          { href: "/app/leave-types", label: "Leave Types", icon: Tag },
          { href: "/app/leave-policies", label: "Leave Policies", icon: ClipboardCheck },
          { href: "/app/leave-year-setting", label: "Leave Year", icon: CalendarHeart, advanced: true },
          {
            href: "/app/leave-combination-rules",
            label: "Leave Combination Rules",
            icon: GitMerge,
            advanced: true,
          },
          {
            href: "/app/statutory-leave-minimums",
            label: "Statutory Minimums",
            icon: Scale,
            advanced: true,
          },
        ],
      },
    ],
  },
  {
    slug: "payroll",
    label: "Payroll",
    description: "Earnings and deduction components, salary structures, and statutory tax/PF/ESI rates.",
    icon: Banknote,
    checklistCodes: [],
    sections: [
      {
        label: "Pay setup",
        items: [
          { href: "/app/payroll/salary-components", label: "Salary Components", icon: Coins },
          { href: "/app/payroll/salary-structures", label: "Salary Structures", icon: LayoutList },
          { href: "/app/payroll/statutory-rates", label: "Statutory Rates", icon: Landmark },
        ],
      },
    ],
  },
  {
    slug: "access",
    label: "Access & setup",
    description: "User accounts and roles, and the setup checklist.",
    icon: UserCog,
    checklistCodes: [],
    sections: [
      {
        label: "Access & setup",
        items: [
          { href: "/app/users", label: "Users", icon: UserCog },
          { href: "/app/setup", label: "Setup", icon: ListChecks },
        ],
      },
    ],
  },
];

/** Screens shared by several modules: each module with `followsKinds` links to them. */
export const SETTINGS_SHARED_GROUP: SettingsNavGroup = {
  label: "Who follows what",
  description: "Choose which rules each group follows, and check what applies to a person.",
  items: [
    { href: "/app/policy-assignments", label: "Rules by Group", icon: Link2 },
    { href: "/app/policy-resolution", label: "Check a Person's Rules", icon: Search },
  ],
};

export function settingsModuleHref(slug: SettingsModuleSlug): string {
  return `/app/settings/${slug}`;
}

/** Every Settings screen, grouped by module section; used by search, breadcrumbs and the
 * sidebar. */
export const SETTINGS_NAV_GROUPS: SettingsNavGroup[] = [
  ...SETTINGS_MODULES.flatMap((area) => area.sections),
  SETTINGS_SHARED_GROUP,
];

export const SETTINGS_ITEMS: NavItem[] = SETTINGS_NAV_GROUPS.flatMap((group) => group.items);

/** The module a Settings screen belongs to, by its path (including detail pages under it). */
export function settingsModuleFor(pathname: string): SettingsModule | null {
  for (const area of SETTINGS_MODULES) {
    for (const section of area.sections) {
      for (const item of section.items) {
        if (pathname === item.href || pathname.startsWith(`${item.href}/`)) return area;
      }
    }
  }
  return null;
}
