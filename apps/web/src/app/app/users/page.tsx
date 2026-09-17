"use client";

import { useCallback, useEffect, useState } from "react";

import { EmptyState } from "@/components/common/empty-state";
import { ErrorState } from "@/components/common/error-state";
import { FormField } from "@/components/common/form-field";
import { LoadingState } from "@/components/common/loading-state";
import { PageHeader } from "@/components/common/page-header";
import { useToast } from "@/components/common/toast";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/native-select";
import { apiClient } from "@/lib/api/client";
import { ApiError, describeApiError } from "@/lib/api/errors";
import { usePermissions } from "@/lib/auth/use-permissions";

interface UserSummary {
  user_id: string;
  email: string | null;
  first_name: string | null;
  last_name: string | null;
  is_primary: boolean;
  status: string;
  role_codes: string[];
}

const ASSIGNABLE_ROLES = [
  "COMPANY_ADMIN",
  "HR_ADMIN",
  "REPORTING_MANAGER",
  "BRANCH_MANAGER",
  "EMPLOYEE",
] as const;

function userName(user: UserSummary): string {
  return [user.first_name, user.last_name].filter(Boolean).join(" ") || user.email || "—";
}

export default function UsersPage() {
  const { toast } = useToast();
  const { can } = usePermissions();
  const canManageRoles = can("SETTINGS.ROLE.MANAGE");
  const canManageUsers = can("SETTINGS.USER.MANAGE");

  const [users, setUsers] = useState<UserSummary[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<ApiError | null>(null);

  const [roleDialogUser, setRoleDialogUser] = useState<UserSummary | null>(null);
  const [roleSelection, setRoleSelection] = useState<Set<string>>(new Set());
  const [savingRoles, setSavingRoles] = useState(false);

  const [inviteOpen, setInviteOpen] = useState(false);
  const [inviteEmail, setInviteEmail] = useState("");
  const [inviteRole, setInviteRole] = useState<string>("EMPLOYEE");
  const [inviteError, setInviteError] = useState<string | null>(null);
  const [inviting, setInviting] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await apiClient.get<UserSummary[]>("/users");
      setUsers(data);
    } catch (err) {
      setUsers(null);
      setError(
        err instanceof ApiError
          ? err
          : new ApiError({ status: 0, code: "UNKNOWN_ERROR", message: "Something went wrong." }),
      );
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  function openRoleDialog(user: UserSummary) {
    setRoleDialogUser(user);
    setRoleSelection(new Set(user.role_codes));
  }

  async function handleSaveRoles() {
    if (!roleDialogUser) return;
    setSavingRoles(true);
    try {
      await apiClient.patch(`/users/${roleDialogUser.user_id}/roles`, {
        role_codes: Array.from(roleSelection),
      });
      toast({ title: "Roles updated", variant: "success" });
      setRoleDialogUser(null);
      void load();
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        toast({ title: err.message, variant: "danger" });
        return;
      }
      toast({ title: "Could not update roles", description: describeApiError(err), variant: "danger" });
    } finally {
      setSavingRoles(false);
    }
  }

  async function handleInvite() {
    setInviteError(null);
    if (!inviteEmail.trim()) {
      setInviteError("Enter an email address.");
      return;
    }
    setInviting(true);
    try {
      const result = await apiClient.post<{ email: string; email_sent: boolean }>("/users/invite", {
        email: inviteEmail.trim(),
        role_code: inviteRole,
      });
      toast({
        title: `Invite sent to ${result.email}`,
        description: result.email_sent ? undefined : "Created, but the email could not be delivered.",
        variant: "success",
      });
      setInviteOpen(false);
      setInviteEmail("");
      setInviteRole("EMPLOYEE");
    } catch (err) {
      if (err instanceof ApiError && (err.status === 422 || err.status === 409)) {
        setInviteError(err.message);
        return;
      }
      toast({ title: "Could not send invite", description: describeApiError(err), variant: "danger" });
    } finally {
      setInviting(false);
    }
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Users"
        description="Everyone with a login to this company, and the roles they hold."
        actions={
          canManageUsers ? (
            <Button type="button" onClick={() => setInviteOpen(true)}>
              Invite user
            </Button>
          ) : null
        }
      />

      {loading ? (
        <Card>
          <CardContent className="pt-6">
            <LoadingState label="Loading users…" />
          </CardContent>
        </Card>
      ) : null}

      {error && !loading ? (
        <Card>
          <CardContent className="pt-6">
            <ErrorState message={error.message} onRetry={() => void load()} />
          </CardContent>
        </Card>
      ) : null}

      {!loading && !error && users && users.length === 0 ? (
        <EmptyState title="No users yet" description="Invite someone to get started." />
      ) : null}

      {!loading && !error && users && users.length > 0 ? (
        <Card>
          <CardContent className="divide-y divide-border p-0">
            {users.map((user) => (
              <div key={user.user_id} className="flex items-center justify-between gap-4 px-4 py-3">
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <p className="truncate text-sm font-medium text-foreground">{userName(user)}</p>
                    {user.is_primary ? <Badge variant="secondary">Primary</Badge> : null}
                  </div>
                  <p className="truncate text-sm text-foreground-secondary">{user.email ?? "—"}</p>
                  <div className="mt-1 flex flex-wrap gap-1">
                    {user.role_codes.length === 0 ? (
                      <Badge variant="outline">No roles</Badge>
                    ) : (
                      user.role_codes.map((code) => (
                        <Badge key={code} variant="secondary">
                          {code}
                        </Badge>
                      ))
                    )}
                  </div>
                </div>
                {canManageRoles ? (
                  <Button type="button" variant="outline" onClick={() => openRoleDialog(user)}>
                    Manage roles
                  </Button>
                ) : null}
              </div>
            ))}
          </CardContent>
        </Card>
      ) : null}

      <Dialog open={roleDialogUser !== null} onOpenChange={(open) => (!savingRoles && !open ? setRoleDialogUser(null) : null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Manage roles — {roleDialogUser ? userName(roleDialogUser) : ""}</DialogTitle>
          </DialogHeader>
          <div className="space-y-2">
            {ASSIGNABLE_ROLES.map((code) => (
              <label key={code} className="flex items-center gap-2 text-sm text-foreground">
                <input
                  type="checkbox"
                  className="h-4 w-4 rounded border-border"
                  checked={roleSelection.has(code)}
                  onChange={(e) => {
                    setRoleSelection((current) => {
                      const next = new Set(current);
                      if (e.target.checked) next.add(code);
                      else next.delete(code);
                      return next;
                    });
                  }}
                />
                {code}
              </label>
            ))}
          </div>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => setRoleDialogUser(null)} disabled={savingRoles}>
              Cancel
            </Button>
            <Button type="button" onClick={() => void handleSaveRoles()} disabled={savingRoles}>
              {savingRoles ? "Saving…" : "Save"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={inviteOpen} onOpenChange={(open) => (!inviting ? setInviteOpen(open) : null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Invite a user</DialogTitle>
          </DialogHeader>
          <div className="space-y-4">
            {inviteError ? (
              <div role="alert" className="rounded-md border border-danger/30 bg-danger-subtle px-3 py-2 text-sm text-danger">
                {inviteError}
              </div>
            ) : null}
            <FormField id="inviteEmail" label="Email" required>
              <Input
                type="email"
                value={inviteEmail}
                onChange={(e) => setInviteEmail(e.target.value)}
                disabled={inviting}
              />
            </FormField>
            <FormField id="inviteRole" label="Role" required>
              <NativeSelect value={inviteRole} onChange={(e) => setInviteRole(e.target.value)} disabled={inviting}>
                {ASSIGNABLE_ROLES.map((code) => (
                  <option key={code} value={code}>
                    {code}
                  </option>
                ))}
              </NativeSelect>
            </FormField>
          </div>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => setInviteOpen(false)} disabled={inviting}>
              Cancel
            </Button>
            <Button type="button" onClick={() => void handleInvite()} disabled={inviting}>
              {inviting ? "Sending…" : "Send invite"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
