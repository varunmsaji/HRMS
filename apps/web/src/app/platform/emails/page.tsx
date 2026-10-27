"use client";

import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/native-select";
import type { PaginationMeta } from "@/lib/api/types";
import { describeApiError } from "@/lib/api/errors";
import { platformApi, type EmailLogDetail, type EmailLogItem } from "@/lib/platform/api";

const STATUS_LABEL: Record<EmailLogItem["status"], string> = {
  ACCEPTED: "Accepted by provider",
  FAILED: "Failed",
  LOGGED_ONLY: "Not sent (dev log)",
};

export default function PlatformEmailsPage() {
  const [items, setItems] = useState<EmailLogItem[]>([]);
  const [pagination, setPagination] = useState<PaginationMeta | null>(null);
  const [page, setPage] = useState(1);
  const [status, setStatus] = useState("");
  const [search, setSearch] = useState("");
  const [q, setQ] = useState("");
  const [open, setOpen] = useState<EmailLogDetail | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    platformApi
      .emails({ page, status: status || undefined, q: q || undefined })
      .then((r) => { setItems(r.items); setPagination(r.pagination); setError(null); })
      .catch((e) => setError(describeApiError(e)));
  }, [page, status, q]);

  const view = (id: string) =>
    platformApi.email(id).then(setOpen).catch((e) => setError(describeApiError(e)));

  return (
    <div className="space-y-6">
      <h1 className="text-xl font-semibold">Email log</h1>
      <p className="text-sm text-foreground-muted">
        Every email the platform sends. “Accepted” means the mail provider took the message, not that it was delivered.
        Single-use links are masked.
      </p>
      <form
        className="flex flex-wrap gap-2"
        onSubmit={(e) => { e.preventDefault(); setQ(search.trim()); setPage(1); }}
      >
        <Input className="w-72" placeholder="Recipient or subject" value={search} onChange={(e) => setSearch(e.target.value)} aria-label="Search emails" />
        <Button type="submit" variant="outline">Search</Button>
        <NativeSelect className="w-56" value={status} onChange={(e) => { setStatus(e.target.value); setPage(1); }} aria-label="Status filter">
          <option value="">All statuses</option>
          <option value="ACCEPTED">Accepted</option>
          <option value="FAILED">Failed</option>
          <option value="LOGGED_ONLY">Not sent (dev log)</option>
        </NativeSelect>
      </form>
      {error ? <p role="alert" className="text-sm text-danger">{error}</p> : null}
      <Card>
        <CardContent className="overflow-x-auto p-0">
          <table className="w-full text-sm">
            <thead className="border-b border-border text-left text-foreground-muted">
              <tr>
                <th className="px-4 py-2 font-medium">When</th>
                <th className="px-4 py-2 font-medium">To</th>
                <th className="px-4 py-2 font-medium">Subject</th>
                <th className="px-4 py-2 font-medium">Type</th>
                <th className="px-4 py-2 font-medium">Status</th>
                <th className="px-4 py-2" />
              </tr>
            </thead>
            <tbody>
              {items.map((e) => (
                <tr key={e.id} className="border-b border-border last:border-0">
                  <td className="px-4 py-2 whitespace-nowrap">{new Date(e.created_at).toLocaleString()}</td>
                  <td className="px-4 py-2">{e.recipient}</td>
                  <td className="px-4 py-2">{e.subject}</td>
                  <td className="px-4 py-2">{e.kind ?? "—"}</td>
                  <td className="px-4 py-2">
                    {STATUS_LABEL[e.status]}
                    {e.failure_class ? ` (${e.failure_class})` : ""}
                  </td>
                  <td className="px-4 py-2"><Button variant="outline" size="sm" onClick={() => view(e.id)}>View</Button></td>
                </tr>
              ))}
              {items.length === 0 ? (
                <tr><td colSpan={6} className="px-4 py-6 text-center text-foreground-muted">No emails.</td></tr>
              ) : null}
            </tbody>
          </table>
        </CardContent>
      </Card>
      {pagination && pagination.total_pages > 1 ? (
        <div className="flex justify-end gap-2">
          <Button variant="outline" size="sm" disabled={page <= 1} onClick={() => setPage(page - 1)}>Previous</Button>
          <Button variant="outline" size="sm" disabled={page >= pagination.total_pages} onClick={() => setPage(page + 1)}>Next</Button>
        </div>
      ) : null}
      {open ? (
        <Card>
          <CardContent className="space-y-3 p-4 text-sm">
            <div className="flex items-center justify-between">
              <h2 className="font-semibold">{open.subject}</h2>
              <Button variant="outline" size="sm" onClick={() => setOpen(null)}>Close</Button>
            </div>
            <dl className="grid grid-cols-[8rem_1fr] gap-y-1">
              <dt className="text-foreground-muted">To</dt><dd>{open.recipient}</dd>
              <dt className="text-foreground-muted">From</dt><dd>{open.sender ?? "—"}</dd>
              <dt className="text-foreground-muted">Sent</dt><dd>{new Date(open.created_at).toLocaleString()}</dd>
              <dt className="text-foreground-muted">Provider</dt><dd>{open.provider}</dd>
              <dt className="text-foreground-muted">Status</dt><dd>{STATUS_LABEL[open.status]}</dd>
              <dt className="text-foreground-muted">Type</dt><dd>{open.kind ?? "—"}</dd>
              <dt className="text-foreground-muted">Company</dt><dd>{open.company_id ?? "—"}</dd>
              <dt className="text-foreground-muted">Request ID</dt><dd>{open.request_id ?? "—"}</dd>
              <dt className="text-foreground-muted">Duration</dt><dd>{open.duration_ms != null ? `${open.duration_ms} ms` : "—"}</dd>
              {open.status === "FAILED" ? (
                <>
                  <dt className="text-foreground-muted">Failure</dt>
                  <dd>
                    {open.failure_class} · {open.error_type}
                    {open.status_code ? ` · HTTP/SMTP ${open.status_code}` : ""}
                    {open.retryable ? " · retryable" : ""}
                  </dd>
                </>
              ) : null}
            </dl>
            <pre className="max-h-96 overflow-auto whitespace-pre-wrap rounded border border-border bg-surface p-3">{open.text_body}</pre>
          </CardContent>
        </Card>
      ) : null}
    </div>
  );
}
