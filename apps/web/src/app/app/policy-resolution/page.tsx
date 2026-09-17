"use client";

import { useEffect, useState } from "react";

import { EmptyState } from "@/components/common/empty-state";
import { FormField } from "@/components/common/form-field";
import { PageHeader } from "@/components/common/page-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/native-select";
import { apiClient } from "@/lib/api/client";
import { ApiError, describeApiError } from "@/lib/api/errors";
import { businessToday } from "@/lib/attendance/format";
import type { PolicyResolution } from "@/lib/attendance-policy/types";
import { useAuth } from "@/lib/auth/auth-context";
import { POLICY_KIND_LABELS } from "@/lib/policy-assignment/types";

interface EmployeeOption {
  id: string;
  first_name: string;
  last_name: string | null;
  employee_code: string | null;
}

const RESOLUTION_KINDS = ["ATTENDANCE_POLICY", "OVERTIME_POLICY", "REGULARIZATION_POLICY"] as const;

/** HR-debugging "resolved through" explain view (architecture §35) — mirrors `/calendar-resolution`
 * (W1) for the three W3 policy kinds. Answers: for this employee, on this date, which policy
 * applies, and which precedence level (EMPLOYEE/SHIFT/.../COMPANY) matched. */
export default function PolicyResolutionPage() {
  const { user } = useAuth();
  const [employees, setEmployees] = useState<EmployeeOption[]>([]);
  const [employeeId, setEmployeeId] = useState("");
  const [date, setDate] = useState(businessToday(user?.company_timezone ?? "Asia/Kolkata"));
  const [policyKind, setPolicyKind] = useState<(typeof RESOLUTION_KINDS)[number]>(
    "ATTENDANCE_POLICY",
  );

  const [result, setResult] = useState<PolicyResolution | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    void apiClient
      .get<EmployeeOption[]>("/employees")
      .then(setEmployees)
      .catch(() => setEmployees([]));
  }, []);

  async function handleResolve() {
    if (!employeeId || !date) {
      setError("Choose an employee and a date.");
      return;
    }
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      const data = await apiClient.get<PolicyResolution>(
        `/attendance-policy-resolution?employee_id=${employeeId}&date=${date}&policy_kind=${policyKind}`,
      );
      setResult(data);
    } catch (err) {
      setError(err instanceof ApiError ? describeApiError(err) : "Something went wrong.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Policy Resolution Preview"
        description="Debug which policy applies to an employee on a given date, and which precedence level resolved it — the same WD-09 walk the future attendance engine uses."
      />

      <Card>
        <CardContent className="space-y-4 pt-6">
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
            <FormField id="resolution-employee" label="Employee" required>
              <NativeSelect value={employeeId} onChange={(e) => setEmployeeId(e.target.value)}>
                <option value="">Choose…</option>
                {employees.map((emp) => (
                  <option key={emp.id} value={emp.id}>
                    {emp.first_name} {emp.last_name ?? ""}
                    {emp.employee_code ? ` (${emp.employee_code})` : ""}
                  </option>
                ))}
              </NativeSelect>
            </FormField>
            <FormField id="resolution-date" label="Date" required>
              <Input type="date" value={date} onChange={(e) => setDate(e.target.value)} />
            </FormField>
            <FormField id="resolution-kind" label="Policy kind" required>
              <NativeSelect
                value={policyKind}
                onChange={(e) =>
                  setPolicyKind(e.target.value as (typeof RESOLUTION_KINDS)[number])
                }
              >
                {RESOLUTION_KINDS.map((kind) => (
                  <option key={kind} value={kind}>
                    {POLICY_KIND_LABELS[kind]}
                  </option>
                ))}
              </NativeSelect>
            </FormField>
          </div>
          <Button type="button" onClick={() => void handleResolve()} disabled={loading}>
            {loading ? "Resolving…" : "Resolve"}
          </Button>
          {error ? <p className="text-sm text-danger">{error}</p> : null}
        </CardContent>
      </Card>

      {result ? (
        <Card>
          <CardContent className="pt-6">
            {result.config_incomplete ? (
              <EmptyState
                title="CONFIG_INCOMPLETE"
                description="No applicable policy is assigned at any scope for this employee and date. This never silently falls back to a default (WD-21) — assign a policy at COMPANY scope at minimum."
              />
            ) : (
              <dl className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                <div>
                  <dt className="text-xs font-medium uppercase tracking-wide text-foreground-muted">
                    Resolved policy
                  </dt>
                  <dd className="mt-0.5 text-sm text-foreground">
                    {result.resolved_policy_name}
                    {result.resolved_policy_code ? ` (${result.resolved_policy_code})` : ""}
                  </dd>
                </div>
                <div>
                  <dt className="text-xs font-medium uppercase tracking-wide text-foreground-muted">
                    Resolved through
                  </dt>
                  <dd className="mt-0.5 text-sm text-foreground">
                    <Badge variant="secondary">{result.resolved_through}</Badge>
                  </dd>
                </div>
                <div>
                  <dt className="text-xs font-medium uppercase tracking-wide text-foreground-muted">
                    Policy version
                  </dt>
                  <dd className="mt-0.5 text-sm text-foreground">{result.resolved_version_id}</dd>
                </div>
              </dl>
            )}
          </CardContent>
        </Card>
      ) : null}
    </div>
  );
}
