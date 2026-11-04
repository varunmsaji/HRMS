import { useState } from "react";

import { FormField } from "@/components/common/form-field";
import { EmployeeSelect } from "@/components/employee/employee-select";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import {
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { apiClient } from "@/lib/api/client";
import { describeApiError } from "@/lib/api/errors";
import type { EmployeeDirectory } from "@/lib/employee/use-employee-directory";
import {
  appliedSourceLabel,
  coveragePath,
  coverageRowKey,
  coverageRowLabel,
  type PolicyCoverage,
} from "@/lib/policy-assignment/types";

/** For one employee on one date: which policy applies for each type, and why. */
export function CheckEmployeePanel({
  directory,
  today,
}: {
  directory: EmployeeDirectory;
  today: string;
}) {
  const [employeeId, setEmployeeId] = useState("");
  const [date, setDate] = useState(today);
  const [coverage, setCoverage] = useState<PolicyCoverage | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleCheck() {
    if (!employeeId || !date) {
      setError("Choose an employee and a date.");
      return;
    }
    setLoading(true);
    setError(null);
    setCoverage(null);
    try {
      setCoverage(await apiClient.get<PolicyCoverage>(coveragePath("EMPLOYEE", employeeId, date)));
    } catch (err) {
      setError(describeApiError(err));
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="space-y-4">
      <Card>
        <CardContent className="space-y-4 pt-6">
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <FormField id="check-employee" label="Employee" required>
              <EmployeeSelect directory={directory} value={employeeId} onChange={setEmployeeId} />
            </FormField>
            <FormField id="check-date" label="Date" required>
              <Input type="date" value={date} onChange={(e) => setDate(e.target.value)} />
            </FormField>
          </div>
          <Button type="button" onClick={() => void handleCheck()} disabled={loading}>
            {loading ? "Checking…" : "Check"}
          </Button>
          {error ? <p className="text-sm text-danger">{error}</p> : null}
        </CardContent>
      </Card>

      {coverage ? (
        <TableContainer>
          <Table>
            <TableHeader>
              <TableRow className="hover:bg-transparent">
                <TableHead>Policy type</TableHead>
                <TableHead>Applies</TableHead>
                <TableHead>Comes from</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {coverage.rows.map((row) => (
                <TableRow key={coverageRowKey(row)}>
                  <TableCell className="font-medium text-foreground">
                    {coverageRowLabel(row)}
                  </TableCell>
                  <TableCell>
                    {row.applied ? (
                      <>
                        <p className="text-sm text-foreground">
                          {row.applied.policy_name ?? "Name unavailable"}
                        </p>
                        {!row.applied.has_rules ? (
                          <p className="mt-0.5 text-xs text-danger">
                            No published rules on this date, so this rule is not applied.
                          </p>
                        ) : null}
                      </>
                    ) : (
                      <Badge variant="outline">Not set</Badge>
                    )}
                  </TableCell>
                  <TableCell className="text-sm text-foreground-secondary">
                    {row.applied
                      ? row.applied.scope_type === "EMPLOYEE"
                        ? "Set for this employee"
                        : appliedSourceLabel(row.applied)
                      : "Nothing assigned at any level"}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </TableContainer>
      ) : null}
    </div>
  );
}
