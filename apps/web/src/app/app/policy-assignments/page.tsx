"use client";

import { useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";

import { LoadingState } from "@/components/common/loading-state";
import { PageHeader } from "@/components/common/page-header";
import { AssignmentHistoryPanel } from "@/components/policy-assignment/assignment-history-panel";
import { CheckEmployeePanel } from "@/components/policy-assignment/check-employee-panel";
import { SetPoliciesPanel } from "@/components/policy-assignment/set-policies-panel";
import { businessToday } from "@/lib/attendance/format";
import { useAuth } from "@/lib/auth/auth-context";
import { useEmployeeDirectory } from "@/lib/employee/use-employee-directory";
import { cn } from "@/lib/utils";

type TabKey = "set" | "all" | "check";
const TABS: Array<{ key: TabKey; label: string }> = [
  { key: "set", label: "Set policies" },
  { key: "all", label: "All assignments" },
  { key: "check", label: "Check an employee" },
];

function PolicyAssignmentsContent() {
  const params = useSearchParams();
  const { user } = useAuth();
  const directory = useEmployeeDirectory();
  const today = businessToday(user?.company_timezone ?? "Asia/Kolkata");
  const [tab, setTab] = useState<TabKey>(params.get("tab") === "check" ? "check" : "set");

  return (
    <div className="space-y-6">
      <PageHeader
        backHref="/app/settings"
        backLabel="Settings"
        title="Policy Assignments"
        description="Choose who follows which rules. Anything not set for a group is inherited from a wider one, and the most specific setting wins."
      />

      <div className="flex gap-1 overflow-x-auto border-b border-border" role="tablist">
        {TABS.map((item) => (
          <button
            key={item.key}
            type="button"
            role="tab"
            aria-selected={tab === item.key}
            onClick={() => setTab(item.key)}
            className={cn(
              "shrink-0 border-b-2 px-3.5 py-2.5 text-sm font-medium transition-colors duration-motion-instant focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
              tab === item.key
                ? "border-primary text-primary"
                : "border-transparent text-foreground-secondary hover:border-border-strong hover:text-foreground",
            )}
          >
            {item.label}
          </button>
        ))}
      </div>

      {tab === "set" ? <SetPoliciesPanel directory={directory} today={today} /> : null}
      {tab === "all" ? <AssignmentHistoryPanel directory={directory} today={today} /> : null}
      {tab === "check" ? <CheckEmployeePanel directory={directory} today={today} /> : null}
    </div>
  );
}

export default function PolicyAssignmentsPage() {
  return (
    <Suspense fallback={<LoadingState label="Loading policy assignments…" />}>
      <PolicyAssignmentsContent />
    </Suspense>
  );
}
