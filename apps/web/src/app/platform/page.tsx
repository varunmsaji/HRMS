"use client";

import { AlertTriangle, Building2, Clock, Lock, ShieldCheck, UserPlus } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useState, type ReactNode } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { describeApiError } from "@/lib/api/errors";
import { platformApi, type CompanyListItem, type Dashboard } from "@/lib/platform/api";

import { ActionDialog, type DialogAction } from "./action-dialog";
import { StatusBadge } from "./status-badge";

const STATUS_ORDER = ["PENDING_APPROVAL", "TRIAL", "ACTIVE", "SUSPENDED", "REJECTED", "TERMINATED"];
const BAR_COLOR: Record<string, string> = {
  PENDING_APPROVAL: "bg-warning",
  TRIAL: "bg-info",
  ACTIVE: "bg-success",
  SUSPENDED: "bg-warning",
  REJECTED: "bg-danger",
  TERMINATED: "bg-foreground-muted",
};

function ago(iso: string | null): string {
  if (!iso) return "—";
  const hours = Math.floor((Date.now() - new Date(iso).getTime()) / 3_600_000);
  if (hours < 1) return "just now";
  if (hours < 48) return `${hours}h ago`;
  return `${Math.floor(hours / 24)}d ago`;
}

function daysUntil(iso: string | null): string {
  if (!iso) return "—";
  const days = Math.ceil((new Date(iso).getTime() - Date.now()) / 86_400_000);
  return days <= 0 ? "today" : `in ${days}d`;
}

