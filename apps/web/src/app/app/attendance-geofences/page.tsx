"use client";

import { MapPin } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";

import { EmptyState } from "@/components/common/empty-state";
import { ErrorState } from "@/components/common/error-state";
import { FormField } from "@/components/common/form-field";
import { LoadingState } from "@/components/common/loading-state";
import { PageHeader } from "@/components/common/page-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { NativeSelect } from "@/components/ui/native-select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { EmployeeSelect } from "@/components/employee/employee-select";
import { apiClient } from "@/lib/api/client";
import { useEmployeeDirectory } from "@/lib/employee/use-employee-directory";
import { useEmployeeNames } from "@/lib/employee/use-employee-names";
import { ApiError, describeApiError } from "@/lib/api/errors";
import { usePermissions } from "@/lib/auth/use-permissions";
import {
  formatMetres,
  isUsableGeofence,
  mapLink,
  outcomeLabel,
  type GeofenceAttempt,
  type GeofenceWorkplace,
  type WorkplaceAuthorization,
} from "@/lib/geofence/types";

/** Workplace geofences for attendance. A workplace is a Branch with coordinates and a radius
 * (edited on the branch screen); this page shows where each is used, manages the extra workplaces
 * an employee may punch at, and lets HR review rejected location attempts. Every action is
 * authorised by the API — hiding controls here is convenience only. */
