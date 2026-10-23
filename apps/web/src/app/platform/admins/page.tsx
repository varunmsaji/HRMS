"use client";

import { useEffect, useState, type FormEvent } from "react";

import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ApiError, describeApiError, getFieldError } from "@/lib/api/errors";
import { platformApi, type PlatformAdminItem } from "@/lib/platform/api";

export default function PlatformAdminsPage() {
  const [admins, setAdmins] = useState<PlatformAdminItem[]>([]);
  const [reloadKey, setReloadKey] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [createError, setCreateError] = useState<string | null>(null);
  const [resetFor, setResetFor] = useState<string | null>(null);
  const [resetPassword, setResetPassword] = useState("");

  useEffect(() => {
    let cancelled = false;
    platformApi
      .listAdmins()
      .then((a) => {
        if (!cancelled) {
          setAdmins(a);
          setError(null);
        }
      })
      .catch((e) => {
        if (!cancelled) setError(describeApiError(e));
      });
    return () => {
      cancelled = true;
    };
  }, [reloadKey]);

  const reload = () => setReloadKey((k) => k + 1);

  async function create(event: FormEvent) {
    event.preventDefault();
    setCreateError(null);
    setNotice(null);
    try {
      await platformApi.createAdmin(username.trim(), password);
      setUsername("");
      setPassword("");
      setNotice("Platform admin created.");
      reload();
    } catch (e) {
      const detail = e instanceof ApiError ? (getFieldError(e.details, "username") ?? getFieldError(e.details, "password")) : undefined;
      setCreateError(detail ?? describeApiError(e));
    }
  }

  async function run(label: string, fn: () => Promise<unknown>) {
    setNotice(null);
    try {
      await fn();
      setError(null);
      setNotice(label);
      reload();
    } catch (e) {
      setError(describeApiError(e));
    }
  }

  return (
    <div className="space-y-6">
      <h1 className="text-xl font-semibold">Platform admins</h1>
      {error ? <p role="alert" className="text-sm text-danger">{error}</p> : null}
      {notice ? <p role="status" className="text-sm text-success">{notice}</p> : null}

      <Card>
        <CardContent className="p-0">
          <table className="w-full text-sm">
            <thead className="border-b border-border text-left text-foreground-muted">
              <tr>
                <th className="px-4 py-2 font-medium">Username</th>
                <th className="px-4 py-2 font-medium">Status</th>
                <th className="px-4 py-2 font-medium">Last sign-in</th>
                <th className="px-4 py-2 font-medium text-right">Actions</th>
              </tr>
            </thead>
            <tbody>
              {admins.map((a) => (
                <tr key={a.id} className="border-b border-border last:border-0 align-top">
                  <td className="px-4 py-2 font-medium">{a.username}{a.is_you ? <span className="ml-2 text-xs text-foreground-muted">(you)</span> : null}</td>
                  <td className="px-4 py-2">
                    <Badge variant={a.status === "ACTIVE" ? "success" : "secondary"}>{a.status}</Badge>
                    {a.locked ? <Badge variant="warning" className="ml-1">LOCKED</Badge> : null}
                  </td>
                  <td className="px-4 py-2">{a.last_login_at ? new Date(a.last_login_at).toLocaleString() : "Never"}</td>
                  <td className="px-4 py-2">
                    <div className="flex flex-wrap justify-end gap-2">
                      <Button size="sm" variant="outline" onClick={() => { setResetFor(resetFor === a.id ? null : a.id); setResetPassword(""); }}>Reset password</Button>
                      {a.status === "ACTIVE" ? (
                        <Button size="sm" variant="destructive" disabled={a.is_you} onClick={() => run(`${a.username} disabled and signed out.`, () => platformApi.setAdminStatus(a.id, false))}>Disable</Button>
                      ) : (
                        <Button size="sm" onClick={() => run(`${a.username} enabled.`, () => platformApi.setAdminStatus(a.id, true))}>Enable</Button>
                      )}
                    </div>
                    {resetFor === a.id ? (
                      <form className="mt-2 flex justify-end gap-2" onSubmit={(e) => { e.preventDefault(); void run(`Password reset for ${a.username}.`, async () => { await platformApi.resetAdminPassword(a.id, resetPassword); setResetFor(null); setResetPassword(""); }); }}>
                        <Input type="password" autoComplete="new-password" placeholder="New password" className="w-56" value={resetPassword} onChange={(e) => setResetPassword(e.target.value)} aria-label={`New password for ${a.username}`} />
                        <Button size="sm" type="submit" disabled={!resetPassword}>Set</Button>
                      </form>
                    ) : null}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </CardContent>
      </Card>

      <Card className="max-w-lg">
        <CardHeader><CardTitle className="text-base">Add a platform admin</CardTitle></CardHeader>
        <CardContent>
          <form onSubmit={create} className="space-y-3" noValidate>
            <div className="space-y-1.5">
              <Label htmlFor="new-username">Username</Label>
              <Input id="new-username" autoComplete="off" value={username} onChange={(e) => setUsername(e.target.value)} />
              <p className="text-xs text-foreground-muted">3–64 characters: letters, digits, dot, dash, underscore.</p>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="new-password">Password</Label>
              <Input id="new-password" type="password" autoComplete="new-password" value={password} onChange={(e) => setPassword(e.target.value)} />
              <p className="text-xs text-foreground-muted">At least 8 characters with a letter and a digit; common passwords are rejected.</p>
            </div>
            {createError ? <p role="alert" className="text-sm text-danger">{createError}</p> : null}
            <Button type="submit" disabled={!username || !password}>Create admin</Button>
          </form>
        </CardContent>
      </Card>
    </div>
  );
}