export default function PlatformDashboardPage() {
  const [dash, setDash] = useState<Dashboard | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);
  const [dialog, setDialog] = useState<{ company: CompanyListItem; action: DialogAction } | null>(null);

  useEffect(() => {
    let cancelled = false;
    platformApi
      .dashboard()
      .then((d) => {
        if (!cancelled) {
          setDash(d);
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

  const refresh = useCallback(() => setReloadKey((k) => k + 1), []);

  if (error && !dash) return <p role="alert" className="text-sm text-danger">{error}</p>;
  if (!dash) return <p className="text-sm text-foreground-muted">Loading…</p>;

  const max = Math.max(1, ...dash.registrations_last_30_days.map((d) => d.count));
  const totalForBars = Math.max(1, dash.total_companies);

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-xl font-semibold">Platform dashboard</h1>
        <Button variant="outline" size="sm" onClick={refresh}>Refresh</Button>
      </div>
      {error ? <p role="alert" className="text-sm text-danger">{error}</p> : null}

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4 xl:grid-cols-6">
        <Kpi icon={<Building2 className="h-4 w-4" />} label="Companies" value={dash.total_companies} href="/platform/companies" />
        <Kpi icon={<Clock className="h-4 w-4" />} label="Awaiting approval" value={dash.pending_count} href="/platform/companies?status=PENDING_APPROVAL" highlight={dash.pending_count > 0} note={dash.oldest_pending_since ? `oldest ${ago(dash.oldest_pending_since)}` : undefined} />
        <Kpi icon={<ShieldCheck className="h-4 w-4" />} label="Active / trial" value={(dash.counts_by_status.ACTIVE ?? 0) + (dash.counts_by_status.TRIAL ?? 0)} href="/platform/companies" />
        <Kpi icon={<AlertTriangle className="h-4 w-4" />} label="Trials ending ≤ 7d" value={dash.trials_expiring_within_7_days} highlight={dash.trials_expiring_within_7_days > 0} />
        <Kpi icon={<UserPlus className="h-4 w-4" />} label="New in 30 days" value={dash.registrations_total_30_days} />
        <Kpi icon={<Lock className="h-4 w-4" />} label="Locked company admins" value={dash.locked_company_admins} highlight={dash.locked_company_admins > 0} href="/platform/companies" />
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <CardHeader><CardTitle className="text-base">Registrations — last 30 days</CardTitle></CardHeader>
          <CardContent>
            <div className="flex h-32 items-end gap-1" role="img" aria-label={`${dash.registrations_total_30_days} registrations in the last 30 days`}>
              {dash.registrations_last_30_days.map((d) => (
                <div key={d.day} className="flex h-full flex-1 items-end" title={`${d.day}: ${d.count}`}>
                  <div className="w-full rounded-sm bg-primary" style={{ height: `${(d.count / max) * 100}%`, minHeight: d.count ? 4 : 1 }} />
                </div>
              ))}
            </div>
            <div className="mt-1 flex justify-between text-[11px] text-foreground-muted">
              <span>{dash.registrations_last_30_days[0]?.day}</span>
              <span>{dash.registrations_last_30_days.at(-1)?.day}</span>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader><CardTitle className="text-base">Companies by status</CardTitle></CardHeader>
          <CardContent className="space-y-2">
            {STATUS_ORDER.map((s) => {
              const n = dash.counts_by_status[s] ?? 0;
              return (
                <Link key={s} href={`/platform/companies?status=${s}`} className="block text-sm hover:opacity-80">
                  <div className="flex justify-between"><span>{s.replace("_", " ")}</span><span className="font-medium">{n}</span></div>
                  <div className="mt-1 h-1.5 rounded bg-border"><div className={`h-1.5 rounded ${BAR_COLOR[s]}`} style={{ width: `${(n / totalForBars) * 100}%` }} /></div>
                </Link>
              );
            })}
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader className="flex-row items-center justify-between space-y-0">
          <CardTitle className="text-base">Awaiting approval {dash.pending_count > dash.pending.length ? `(showing oldest ${dash.pending.length} of ${dash.pending_count})` : ""}</CardTitle>
          {dash.pending_count > 0 ? <Link href="/platform/companies?status=PENDING_APPROVAL" className="text-sm text-primary hover:underline">View all</Link> : null}
        </CardHeader>
        <CardContent className="p-0">
          {dash.pending.length === 0 ? <Empty text="Nothing is waiting for approval." /> : (
            <ul>
              {dash.pending.map((c) => (
                <li key={c.id} className="flex flex-wrap items-center justify-between gap-3 border-t border-border px-4 py-3 first:border-t-0">
                  <div>
                    <Link href={`/platform/companies/${c.id}`} className="font-medium text-primary hover:underline">{c.name}</Link>
                    <div className="text-xs text-foreground-muted">{c.admin_name ?? "—"} · {c.admin_email} · registered {ago(c.created_at)}{c.company_size ? ` · ${c.company_size} staff` : ""}</div>
                  </div>
                  <div className="flex gap-2">
                    <Button size="sm" onClick={() => setDialog({ company: c, action: "approve" })}>Approve</Button>
                    <Button size="sm" variant="destructive" onClick={() => setDialog({ company: c, action: "reject" })}>Reject</Button>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>

      <div className="grid gap-4 lg:grid-cols-2">
        <CompanyList title="Trials ending soon" empty="No trials end in the next 7 days." items={dash.trials_expiring} when={(c) => `ends ${daysUntil(c.trial_ends_at)}`} />
        <CompanyList title="Terminated — retention ending (30 days)" empty="No terminated company's retention ends soon." items={dash.retention_due} when={() => "review for purge"} />
      </div>

      <Card>
        <CardHeader className="flex-row items-center justify-between space-y-0">
          <CardTitle className="text-base">Recent activity</CardTitle>
          <Link href="/platform/audit" className="text-sm text-primary hover:underline">Full audit log</Link>
        </CardHeader>
        <CardContent className="p-0">
          {dash.recent_activity.length === 0 ? <Empty text="No activity yet." /> : (
            <ul className="text-sm">
              {dash.recent_activity.map((e) => (
                <li key={e.id} className="flex flex-wrap justify-between gap-2 border-t border-border px-4 py-2 first:border-t-0">
                  <span><span className="font-medium">{e.actor_username ?? "system"}</span> · {e.action.replaceAll("_", " ").toLowerCase()}{e.before_status && e.after_status ? ` (${e.before_status} → ${e.after_status})` : ""}{e.reason ? ` — ${e.reason}` : ""}</span>
                  <span className="text-foreground-muted">{ago(e.created_at)}</span>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>

      {dialog ? (
        <ActionDialog
          company={dialog.company}
          action={dialog.action}
          onClose={() => setDialog(null)}
          onDone={() => { setDialog(null); refresh(); }}
        />
      ) : null}
    </div>
  );
}

function Kpi({ icon, label, value, href, highlight, note }: { icon: ReactNode; label: string; value: number; href?: string; highlight?: boolean; note?: string }) {
  const body = (
    <Card className={highlight ? "border-warning" : undefined}>
      <CardContent className="p-4">
        <div className="flex items-center gap-1.5 text-xs text-foreground-muted">{icon}{label}</div>
        <div className="mt-1 text-2xl font-semibold">{value}</div>
        {note ? <div className="text-[11px] text-foreground-muted">{note}</div> : null}
      </CardContent>
    </Card>
  );
  return href ? <Link href={href}>{body}</Link> : body;
}

function Empty({ text }: { text: string }) {
  return <p className="px-4 py-6 text-center text-sm text-foreground-muted">{text}</p>;
}

function CompanyList({ title, items, empty, when }: { title: string; items: CompanyListItem[]; empty: string; when: (c: CompanyListItem) => string }) {
  return (
    <Card>
      <CardHeader><CardTitle className="text-base">{title}</CardTitle></CardHeader>
      <CardContent className="p-0">
        {items.length === 0 ? <Empty text={empty} /> : (
          <ul className="text-sm">
            {items.map((c) => (
              <li key={c.id} className="flex items-center justify-between gap-3 border-t border-border px-4 py-2 first:border-t-0">
                <div><Link href={`/platform/companies/${c.id}`} className="font-medium text-primary hover:underline">{c.name}</Link><div className="text-xs text-foreground-muted">{c.admin_email}</div></div>
                <div className="flex items-center gap-2"><StatusBadge status={c.status} /><span className="text-xs text-foreground-muted">{when(c)}</span></div>
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}
