import Link from "next/link";

import { PageHeader } from "@/components/common/page-header";
import { SETTINGS_NAV_GROUPS } from "@/components/layout/nav-items";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

export default function SettingsPage() {
  return (
    <div className="space-y-6">
      <PageHeader
        title="Settings"
        description="Organisation structure, calendars, policies, and administration."
      />

      <div className="grid gap-6 sm:grid-cols-2 xl:grid-cols-3">
        {SETTINGS_NAV_GROUPS.map((group) => (
          <Card key={group.label}>
            <CardHeader>
              <CardTitle className="text-md">{group.label}</CardTitle>
            </CardHeader>
            <CardContent className="p-0">
              <nav className="flex flex-col divide-y divide-border" aria-label={group.label}>
                {group.items.map((item) => {
                  const Icon = item.icon;
                  return (
                    <Link
                      key={item.href}
                      href={item.href}
                      className="flex items-center gap-3 px-6 py-3 text-sm font-medium text-foreground-secondary transition-colors hover:bg-muted hover:text-foreground"
                    >
                      <Icon className="h-4 w-4 shrink-0" aria-hidden="true" />
                      {item.label}
                    </Link>
                  );
                })}
              </nav>
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  );
}
