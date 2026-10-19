"use client";

import { useParams } from "next/navigation";
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ApiError, describeApiError, getFieldError } from "@/lib/api/errors";
import { platformApi, type CompanyDetail, type CompanyStatus } from "@/lib/platform/api";

import { StatusBadge } from "../../status-badge";

type Action = "approve" | "reject" | "suspend" | "reactivate" | "terminate";

const ALLOWED: Record<CompanyStatus, Action[]> = {
  PENDING_APPROVAL: ["approve", "reject", "terminate"],
  REJECTED: ["approve", "terminate"],
  TRIAL: ["suspend", "terminate"],
  ACTIVE: ["suspend", "terminate"],
  SUSPENDED: ["reactivate", "terminate"],
  TERMINATED: [],
};

const COPY: Record<Action, { label: string; help: string; reasonRequired: boolean; destructive?: boolean }> = {
  approve: { label: "Approve", help: "Starts the trial and gives the company full access.", reasonRequired: false },
  reject: { label: "Reject", help: "The company is told why and can no longer sign in.", reasonRequired: true, destructive: true },
  suspend: { label: "Suspend", help: "Read-only grace mode: users can sign in and view data, but cannot change anything.", reasonRequired: true, destructive: true },
  reactivate: { label: "Reactivate", help: "Restores full access.", reasonRequired: false },
  terminate: { label: "Terminate", help: "Closes the company. Nobody can sign in; data is kept for the retention period.", reasonRequired: true, destructive: true },
};

