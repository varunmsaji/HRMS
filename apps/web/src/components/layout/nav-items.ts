import {
  Briefcase,
  Building,
  Building2,
  Clock,
  Landmark,
  LayoutDashboard,
  Layers,
  ListChecks,
  Network,
  Users,
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
  { href: "/app/setup", label: "Setup", icon: ListChecks },
];
