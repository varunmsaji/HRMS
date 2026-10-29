"use client";

import { UserPlus } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { EmployeeIdentityCell } from "@/components/employee/employee-identity";
import { EmptyState } from "@/components/common/empty-state";
import { ErrorState } from "@/components/common/error-state";
import { FormField } from "@/components/common/form-field";
import { LoadingState } from "@/components/common/loading-state";
import { PageHeader } from "@/components/common/page-header";
import { PaginationControls } from "@/components/common/pagination-controls";
import { useToast } from "@/components/common/toast";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/native-select";
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
import { ApiError, describeApiError } from "@/lib/api/errors";
import type { PaginationMeta } from "@/lib/api/types";
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
  const [pagination, setPagination] = useState<PaginationMeta | null>(null);
  const [page, setPage] = useState(1);
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

  const load = useCallback(async (targetPage: number) => {
    setLoading(true);
    setError(null);
    try {
      const { data, pagination: meta } = await apiClient.getList<UserSummary>("/users", {
        page: targetPage,
      });
      setUsers(data);
      setPagination(meta);
    } catch (err) {
      setUsers(null);
      setPagination(null);
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
    void load(page);
  }, [load, page]);

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
      void load(page);
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        toast({ title: err.message, variant: "danger" });
        return;
      }
      toast({
        title: "Could not update roles",
        description: describeApiError(err),
        variant: "danger",
      });
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
      const result = await apiClient.post<{ email: string; email_sent: boolean }>(
        "/users/invite",
        {
          email: inviteEmail.trim(),
          role_code: inviteRole,
        },
      );
      toast({
        title: `Invite sent to ${result.email}`,
        description: result.email_sent
          ? undefined
          : "Created, but the email could not be delivered.",
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
      toast({
        title: "Could not send invite",
        description: describeApiError(err),
        variant: "danger",
      });
    } finally {
      setInviting(false);
    }
  }

  return (
    <div className="space-y-6">
      <PageHeader
        backHref="/app/settings"
        backLabel="Settings"
        title="Users"
        description="Everyone with a login to this company, and the roles they hold."
        actions={
          canManageUsers ? (
            <Button type="button" onClick={() => setInviteOpen(true)}>
              <UserPlus className="h-4 w-4" aria-hidden="true" />
              Invite user
            </Button>
          ) : null
        }
      />

      <TableContainer>
        {loading ? <LoadingState label="Loading users…" /> : null}

        {error && !loading ? (
          <div className="p-6">
            <ErrorState message={error.message} onRetry={() => void load(page)} />
          </div>
        ) : null}

        {!loading && !error && users && users.length === 0 ? (
          <div className="p-6">
            <EmptyState title="No users yet" description="Invite someone to get started." />
          </div>
        ) : null}

        {!loading && !error && users && users.length > 0 ? (
          <Table>
            <TableHeader>
              <TableRow className="hover:bg-transparent">
                <TableHead>User</TableHead>
                <TableHead>Email</TableHead>
                <TableHead>Roles</TableHead>
                {canManageRoles ? <TableHead align="right">Actions</TableHead> : null}
              </TableRow>
            </TableHeader>
            <TableBody>
              {users.map((user) => (
                <TableRow key={user.user_id}>
                  <TableCell>
                    <div className="flex items-center gap-2">
                      <EmployeeIdentityCell name={userName(user)} size="sm" />
                      {user.is_primary ? <Badge variant="secondary">Primary</Badge> : null}
                    </div>
                  </TableCell>
                  <TableCell className="text-foreground-secondary">{user.email ?? "—"}</TableCell>
                  <TableCell>
                    <div className="flex flex-wrap gap-1">
                      {user.role_codes.length === 0 ? (
                        <Badge variant="outline">No roles</Badge>
                      ) : (
                        user.role_codes.map((code) => (
                          <Badge key={code} variant="secondary" className="font-mono text-2xs">
                            {code}
                          </Badge>
                        ))
                      )}
                    </div>
                  </TableCell>
                  {canManageRoles ? (
                    <TableCell align="right">
                      <Button
                        type="button"
                        variant="outline"
                        size="xs"
                        onClick={() => openRoleDialog(user)}
                      >
                        Manage roles
                      </Button>
                    </TableCell>
                  ) : null}
                </TableRow>
              ))}
            </TableBody>
          </Table>
        ) : null}

        {pagination ? (
          <PaginationControls
            pagination={pagination}
            onPageChange={setPage}
            disabled={loading}
          />
        ) : null}
      </TableContainer>

      <Dialog
        open={roleDialogUser !== null}
        onOpenChange={(open) => (!savingRoles && !open ? setRoleDialogUser(null) : null)}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>
              Manage roles — {roleDialogUser ? userName(roleDialogUser) : ""}
            </DialogTitle>
          </DialogHeader>
          <div className="space-y-2">
            {ASSIGNABLE_ROLES.map((code) => (
              <label key={code} className="flex items-center gap-2 text-sm text-foreground">
                <Checkbox
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
            <Button
              type="button"
              variant="outline"
              onClick={() => setRoleDialogUser(null)}
              disabled={savingRoles}
            >
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
              <div
                role="alert"
                className="rounded-md border border-danger-border bg-danger-subtle px-3 py-2 text-sm text-danger"
              >
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
              <NativeSelect
                value={inviteRole}
                onChange={(e) => setInviteRole(e.target.value)}
                disabled={inviting}
              >
                {ASSIGNABLE_ROLES.map((code) => (
                  <option key={code} value={code}>
                    {code}
                  </option>
                ))}
              </NativeSelect>
            </FormField>
          </div>
          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => setInviteOpen(false)}
              disabled={inviting}
            >
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
