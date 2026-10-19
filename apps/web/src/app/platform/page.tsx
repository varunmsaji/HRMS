"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/native-select";
import { describeApiError } from "@/lib/api/errors";
import {
  platformApi,
  type CompanyListItem,
  type Dashboard,
} from "@/lib/platform/api";
import type { PaginationMeta } from "@/lib/api/types";

import { StatusBadge } from "./status-badge";

const STATUSES = ["PENDING_APPROVAL", "TRIAL", "ACTIVE", "SUSPENDED", "REJECTED", "TERMINATED"];

export default function PlatformHomePage() {
  const [dash, setDash] = useState<Dashboard | null>(null);
  const [items, setItems] = useState<CompanyListItem[]>([]);
  const [pagination, setPagination] = useState<PaginationMeta | null>(null);
  const [status, setStatus] = useState("PENDING_APPROVAL");
  const [q, setQ] = useState("");
  const [page, setPage] = useState(1);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    Promise.all([
      platformApi.dashboard(),
      platformApi.listCompanies({ status: status || undefined, q: q.trim() || undefined, page }),
    ])
      .then(([d, list]) => {
        if (cancelled) return;
        setDash(d);
        setItems(list.items);
        setPagination(list.pagination);
        setError(null);
      })
      .catch((e) => {
        if (!cancelled) setError(describeApiError(e));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [status, q, page]);

  return (
    <div className="space-y-6">
      <h1 className="text-xl font-semibold">Companies</h1>

      {dash ? (
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
          <Stat label="Awaiting approval" value={dash.pending_count} />
          <Stat label="In trial" value={dash.counts_by_status.TRIAL ?? 0} />
          <Stat label="Active" value={dash.counts_by_status.ACTIVE ?? 0} />
          <Stat label="Trials ending ≤ 7 days" value={dash.trials_expiring_within_7_days} />
        </div>
      ) : null}

      <div className="flex flex-wrap gap-3">
        <NativeSelect className="w-52" value={status} onChange={(e) => { setStatus(e.target.value); setPage(1); }} aria-label="Status filter">
          <option value="">All statuses</option>
          {STATUSES.map((s) => (<option key={s} value={s}>{s.replace("_", " ")}</option>))}
        </NativeSelect>
        <Input className="w-64" placeholder="Search company or admin email" value={q} onChange={(e) => { setQ(e.target.value); setPage(1); }} aria-label="Search" />
      </div>

      {error ? <p role="alert" className="text-sm text-danger">{error}</p> : null}

      <Card>
        <CardContent className="p-0">
          <table className="w-full text-sm">
            <thead className="border-b border-border text-left text-foreground-muted">
              <tr>
                <th className="px-4 py-2 font-medium">Company</th>
                <th className="px-4 py-2 font-medium">Admin</th>
                <th className="px-4 py-2 font-medium">Status</th>
                <th className="px-4 py-2 font-medium">Registered</th>
              </tr>
            </thead>
            <tbody>
              {items.map((c) => (
                <tr key={c.id} className="border-b border-border last:border-0 hover:bg-accent/40">
                  <td className="px-4 py-2">
                    <Link href={`/platform/companies/${c.id}`} className="font-medium text-primary hover:underline">{c.name}</Link>
                  </td>
                  <td className="px-4 py-2">{c.admin_name ?? "—"}<div className="text-xs text-foreground-muted">{c.admin_email}</div></td>
                  <td className="px-4 py-2"><StatusBadge status={c.status} /></td>
                  <td className="px-4 py-2">{new Date(c.created_at).toLocaleDateString()}</td>
                </tr>
              ))}
              {!loading && items.length === 0 ? (
                <tr><td colSpan={4} className="px-4 py-8 text-center text-foreground-muted">No companies match.</td></tr>
              ) : null}
            </tbody>
          </table>
        </CardContent>
      </Card>

      {pagination && pagination.total_pages > 1 ? (
        <div className="flex items-center justify-between text-sm">
          <span>Page {pagination.page} of {pagination.total_pages}</span>
          <div className="flex gap-2">
            <Button variant="outline" size="sm" disabled={page <= 1} onClick={() => setPage(page - 1)}>Previous</Button>
            <Button variant="outline" size="sm" disabled={page >= pagination.total_pages} onClick={() => setPage(page + 1)}>Next</Button>
          </div>
        </div>
      ) : null}
    </div>
  );
}

function Stat({ label, value }: { label: string; value: number }) {
  return (
    <Card>
      <CardContent className="p-4">
        <div className="text-2xl font-semibold">{value}</div>
        <div className="text-xs text-foreground-muted">{label}</div>
      </CardContent>
    </Card>
  );
}
