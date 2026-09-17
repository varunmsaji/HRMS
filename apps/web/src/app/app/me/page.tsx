"use client";

import { useCallback, useEffect, useState } from "react";

import { EmployeeAttendancePanel } from "@/components/attendance/employee-attendance-panel";
import { AssignmentPanel } from "@/components/employee/assignment-panel";
import { BankingPanel } from "@/components/employee/banking-panel";
import { CompensationPanel } from "@/components/employee/compensation-panel";
import { EmployeeOverview } from "@/components/employee/employee-overview";
import { EmployeeStatusBadge } from "@/components/employee/employee-status-badge";
import { EmploymentPanel } from "@/components/employee/employment-panel";
import { StatutoryPanel } from "@/components/employee/statutory-panel";
import { EmptyState } from "@/components/common/empty-state";
import { ErrorState } from "@/components/common/error-state";
import { LoadingState } from "@/components/common/loading-state";
import { PageHeader } from "@/components/common/page-header";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { apiClient } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import { useAuth } from "@/lib/auth/auth-context";
import { usePermissions } from "@/lib/auth/use-permissions";
import type { Employee } from "@/lib/employee/types";
import { cn } from "@/lib/utils";

type TabKey =
  | "overview"
  | "employment"
  | "assignment"
  | "compensation"
  | "statutory"
  | "banking"
  | "attendance";

const TABS: Array<{ key: TabKey; label: string; permission?: string }> = [
  { key: "overview", label: "Overview" },
  { key: "employment", label: "Employment" },
  { key: "assignment", label: "Assignment" },
  { key: "compensation", label: "Compensation", permission: "EMPLOYEE.VIEW_COMPENSATION" },
  { key: "statutory", label: "Statutory", permission: "EMPLOYEE.VIEW_STATUTORY" },
  { key: "banking", label: "Banking", permission: "EMPLOYEE.VIEW_BANKING" },
  { key: "attendance", label: "Attendance", permission: "ATTENDANCE.VIEW" },
];

function employeeName(employee: Employee): string {
  return (
    employee.display_name?.trim() || [employee.first_name, employee.last_name].filter(Boolean).join(" ")
  );
}

export default function MyProfilePage() {
  const { user } = useAuth();
  const { can } = usePermissions();

  const [employee, setEmployee] = useState<Employee | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<ApiError | null>(null);
  const [tab, setTab] = useState<TabKey>("overview");

  const employeeId = user?.employee_id ?? null;

  const loadEmployee = useCallback(async () => {
    if (!employeeId) {
      setLoading(false);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const data = await apiClient.get<Employee>(`/employees/${employeeId}`);
      setEmployee(data);
    } catch (err) {
      setEmployee(null);
      setError(
        err instanceof ApiError
          ? err
          : new ApiError({ status: 0, code: "UNKNOWN_ERROR", message: "Something went wrong." }),
      );
    } finally {
      setLoading(false);
    }
  }, [employeeId]);

  useEffect(() => {
    void loadEmployee();
  }, [loadEmployee]);

  const visibleTabs = TABS.filter((item) => !item.permission || can(item.permission));

  if (!employeeId) {
    return (
      <div className="space-y-6">
        <PageHeader title="My Profile" />
        <EmptyState
          title="No employee record linked to your account"
          description="Ask your admin to link your login to an employee record."
        />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title={employee ? employeeName(employee) || employee.employee_code : "My Profile"}
        description={employee ? `Employee code ${employee.employee_code}` : undefined}
      />

      {employee ? (
        <div className="flex flex-wrap items-center gap-2">
          <EmployeeStatusBadge status={employee.status} />
          <Badge variant={employee.is_active ? "secondary" : "outline"}>
            {employee.is_active ? "Active" : "Inactive"}
          </Badge>
        </div>
      ) : null}

      {loading ? (
        <Card>
          <CardContent className="pt-6">
            <LoadingState label="Loading your profile…" />
          </CardContent>
        </Card>
      ) : null}

      {error && !loading ? (
        <Card>
          <CardContent className="pt-6">
            <ErrorState message={error.message} onRetry={() => void loadEmployee()} />
          </CardContent>
        </Card>
      ) : null}

      {!loading && !error && employee ? (
        <div className="space-y-4">
          <div className="flex gap-1 overflow-x-auto border-b border-border" role="tablist">
            {visibleTabs.map((item) => (
              <button
                key={item.key}
                type="button"
                role="tab"
                aria-selected={tab === item.key}
                onClick={() => setTab(item.key)}
                className={cn(
                  "shrink-0 border-b-2 px-3 py-2 text-sm font-medium transition-colors",
                  tab === item.key
                    ? "border-primary text-foreground"
                    : "border-transparent text-foreground-muted hover:text-foreground",
                )}
              >
                {item.label}
              </button>
            ))}
          </div>

          {tab === "overview" ? <EmployeeOverview employee={employee} /> : null}
          {tab === "employment" ? <EmploymentPanel employeeId={employee.id} /> : null}
          {tab === "assignment" ? <AssignmentPanel employeeId={employee.id} /> : null}
          {tab === "compensation" ? <CompensationPanel employeeId={employee.id} /> : null}
          {tab === "statutory" ? <StatutoryPanel employeeId={employee.id} /> : null}
          {tab === "banking" ? <BankingPanel employeeId={employee.id} /> : null}
          {tab === "attendance" ? (
            <EmployeeAttendancePanel employeeId={employee.id} employeeLabel={employeeName(employee)} />
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
