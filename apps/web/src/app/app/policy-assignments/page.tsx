"use client";

import { useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";

import { LoadingState } from "@/components/common/loading-state";
import { PageHeader } from "@/components/common/page-header";
import { AssignmentHistoryPanel } from "@/components/policy-assignment/assignment-history-panel";
import { CheckEmployeePanel } from "@/components/policy-assignment/check-employee-panel";
import { SetPoliciesPanel } from "@/components/policy-assignment/set-policies-panel";
import { TabBar } from "@/components/ui/tab-bar";
import { businessToday } from "@/lib/attendance/format";
import { useAuth } from "@/lib/auth/auth-context";
import { useEmployeeDirectory } from "@/lib/employee/use-employee-directory";

type TabKey = "set" | "all" | "check";
const TABS: Array<{ key: TabKey; label: string }> = [
  { key: "set", label: "Set rules for a group" },
  { key: "all", label: "All assignments" },
  { key: "check", label: "Check a person" },
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
        title="Rules by Group"
        description="Choose who follows which rules. Anything not set for a group is inherited from a wider one, and the most specific setting wins."
      />

      <TabBar tabs={TABS} value={tab} onChange={setTab} label="Policy assignment views" />

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
