import { AlertTriangle, ArrowUpRight } from "lucide-react";
import Link from "next/link";

import type { NavItem } from "@/components/layout/nav-items";
import { SETTINGS_ITEM_DESCRIPTIONS } from "@/components/settings/item-descriptions";
import { useItemStatus } from "@/lib/settings/item-status";
import { cn } from "@/lib/utils";

/** A link card to one Settings screen. With `withStatus`, it also says how things stand there,
 * e.g. "3 shifts" or "2 policies · 1 not assigned". */
export function SettingsItemCard({ item, withStatus = false }: { item: NavItem; withStatus?: boolean }) {
  const Icon = item.icon;
  const description = SETTINGS_ITEM_DESCRIPTIONS[item.href];
  const status = useItemStatus(item.href, withStatus);
  return (
    <Link
      href={item.href}
      className="group relative flex items-start gap-3 rounded-lg border border-border bg-card p-4 transition-all duration-motion-instant hover:border-primary/40 hover:shadow-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
    >
      <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md bg-muted text-foreground-secondary transition-colors group-hover:bg-primary/10 group-hover:text-primary">
        <Icon className="h-4 w-4" aria-hidden="true" />
      </span>
      <span className="min-w-0 flex-1">
        <span className="block truncate text-sm font-medium text-foreground">{item.label}</span>
        {description ? (
          <span className="mt-0.5 block text-xs text-foreground-secondary">{description}</span>
        ) : null}
        {status ? (
          <span
            className={cn(
              "mt-1.5 inline-flex items-center gap-1 text-xs font-medium",
              status.tone === "warning"
                ? "text-warning"
                : status.tone === "ok"
                  ? "text-foreground"
                  : "text-foreground-muted",
            )}
          >
            {status.tone === "warning" ? (
              <AlertTriangle className="h-3 w-3" aria-hidden="true" />
            ) : null}
            {status.text}
          </span>
        ) : null}
      </span>
      <ArrowUpRight
        className="h-4 w-4 shrink-0 text-foreground-disabled opacity-0 transition-opacity group-hover:opacity-100"
        aria-hidden="true"
      />
    </Link>
  );
}