export default function AttendanceGeofencesPage() {
  const { can } = usePermissions();
  const canConfigure = can("ATTENDANCE.POLICY_MANAGE");
  const canReview = can("ATTENDANCE.VIEW_ALL");

  const [workplaces, setWorkplaces] = useState<GeofenceWorkplace[] | null>(null);
  const [authorizations, setAuthorizations] = useState<WorkplaceAuthorization[]>([]);
  const [attempts, setAttempts] = useState<GeofenceAttempt[] | null>(null);
  const [authorizationTotal, setAuthorizationTotal] = useState(0);
  const directory = useEmployeeDirectory({ enabled: canConfigure });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [attemptsError, setAttemptsError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [onlyRejected, setOnlyRejected] = useState(true);

  const nameIds = useMemo(
    () => [
      ...authorizations.map((a) => a.employee_id),
      ...(attempts ?? []).map((a) => a.employee_id),
    ],
    [authorizations, attempts],
  );
  const employeeName = useEmployeeNames(nameIds, directory.employees);

  const [newEmployee, setNewEmployee] = useState("");
  const [newBranch, setNewBranch] = useState("");
  const [saving, setSaving] = useState(false);

  const branchById = useMemo(
    () => new Map((workplaces ?? []).map((w) => [w.branch_id, w])),
    [workplaces],
  );

  const loadConfig = useCallback(async () => {
    if (!canConfigure) {
      setLoading(false);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const [{ data: places }, { data: auths, pagination: authMeta }] = await Promise.all([
        apiClient.getList<GeofenceWorkplace>("/attendance/geofences"),
        apiClient.getList<WorkplaceAuthorization>("/attendance/workplace-authorizations", {
          per_page: 100,
        }),
      ]);
      setWorkplaces(places);
      setAuthorizations(auths);
      setAuthorizationTotal(authMeta?.total ?? auths.length);
    } catch (err) {
      setError(err instanceof ApiError ? describeApiError(err) : "Could not load workplaces.");
    } finally {
      setLoading(false);
    }
  }, [canConfigure]);

  const loadAttempts = useCallback(async () => {
    if (!canReview) return;
    setAttemptsError(null);
    try {
      const { data } = await apiClient.getList<GeofenceAttempt>("/attendance/geofence-attempts", {
        per_page: 50,
        accepted: onlyRejected ? "false" : undefined,
      });
      setAttempts(data);
    } catch (err) {
      setAttemptsError(
        err instanceof ApiError ? describeApiError(err) : "Could not load location attempts.",
      );
    }
  }, [canReview, onlyRejected]);

  useEffect(() => {
    void loadConfig();
  }, [loadConfig]);
  useEffect(() => {
    void loadAttempts();
  }, [loadAttempts]);

  async function addAuthorization() {
    if (!newEmployee || !newBranch) {
      setError("Choose an employee and a workplace.");
      return;
    }
    setSaving(true);
    setError(null);
    setNotice(null);
    try {
      await apiClient.post("/attendance/workplace-authorizations", {
        employee_id: newEmployee,
        branch_id: newBranch,
      });
      setNotice("Workplace authorised. The employee can now punch there.");
      setNewEmployee("");
      setNewBranch("");
      await loadConfig();
    } catch (err) {
      setError(err instanceof ApiError ? describeApiError(err) : "Could not save.");
    } finally {
      setSaving(false);
    }
  }

  async function removeAuthorization(id: string) {
    setSaving(true);
    setError(null);
    setNotice(null);
    try {
      await apiClient.delete(`/attendance/workplace-authorizations/${id}`);
      setNotice("Authorisation removed.");
      await loadConfig();
    } catch (err) {
      setError(err instanceof ApiError ? describeApiError(err) : "Could not remove.");
    } finally {
      setSaving(false);
    }
  }

  const usable = (workplaces ?? []).filter(isUsableGeofence);

  return (
    <div className="space-y-6">
      <PageHeader
        backHref="/app/settings"
        backLabel="Settings"
        title="Workplace Geofences"
        description="Approved workplaces for location-checked attendance. A device-reported location is evidence, not proof of presence: it can be spoofed. The check is switched on per attendance policy (Disabled, Optional or Required)."
      />

      {notice ? (
        <p role="status" className="text-sm text-success">
          {notice}
        </p>
      ) : null}
      {error ? <ErrorState message={error} onRetry={() => void loadConfig()} /> : null}

      {canConfigure ? (
        <>
          <section aria-labelledby="workplaces-heading" className="space-y-3">
            <h2 id="workplaces-heading" className="text-base font-semibold text-foreground">
              Workplaces
            </h2>
            {loading ? (
              <LoadingState label="Loading workplaces…" />
            ) : workplaces && workplaces.length === 0 ? (
              <EmptyState
                icon={MapPin}
                title="No branches yet"
                description="A workplace is a branch with coordinates and a radius. Create a branch first."
                action={
                  <Button asChild>
                    <Link href="/app/branches">Go to branches</Link>
                  </Button>
                }
              />
            ) : (
              <Card>
                <CardContent className="overflow-x-auto pt-6">
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>Workplace</TableHead>
                        <TableHead>Status</TableHead>
                        <TableHead>Location</TableHead>
                        <TableHead>Radius</TableHead>
                        <TableHead>Assigned</TableHead>
                        <TableHead>Also authorised</TableHead>
                        <TableHead className="text-right">Edit</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {(workplaces ?? []).map((w) => (
                        <TableRow key={w.branch_id}>
                          <TableCell className="font-medium">{w.name}</TableCell>
                          <TableCell>
                            {!w.configured ? (
                              <Badge variant="warning">Not configured</Badge>
                            ) : w.is_active ? (
                              <Badge variant="success">Active</Badge>
                            ) : (
                              <Badge variant="secondary">Inactive</Badge>
                            )}
                          </TableCell>
                          <TableCell>
                            {w.latitude !== null && w.longitude !== null ? (
                              <a
                                className="text-primary underline-offset-2 hover:underline"
                                href={mapLink(w.latitude, w.longitude)}
                                target="_blank"
                                rel="noreferrer noopener"
                              >
                                {w.latitude.toFixed(5)}, {w.longitude.toFixed(5)}
                              </a>
                            ) : (
                              "—"
                            )}
                          </TableCell>
                          <TableCell>{w.radius_m ? `${w.radius_m} m` : "—"}</TableCell>
                          <TableCell>{w.assigned_employee_count}</TableCell>
                          <TableCell>{w.authorized_employee_count}</TableCell>
                          <TableCell className="text-right">
                            <Link
                              className="text-sm text-primary hover:underline"
                              href={`/app/branches/${w.branch_id}`}
                            >
                              Edit coordinates &amp; radius
                            </Link>
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                  <p className="mt-3 text-xs text-foreground-secondary">
                    No map component is bundled: coordinates are entered on the branch screen and
                    open in OpenStreetMap for checking. A branch with employees assigned cannot be
                    deactivated; one that is an extra authorised workplace is blocked until those
                    authorisations are removed.
                  </p>
                </CardContent>
              </Card>
            )}
          </section>

          <section aria-labelledby="auth-heading" className="space-y-3">
            <h2 id="auth-heading" className="text-base font-semibold text-foreground">
              Extra workplaces for individual employees
            </h2>
            <p className="text-sm text-foreground-secondary">
              Employees can always punch at the branch on their assignment. Add another approved
              workplace here for people who legitimately work across locations. Employees cannot
              choose a workplace themselves.
            </p>
            <Card>
              <CardContent className="space-y-4 pt-6">
                <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
                  <FormField id="auth-employee" label="Employee">
                    <EmployeeSelect directory={directory} value={newEmployee} onChange={setNewEmployee} />
                  </FormField>
                  <FormField
                    id="auth-branch"
                    label="Workplace"
                    description="Only active branches with coordinates and a radius."
                  >
                    <NativeSelect value={newBranch} onChange={(e) => setNewBranch(e.target.value)}>
                      <option value="">Choose…</option>
                      {usable.map((w) => (
                        <option key={w.branch_id} value={w.branch_id}>
                          {w.name}
                        </option>
                      ))}
                    </NativeSelect>
                  </FormField>
                  <div className="flex items-end">
                    <Button type="button" onClick={() => void addAuthorization()} disabled={saving}>
                      {saving ? "Saving…" : "Authorise"}
                    </Button>
                  </div>
                </div>

                {authorizations.length === 0 ? (
                  <p className="text-sm text-foreground-secondary">
                    No extra workplaces have been authorised.
                  </p>
                ) : (
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>Employee</TableHead>
                        <TableHead>Workplace</TableHead>
                        <TableHead className="text-right">Action</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {authorizations.map((a) => (
                        <TableRow key={a.id}>
                          <TableCell>{employeeName(a.employee_id)}</TableCell>
                          <TableCell>{branchById.get(a.branch_id)?.name ?? a.branch_id}</TableCell>
                          <TableCell className="text-right">
                            <Button
                              type="button"
                              variant="outline"
                              size="sm"
                              disabled={saving}
                              onClick={() => void removeAuthorization(a.id)}
                            >
                              Remove
                            </Button>
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                )}
                {authorizationTotal > authorizations.length ? (
                  <p role="alert" className="text-sm text-warning">
                    Showing the first {authorizations.length} of {authorizationTotal} authorisations —
                    the rest are not listed on this page.
                  </p>
                ) : null}
              </CardContent>
            </Card>
          </section>
        </>
      ) : null}

      {canReview ? (
        <section aria-labelledby="attempts-heading" className="space-y-3">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <h2 id="attempts-heading" className="text-base font-semibold text-foreground">
              Location attempts
            </h2>
            <label className="flex items-center gap-2 text-sm text-foreground">
              <input
                type="checkbox"
                checked={onlyRejected}
                onChange={(e) => setOnlyRejected(e.target.checked)}
              />
              Rejected only
            </label>
          </div>
          <p className="text-sm text-foreground-secondary">
            A rejected attempt never becomes attendance by itself. If the employee was genuinely at
            work, correct their attendance through the regularization workflow, which requires a
            reason and is audited. Coordinates are shown rounded (about 11 m) and are removed after
            the retention period.
          </p>
          {attemptsError ? (
            <ErrorState message={attemptsError} onRetry={() => void loadAttempts()} />
          ) : attempts === null ? (
            <LoadingState label="Loading attempts…" />
          ) : attempts.length === 0 ? (
            <EmptyState
              title={onlyRejected ? "No rejected attempts" : "No attempts recorded"}
              description="Attempts appear here once a policy using Optional or Required location checks is in use."
            />
          ) : (
            <Card>
              <CardContent className="overflow-x-auto pt-6">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>When</TableHead>
                      <TableHead>Employee</TableHead>
                      <TableHead>Punch</TableHead>
                      <TableHead>Result</TableHead>
                      <TableHead>Distance / radius</TableHead>
                      <TableHead>GPS accuracy</TableHead>
                      <TableHead>Mode</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {attempts.map((a) => (
                      <TableRow key={a.id}>
                        <TableCell>{new Date(a.created_at).toLocaleString()}</TableCell>
                        <TableCell>{employeeName(a.employee_id)}</TableCell>
                        <TableCell>{a.direction}</TableCell>
                        <TableCell>
                          <Badge variant={a.accepted ? "success" : "danger"}>
                            {a.accepted ? "Allowed" : "Rejected"}
                          </Badge>{" "}
                          <span className="text-sm">{outcomeLabel(a.outcome)}</span>
                          {a.client_error ? (
                            <span className="block text-xs text-foreground-secondary">
                              Phone reported: {a.client_error.replaceAll("_", " ").toLowerCase()}
                            </span>
                          ) : null}
                        </TableCell>
                        <TableCell>
                          {formatMetres(a.distance_m)} / {formatMetres(a.radius_m)}
                        </TableCell>
                        <TableCell>{formatMetres(a.accuracy_m)}</TableCell>
                        <TableCell>{a.mode}</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </CardContent>
            </Card>
          )}
        </section>
      ) : null}

      {!canConfigure && !canReview ? (
        <EmptyState
          title="No access"
          description="You need the attendance policy or attendance view-all permission to manage workplace geofences."
        />
      ) : null}
    </div>
  );
}
