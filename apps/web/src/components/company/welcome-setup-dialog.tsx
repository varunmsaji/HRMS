"use client";

import { CircleCheck, Circle } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { apiClient } from "@/lib/api/client";
import { useAuth } from "@/lib/auth/auth-context";
import { usePermissions } from "@/lib/auth/use-permissions";
import type { CompanySetupProgressSummary } from "@/lib/company/types";
import { cn } from "@/lib/utils";

interface WelcomeStep {
  key: string;
  label: string;
  hint: string;
  href: string;
  done: boolean;
}

const seenKey = (userId: string) => `hrms.welcome-setup.seen.${userId}`;

function hasBeenSeen(userId: string): boolean {
  try {
    return window.localStorage.getItem(seenKey(userId)) !== null;
  } catch {
    // Storage blocked: err on the side of not nagging.
    return true;
  }
}

function markSeen(userId: string) {
  try {
    window.localStorage.setItem(seenKey(userId), new Date().toISOString());
  } catch {
    // Nothing to do; the dialog just may show again.
  }
}

async function loadSteps(): Promise<WelcomeStep[] | null> {
  try {
    const [progress, legalEntities, branches] = await Promise.all([
      apiClient.get<CompanySetupProgressSummary>("/companies/current/setup-progress"),
      apiClient.get<unknown[]>("/legal-entities"),
      apiClient.get<unknown[]>("/branches"),
    ]);
    if (!progress || !Array.isArray(legalEntities) || !Array.isArray(branches)) return null;
    const profileDone =
      progress.steps.find((step) => step.code === "COMPANY_PROFILE")?.is_complete ?? false;
    return [
      {
        key: "profile",
        label: "Complete your company profile",
        hint: "Name, address, tax details and regional settings.",
        href: "/app/company",
        done: profileDone,
      },
      {
        key: "legal-entity",
        label: "Add your company (legal entity)",
        hint: "The registered entity that employs your people. Branches belong to it.",
        href: "/app/legal-entities",
        done: legalEntities.length > 0,
      },
      {
        key: "branches",
        label: "Add your branches",
        hint: "Each office or location where your employees work.",
        href: "/app/branches",
        done: branches.length > 0,
      },
    ];
  } catch {
    return null;
  }
}

/**
 * First-login welcome for a new company's administrator: a one-time card that walks them through
 * the company profile, their company (legal entity) and branches. It opens once per user per
 * browser (remembered in `localStorage`); afterwards the dashboard's "Finish setting up" banner
 * and the Setup page remain the way back. Never blocks anything, and stays away while the company
 * is still awaiting approval (it is read-only then, so none of these steps could be saved).
 */
export function WelcomeSetupDialog({ companyName }: { companyName: string }) {
  const router = useRouter();
  const { user } = useAuth();
  const { can } = usePermissions();
  const [steps, setSteps] = useState<WelcomeStep[] | null>(null);
  const [open, setOpen] = useState(false);

  const userId = user?.id ?? null;
  const eligible =
    userId !== null &&
    can("ORG.COMPANY.MANAGE") &&
    can("ORG.BRANCH.MANAGE") &&
    user?.company_status !== "PENDING_APPROVAL";

  useEffect(() => {
    if (!eligible || userId === null || hasBeenSeen(userId)) return;
    let cancelled = false;
    void loadSteps().then((loaded) => {
      if (cancelled || !loaded || loaded.every((step) => step.done)) return;
      markSeen(userId);
      setSteps(loaded);
      setOpen(true);
    });
    return () => {
      cancelled = true;
    };
  }, [eligible, userId]);

  if (!steps) return null;

  const nextStep = steps.find((step) => !step.done);
  const doneCount = steps.filter((step) => step.done).length;

  function goToNext() {
    setOpen(false);
    if (nextStep) router.push(nextStep.href);
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>Welcome to {companyName}</DialogTitle>
          <DialogDescription>
            Let&apos;s get your company set up. It takes a few minutes, and {doneCount} of{" "}
            {steps.length} steps {doneCount === 1 ? "is" : "are"} already done.
          </DialogDescription>
        </DialogHeader>

        <ol className="space-y-3">
          {steps.map((step, index) => {
            const isNext = step === nextStep;
            return (
              <li
                key={step.key}
                className={cn(
                  "flex items-start gap-3 rounded-lg border p-3",
                  isNext ? "border-primary-border bg-primary-subtle/50" : "border-border",
                )}
              >
                {step.done ? (
                  <CircleCheck className="mt-0.5 h-5 w-5 shrink-0 text-success" aria-hidden="true" />
                ) : (
                  <Circle className="mt-0.5 h-5 w-5 shrink-0 text-foreground-muted" aria-hidden="true" />
                )}
                <div className="min-w-0">
                  <p className="text-sm font-medium text-foreground">
                    {index + 1}. {step.label}
                    {step.done ? <span className="ml-2 text-xs text-success">Done</span> : null}
                  </p>
                  <p className="mt-0.5 text-xs text-foreground-secondary">{step.hint}</p>
                </div>
              </li>
            );
          })}
        </ol>

        <DialogFooter>
          <Button variant="outline" onClick={() => setOpen(false)}>
            I&apos;ll do this later
          </Button>
          <Button onClick={goToNext}>Start setup</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