export default function CompanyDetailPage() {
  const { id } = useParams<{ id: string }>();
  const [company, setCompany] = useState<CompanyDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [action, setAction] = useState<Action | null>(null);
  const [reason, setReason] = useState("");
  const [confirmName, setConfirmName] = useState("");
  const [busy, setBusy] = useState(false);
  const [dialogError, setDialogError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    platformApi
      .getCompany(id)
      .then((c) => {
        if (!cancelled) {
          setCompany(c);
          setError(null);
        }
      })
      .catch((e) => {
        if (!cancelled) setError(describeApiError(e));
      });
    return () => {
      cancelled = true;
    };
  }, [id]);

  function openDialog(next: Action) {
    setAction(next);
    setReason("");
    setConfirmName("");
    setDialogError(null);
  }

  async function submit() {
    if (!action) return;
    setBusy(true);
    setDialogError(null);
    try {
      const body: Record<string, unknown> = {};
      if (reason.trim()) body.reason = reason.trim();
      if (action === "terminate") body.confirm_name = confirmName;
      setCompany(await platformApi.act(id, action, body));
      setAction(null);
    } catch (e) {
      const detail = e instanceof ApiError ? getFieldError(e.details, "reason") ?? getFieldError(e.details, "confirm_name") : undefined;
      setDialogError(detail ?? describeApiError(e));
    } finally {
      setBusy(false);
    }
  }

  async function run(fn: () => Promise<CompanyDetail>) {
    try {
      setCompany(await fn());
      setError(null);
    } catch (e) {
      setError(describeApiError(e));
    }
  }

  if (error && !company) return <p role="alert" className="text-sm text-danger">{error}</p>;
  if (!company) return null;

  const copy = action ? COPY[action] : null;
  const canSubmit =
    !busy &&
    (!copy?.reasonRequired || reason.trim().length >= 3) &&
    (action !== "terminate" || confirmName === company.name);

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <h1 className="text-xl font-semibold">{company.name}</h1>
          <StatusBadge status={company.status} />
        </div>
        <div className="flex gap-2">
          {ALLOWED[company.status].map((a) => (
            <Button key={a} variant={COPY[a].destructive ? "destructive" : "default"} size="sm" onClick={() => openDialog(a)}>
              {COPY[a].label}
            </Button>
          ))}
        </div>
      </div>

      {error ? <p role="alert" className="text-sm text-danger">{error}</p> : null}

      <div className="grid gap-4 md:grid-cols-2">
        <Card>
          <CardHeader><CardTitle className="text-base">Company</CardTitle></CardHeader>
          <CardContent className="space-y-1 text-sm">
            <Row k="Registered" v={new Date(company.created_at).toLocaleString()} />
            <Row k="Industry" v={company.industry_code ?? "—"} />
            <Row k="Size" v={company.company_size ?? "—"} />
            <Row k="Country / timezone" v={`${company.country_code} · ${company.timezone}`} />
            <Row k="Employees" v={String(company.usage.employees)} />
            <Row k="Active users" v={String(company.usage.active_users)} />
          </CardContent>
        </Card>

        <Card>
          <CardHeader><CardTitle className="text-base">Admin contact</CardTitle></CardHeader>
          <CardContent className="space-y-1 text-sm">
            <Row k="Name" v={company.admin_name ?? "—"} />
            <Row k="Email" v={company.admin_email ?? "—"} />
            <Row k="Locked out" v={company.admin_locked ? "Yes" : "No"} />
            {company.admin_locked ? (
              <Button size="sm" variant="outline" className="mt-2" onClick={() => run(() => platformApi.unlockAdmin(id))}>
                Unlock admin
              </Button>
            ) : null}
          </CardContent>
        </Card>

        <Card>
          <CardHeader><CardTitle className="text-base">Status</CardTitle></CardHeader>
          <CardContent className="space-y-1 text-sm">
            <Row k="Reason" v={company.status_reason ?? "—"} />
            <Row k="Changed" v={company.status_changed_at ? new Date(company.status_changed_at).toLocaleString() : "—"} />
            <Row k="Approved" v={company.approved_at ? new Date(company.approved_at).toLocaleString() : "—"} />
            <Row k="Data retained until" v={company.retention_until ? new Date(company.retention_until).toLocaleDateString() : "—"} />
          </CardContent>
        </Card>

        <Card>
          <CardHeader><CardTitle className="text-base">Subscription</CardTitle></CardHeader>
          <CardContent className="space-y-1 text-sm">
            {company.subscription ? (
              <>
                <Row k="Plan" v={`${company.subscription.plan_name} (${company.subscription.plan_code})`} />
                <Row k="Status" v={company.subscription.status} />
                <Row k="Trial ends" v={company.subscription.trial_ends_at ? new Date(company.subscription.trial_ends_at).toLocaleDateString() : "—"} />
                <Row k="Seat limit override" v={company.subscription.seat_limit_override?.toString() ?? "—"} />
                <div className="flex gap-2 pt-2">
                  {[7, 14, 30].map((d) => (
                    <Button key={d} size="sm" variant="outline" onClick={() => run(() => platformApi.patchSubscription(id, { extend_trial_days: d }))}>
                      +{d} days
                    </Button>
                  ))}
                </div>
              </>
            ) : (
              <p className="text-foreground-muted">No subscription.</p>
            )}
          </CardContent>
        </Card>
      </div>

      <Dialog open={action !== null} onOpenChange={(open) => !open && setAction(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{copy?.label} {company.name}</DialogTitle>
            <DialogDescription>{copy?.help}</DialogDescription>
          </DialogHeader>
          <div className="space-y-3">
            <div className="space-y-1.5">
              <Label htmlFor="reason">Reason{copy?.reasonRequired ? "" : " (optional)"}</Label>
              <Input id="reason" value={reason} maxLength={500} onChange={(e) => setReason(e.target.value)} />
              {copy?.reasonRequired ? <p className="text-xs text-foreground-muted">Shown to the company admin and kept in the audit log.</p> : null}
            </div>
            {action === "terminate" ? (
              <div className="space-y-1.5">
                <Label htmlFor="confirm">Type the company name to confirm</Label>
                <Input id="confirm" value={confirmName} onChange={(e) => setConfirmName(e.target.value)} />
              </div>
            ) : null}
            {dialogError ? <p role="alert" className="text-sm text-danger">{dialogError}</p> : null}
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setAction(null)}>Cancel</Button>
            <Button variant={copy?.destructive ? "destructive" : "default"} disabled={!canSubmit} onClick={submit}>
              {busy ? "Working…" : copy?.label}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

function Row({ k, v }: { k: string; v: string }) {
  return (
    <div className="flex justify-between gap-4">
      <span className="text-foreground-muted">{k}</span>
      <span className="text-right">{v}</span>
    </div>
  );
}
