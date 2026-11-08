"use client";

import { Circle, CircleCheck } from "lucide-react";
import Link from "next/link";
import { notFound, useParams } from "next/navigation";
import { useState, type ReactNode } from "react";

import { FaceEnrollmentPolicyCard } from "@/components/attendance/face-enrollment-policy-card";
import { PageHeader } from "@/components/common/page-header";
import { useSetupChecklist } from "@/components/company/setup-checklist-card";
import {
  SETTINGS_MODULES,
  SETTINGS_SHARED_GROUP,
  type SettingsModule,
  type SettingsNavGroup,
} from "@/components/layout/nav-items";
import { CompanyFollowsSummary } from "@/components/settings/company-follows-summary";
import { SettingsItemCard } from "@/components/settings/settings-item-card";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { businessToday } from "@/lib/attendance/format";
import { useAuth } from "@/lib/auth/auth-context";
import { usePermissions } from "@/lib/auth/use-permissions";
import type { SetupChecklist } from "@/lib/company/setup-checklist";

function slug(label: string) {
  return label.toLowerCase().replace(/[^a-z0-9]+/g, "-");
}

function Step({
  number,
  title,
  description,
  children,
}: {
  number: number;
  title: string;
  description?: string;
  children: ReactNode;
}) {
  const id = `${slug(title)}-title`;
  return (
    <section aria-labelledby={id} className="space-y-3">
      <div className="flex items-start gap-3">
        <span
          className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-primary/10 text-xs font-semibold text-primary"
          aria-hidden="true"
        >
          {number}
        </span>
        <div className="min-w-0">
          <h2 id={id} className="text-md font-semibold text-foreground">
            {title}
          </h2>
          {description ? (
            <p className="mt-0.5 text-sm text-foreground-secondary">{description}</p>
          ) : null}
        </div>
      </div>
      <div className="space-y-3 sm:pl-9">{children}</div>
    </section>
  );
}

function SectionCards({ section }: { section: SettingsNavGroup }) {
  const [expanded, setExpanded] = useState(false);
  const shown = section.items.filter((item) => expanded || !item.advanced);
  const hidden = section.items.length - shown.length;
  return (
    <>
      <div className="grid gap-3 sm:grid-cols-2 2xl:grid-cols-3">
        {shown.map((item) => (
          <SettingsItemCard key={item.href} item={item} withStatus />
        ))}
      </div>
      {hidden > 0 ? (
        <button
          type="button"
          onClick={() => setExpanded(true)}
          className="text-sm font-medium text-primary hover:underline"
        >
          Show {hidden} more
        </button>
      ) : null}
    </>
  );
}

/** What is left to set up in this area, from the company's setup checklist. */
function ModuleProgress({
  area,
  checklist,
}: {
  area: SettingsModule;
  checklist: SetupChecklist | null;
}) {
  if (!checklist || area.checklistCodes.length === 0) return null;
  const items = checklist.items.filter((item) => area.checklistCodes.includes(item.code));
  if (items.length === 0) return null;
  const done = items.filter((item) => item.is_complete).length;
  const open = items.filter((item) => !item.is_complete);
  return (
    <Card>
      <CardContent className="space-y-3 pt-6">
        <p className="text-sm font-medium text-foreground">
          {open.length === 0
            ? `${area.label} is set up.`
            : `${done} of ${items.length} setup steps done`}
        </p>
        {open.length > 0 ? (
          <ul className="divide-y divide-border rounded-md border border-border">
            {items.map((item) => (
              <li key={item.code} className="flex items-center justify-between gap-4 px-4 py-2.5">
                <div className="flex min-w-0 items-start gap-3">
                  {item.is_complete ? (
                    <CircleCheck className="mt-0.5 h-4 w-4 shrink-0 text-success" aria-hidden="true" />
                  ) : (
                    <Circle className="mt-0.5 h-4 w-4 shrink-0 text-foreground-muted" aria-hidden="true" />
                  )}
                  <div className="min-w-0">
                    <p className="text-sm text-foreground">
                      {item.label}
                      {item.required ? null : (
                        <span className="text-foreground-muted"> (optional)</span>
                      )}
                    </p>
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
        ) : null}
      </CardContent>
    </Card>
  );
}

export default function SettingsModulePage() {
  const params = useParams<{ module: string }>();
  const area = SETTINGS_MODULES.find((m) => m.slug === params.module);
  const { user } = useAuth();
  const { can } = usePermissions();
  const checklist = useSetupChecklist({ enabled: Boolean(area?.checklistCodes.length) });
  const today = businessToday(user?.company_timezone ?? "Asia/Kolkata");

  if (!area) notFound();

  const steps: ReactNode[] = [];
  let number = 0;

  function followsStep() {
    if (!area?.followsKinds) return null;
    number += 1;
    return (
      <Step
        key="follows"
        number={number}
        title="Who follows which rules"
        description="What the whole company follows today. Open a policy to give it to a branch, department, grade or person instead."
      >
        <CompanyFollowsSummary kinds={area.followsKinds} today={today} />
        <div className="grid gap-3 sm:grid-cols-2 2xl:grid-cols-3">
          {SETTINGS_SHARED_GROUP.items.map((item) => (
            <SettingsItemCard key={item.href} item={item} />
          ))}
        </div>
      </Step>
    );
  }

  for (const section of area.sections) {
    number += 1;
    steps.push(
      <Step
        key={section.label}
        number={number}
        title={section.label}
        description={section.description}
      >
        <SectionCards section={section} />
        {section.items.some((item) => item.href === "/app/attendance-policies") &&
        can("ATTENDANCE.FACE_ENROLLMENT_MANAGE") ? (
          <FaceEnrollmentPolicyCard />
        ) : null}
      </Step>,
    );
    if (area.followsAfter === section.label) steps.push(followsStep());
  }
  if (area.followsKinds && !area.followsAfter) steps.push(followsStep());

  return (
    <div className="space-y-6">
      <PageHeader
        backHref="/app/settings"
        backLabel="Settings"
        title={area.label}
        description={area.description}
      />
      <ModuleProgress area={area} checklist={checklist} />
      <div className="space-y-10">{steps}</div>
    </div>
  );
}
