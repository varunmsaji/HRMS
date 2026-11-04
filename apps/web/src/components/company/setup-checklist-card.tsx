"use client";

import { ArrowRight, Circle, CircleCheck } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { apiClient } from "@/lib/api/client";
import type { SetupChecklist } from "@/lib/company/setup-checklist";
import { cn } from "@/lib/utils";

/** Loads the checklist. `null` until it arrives or when the user may not see it, so callers
 * render nothing rather than an error for something that is only a nudge. */
function useSetupChecklist(): SetupChecklist | null {
  const [checklist, setChecklist] = useState<SetupChecklist | null>(null);
  useEffect(() => {
    let current = true;
    apiClient
      .get<SetupChecklist>("/companies/current/setup-checklist")
      .then((data) => {
        // Anything that is not a checklist is treated as unavailable, never rendered half-way.
        if (current) setChecklist(data && Array.isArray(data.items) ? data : null);
      })
      .catch(() => {
        if (current) setChecklist(null);
      });
    return () => {
      current = false;
    };
  }, []);
  return checklist;
}

/** A single line on the Settings page: how far along, and the next thing to do. Hidden once the
 * essentials are done, so it never nags. */
export function SetupChecklistBanner() {
  const checklist = useSetupChecklist();
  if (!checklist || checklist.required_complete >= checklist.required_total) return null;
  const next = checklist.items.find((item) => item.code === checklist.next_code);
  return (
    <Card>
      <CardContent className="flex flex-wrap items-center justify-between gap-4 pt-6">
        <div className="min-w-0 space-y-1">
          <p className="text-sm font-medium text-foreground">
            Finish setting up: {checklist.required_complete} of {checklist.required_total}{" "}
            essentials done
          </p>
          {next ? (
            <p className="text-sm text-foreground-secondary">
              Next: {next.label}. {next.description}
            </p>
          ) : null}
        </div>
        <div className="flex items-center gap-3">
          <Link href="/app/setup" className="text-sm font-medium text-primary hover:underline">
            See all steps
          </Link>
          {next ? (
            <Button asChild size="sm">
              <Link href={next.path}>
                Go <ArrowRight className="h-4 w-4" aria-hidden="true" />
              </Link>
            </Button>
          ) : null}
        </div>
      </CardContent>
    </Card>
  );
}

/** The full list, on the Setup page: essentials first, then the optional ones. */
export function SetupChecklistList() {
  const checklist = useSetupChecklist();
  if (!checklist) return null;
  const essentials = checklist.items.filter((item) => item.required);
  const optional = checklist.items.filter((item) => !item.required);

  function section(title: string, items: typeof essentials) {
    return (
      <div className="space-y-2">
        <h3 className="text-sm font-medium text-foreground">{title}</h3>
        <ul className="divide-y divide-border rounded-md border border-border">
          {items.map((item) => (
            <li key={item.code} className="flex items-center justify-between gap-4 px-4 py-3">
              <div className="flex min-w-0 items-start gap-3">
                {item.is_complete ? (
                  <CircleCheck className="mt-0.5 h-4 w-4 shrink-0 text-success" aria-hidden="true" />
                ) : (
                  <Circle
                    className={cn("mt-0.5 h-4 w-4 shrink-0 text-foreground-muted")}
                    aria-hidden="true"
                  />
                )}
                <div className="min-w-0">
                  <p className="text-sm font-medium text-foreground">{item.label}</p>
                  <p className="text-xs text-foreground-secondary">{item.description}</p>
                </div>
              </div>
              {item.is_complete ? (
                <span className="text-xs font-medium text-success">Done</span>
              ) : (
                <Button asChild size="sm" variant="outline">
                  <Link href={item.path}>Set up</Link>
                </Button>
              )}
            </li>
          ))}
        </ul>
      </div>
    );
  }

  return (
    <Card>
      <CardContent className="space-y-5 pt-6">
        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-semibold text-foreground">Get your rules ready</h2>
            <span className="text-xs text-foreground-secondary">
              {checklist.required_complete} of {checklist.required_total} essentials done
            </span>
          </div>
          <Progress value={checklist.required_complete} max={checklist.required_total} />
        </div>
        {section("Essentials", essentials)}
        {section("When you need them", optional)}
      </CardContent>
    </Card>
  );
}
