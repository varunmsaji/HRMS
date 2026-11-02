import Link from "next/link";
import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

export function computeInitials(name?: string | null, fallbackCode?: string | null): string {
  // Pickers and queues label people "Name (EMP-0030)"; the code is not part of the name.
  const cleaned = (name ?? "").replace(/\s*\([^)]*\)\s*$/, "").trim();
  if (cleaned) {
    const parts = cleaned.split(/\s+/).filter(Boolean);
    if (parts.length >= 2) {
      return `${parts[0][0]}${parts[parts.length - 1][0]}`.toUpperCase();
    }
    return cleaned.slice(0, 2).toUpperCase();
  }
  if (fallbackCode && fallbackCode.trim()) {
    return fallbackCode.trim().slice(0, 2).toUpperCase();
  }
  return "EM";
}

/** "Imran Shetty (EMP-0030)" → name + code. Only a code-looking suffix is split off: alphanumeric
 * segments joined by - or _, containing at least one digit — so a name that merely ends in
 * brackets ("Raj (Jr)") is left alone. */
const CODE_SUFFIX = /\s*\(([A-Za-z0-9]{2,}(?:[-_][A-Za-z0-9]+)*)\)\s*$/;

export function splitEmployeeLabel(label: string): { name: string; code: string | null } {
  const match = CODE_SUFFIX.exec(label);
  if (!match || !/\d/.test(match[1])) return { name: label, code: null };
  const name = label.slice(0, match.index).trim();
  return name ? { name, code: match[1] } : { name: label, code: null };
}

interface EmployeeAvatarProps {
  name?: string | null;
  code?: string | null;
  size?: "sm" | "md" | "lg";
  className?: string;
}

const SIZE_CLASSES: Record<NonNullable<EmployeeAvatarProps["size"]>, string> = {
  sm: "h-7 w-7 text-2xs",
  md: "h-8 w-8 text-xs",
  lg: "h-11 w-11 text-sm",
};

export function EmployeeAvatar({
  name,
  code,
  size = "md",
  className,
}: EmployeeAvatarProps) {
  return (
    <span
      aria-hidden="true"
      className={cn(
        "inline-flex shrink-0 select-none items-center justify-center rounded-full border border-primary-border bg-primary-subtle font-semibold tracking-tight text-primary",
        SIZE_CLASSES[size],
        className,
      )}
    >
      {computeInitials(name, code)}
    </span>
  );
}

interface EmployeeIdentityCellProps {
  name: string;
  code?: string | null;
  subtitle?: ReactNode;
  href?: string;
  size?: "sm" | "md";
  className?: string;
}

/**
 * Reusable HR employee identity pattern for directory tables, attendance rosters,
 * leave queues, and payroll rows.
 */
export function EmployeeIdentityCell({
  name,
  code,
  subtitle,
  href,
  size = "md",
  className,
}: EmployeeIdentityCellProps) {
  const split = code ? { name: name.trim(), code } : splitEmployeeLabel(name.trim());
  const displayName = split.name || "—";
  const identityCode = split.code;
  const content = (
    <div className={cn("flex items-center gap-2.5 min-w-0", className)}>
      <EmployeeAvatar name={displayName} code={identityCode} size={size} />
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-1.5">
          <span className="truncate font-medium text-foreground group-hover/emp:text-primary group-hover/emp:underline">
            {displayName}
          </span>
        </div>
        {subtitle || identityCode ? (
          <div className="flex items-center gap-1.5 truncate text-xs text-foreground-muted">
            {identityCode ? <span className="font-mono text-2xs text-foreground-secondary">{identityCode}</span> : null}
            {identityCode && subtitle ? <span aria-hidden="true">·</span> : null}
            {subtitle ? <span className="truncate">{subtitle}</span> : null}
          </div>
        ) : null}
      </div>
    </div>
  );

  if (href) {
    return (
      <Link
        href={href}
        className="group/emp inline-flex max-w-full rounded-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      >
        {content}
      </Link>
    );
  }

  return content;
}
