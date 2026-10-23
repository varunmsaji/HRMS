"use client";

import { useParams } from "next/navigation";
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/native-select";
import { describeApiError } from "@/lib/api/errors";
import {
  platformApi,
  type AuditEntry,
  type CompanyDetail,
  type CompanyStatus,
  type PlanItem,
} from "@/lib/platform/api";

import { ACTION_COPY, ActionDialog, type DialogAction } from "../../action-dialog";
import { StatusBadge } from "../../status-badge";

const ALLOWED: Record<CompanyStatus, DialogAction[]> = {
  PENDING_APPROVAL: ["approve", "reject", "terminate"],
  REJECTED: ["approve", "terminate"],
  TRIAL: ["suspend", "terminate"],
  ACTIVE: ["suspend", "terminate"],
  SUSPENDED: ["reactivate", "terminate"],
  TERMINATED: [],
};

export default function CompanyDetailPage() {
  const { id } = useParams<{ id: string }>();
  const [company, setCompany] = useState<CompanyDetail | null>(null);
  const [history, setHistory] = useState<AuditEntry[]>([]);
  const [plans, setPlans] = useState<PlanItem[]>([]);
  const [reloadKey, setReloadKey] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [action, setAction] = useState<DialogAction | null>(null);
  const [planCode, setPlanCode] = useState("");
  const [seats, setSeats] = useState("");

  useEffect(() => {
    let cancelled = false;
    Promise.all([platformApi.getCompany(id), platformApi.auditLog({ company_id: id }), platformApi.plans()])
      .then(([c, audit, p]) => {
        if (cancelled) return;
        setCompany(c);
        setHistory(audit.items);
        setPlans(p);
        setPlanCode(c.subscription?.plan_code ?? "");
        setSeats(c.subscription?.seat_limit_override?.toString() ?? "");
        setError(null);
      })
      .catch((e) => {
        if (!cancelled) setError(describeApiError(e));
      });
    return () => {
      cancelled = true;
    };
  }, [id, reloadKey]);

  const reload = () => setReloadKey((k) => k + 1);

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

  if (error && !company) return <p role="alert" className="text-sm text-danger">{error}</p>;
  if (!company) return <p className="text-sm text-foreground-muted">Loading…</p>;

  const sub = company.subscription;
  const seatsValue = seats.trim() === "" ? null : Number(seats);
  const seatsInvalid = seatsValue !== null && (!Number.isInteger(seatsValue) || seatsValue < 1);
  const planDirty = sub !== null && planCode !== sub.plan_code;
  const seatsDirty = sub !== null && seatsValue !== sub.seat_limit_override;

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <h1 className="text-xl font-semibold">{company.name}</h1>
          <StatusBadge status={company.status} />
        </div>
        <div className="flex gap-2">
          {ALLOWED[company.status].map((a) => (
            <Button key={a} variant={ACTION_COPY[a].destructive ? "destructive" : "default"} size="sm" onClick={() => setAction(a)}>
              {ACTION_COPY[a].label}
            </Button>
          ))}
        </div>
      </div>

      {error ? <p role="alert" className="text-sm text-danger">{error}</p> : null}
      {notice ? <p role="status" className="text-sm text-success">{notice}</p> : null}

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
            <div className="flex flex-wrap gap-2 pt-2">
              {company.admin_locked ? (
                <Button size="sm" variant="outline" onClick={() => run("Admin unlocked.", () => platformApi.unlockAdmin(id))}>Unlock admin</Button>
              ) : null}
              <Button size="sm" variant="outline" onClick={() => run("Verification email sent (if the address is still unverified).", () => platformApi.resendVerification(id))}>
                Resend verification email
              </Button>
            </div>
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
          <CardContent className="space-y-3 text-sm">
            {sub ? (
              <>
                <Row k="Status" v={sub.status} />
                <Row k="Trial ends" v={sub.trial_ends_at ? new Date(sub.trial_ends_at).toLocaleDateString() : "—"} />
                <div className="flex items-center gap-2">
                  <NativeSelect className="flex-1" value={planCode} onChange={(e) => setPlanCode(e.target.value)} aria-label="Plan">
                    {plans.map((p) => (<option key={p.code} value={p.code}>{p.name} ({p.code})</option>))}
                  </NativeSelect>
                  <Button size="sm" disabled={!planDirty} onClick={() => run("Plan changed.", () => platformApi.patchSubscription(id, { plan_code: planCode }))}>Change plan</Button>
                </div>
                <div className="flex items-center gap-2">
                  <Input className="flex-1" inputMode="numeric" placeholder="Seat limit override (blank = plan default)" value={seats} onChange={(e) => setSeats(e.target.value)} aria-label="Seat limit override" />
                  <Button size="sm" disabled={!seatsDirty || seatsInvalid} onClick={() => run("Seat limit updated.", () => platformApi.patchSubscription(id, { seat_limit_override: seatsValue }))}>Save</Button>
                </div>
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-foreground-muted">Extend trial:</span>
                  {[7, 14, 30].map((d) => (
                    <Button key={d} size="sm" variant="outline" onClick={() => run(`Trial extended by ${d} days.`, () => platformApi.patchSubscription(id, { extend_trial_days: d }))}>+{d} days</Button>
                  ))}
                </div>
              </>
            ) : (
              <p className="text-foreground-muted">No subscription.</p>
            )}
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader><CardTitle className="text-base">History</CardTitle></CardHeader>
        <CardContent className="p-0">
          {history.length === 0 ? (
            <p className="px-4 py-6 text-center text-sm text-foreground-muted">No platform actions yet.</p>
          ) : (
            <ul className="text-sm">
              {history.map((e) => (
                <li key={e.id} className="flex flex-wrap justify-between gap-2 border-t border-border px-4 py-2 first:border-t-0">
                  <span><span className="font-medium">{e.actor_username ?? "system"}</span> · {e.action.replaceAll("_", " ").toLowerCase()}{e.before_status && e.after_status ? ` (${e.before_status} → ${e.after_status})` : ""}{e.reason ? ` — ${e.reason}` : ""}</span>
                  <span className="text-foreground-muted">{new Date(e.created_at).toLocaleString()}</span>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>

      {action ? (
        <ActionDialog company={company} action={action} onClose={() => setAction(null)} onDone={() => { setAction(null); reload(); }} />
      ) : null}
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
