"use client";

import { useEffect, useState } from "react";

import { PageHeader } from "@/components/common/page-header";
import { PaginationControls } from "@/components/common/pagination-controls";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
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
  TableToolbar,
} from "@/components/ui/table";
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
      .then((r) => {
        setItems(r.items);
        setPagination(r.pagination);
        setError(null);
      })
      .catch((e) => setError(describeApiError(e)));
  }, [page, status, q]);

  const view = (id: string) =>
    platformApi
      .email(id)
      .then(setOpen)
      .catch((e) => setError(describeApiError(e)));

  return (
    <div className="space-y-6">
      <PageHeader
        title="Email log"
        description="Every email the platform sends. “Accepted” means the mail provider took the message, not that it was delivered. Single-use links are masked."
      />
      {error ? (
        <p role="alert" className="text-sm text-danger">
          {error}
        </p>
      ) : null}
      <TableContainer>
        <TableToolbar>
          <form
            className="flex flex-wrap gap-2"
            onSubmit={(e) => {
              e.preventDefault();
              setQ(search.trim());
              setPage(1);
            }}
          >
            <Input
              className="w-72"
              placeholder="Recipient or subject"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              aria-label="Search emails"
            />
            <Button type="submit" variant="outline">
              Search
            </Button>
            <NativeSelect
              className="w-56"
              value={status}
              onChange={(e) => {
                setStatus(e.target.value);
                setPage(1);
              }}
              aria-label="Status filter"
            >
              <option value="">All statuses</option>
              <option value="ACCEPTED">Accepted</option>
              <option value="FAILED">Failed</option>
              <option value="LOGGED_ONLY">Not sent (dev log)</option>
            </NativeSelect>
          </form>
        </TableToolbar>
        <Table>
          <TableHeader>
            <TableRow className="hover:bg-transparent">
              <TableHead>When</TableHead>
              <TableHead>To</TableHead>
              <TableHead>Subject</TableHead>
              <TableHead>Type</TableHead>
              <TableHead>Status</TableHead>
              <TableHead align="right">Detail</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {items.map((e) => (
              <TableRow key={e.id}>
                <TableCell className="whitespace-nowrap tabular-nums text-foreground-secondary">
                  {new Date(e.created_at).toLocaleString()}
                </TableCell>
                <TableCell className="font-medium text-foreground">{e.recipient}</TableCell>
                <TableCell>{e.subject}</TableCell>
                <TableCell className="font-mono text-xs text-foreground-secondary">
                  {e.kind ?? "—"}
                </TableCell>
                <TableCell className="text-foreground-secondary">
                  {STATUS_LABEL[e.status]}
                  {e.failure_class ? ` (${e.failure_class})` : ""}
                </TableCell>
                <TableCell align="right">
                  <Button variant="outline" size="xs" onClick={() => void view(e.id)}>
                    View
                  </Button>
                </TableCell>
              </TableRow>
            ))}
            {items.length === 0 ? (
              <TableRow>
                <TableCell colSpan={6} className="py-6 text-center text-foreground-muted">
                  No emails.
                </TableCell>
              </TableRow>
            ) : null}
          </TableBody>
        </Table>
        {pagination ? (
          <PaginationControls pagination={pagination} onPageChange={setPage} />
        ) : null}
      </TableContainer>
      {open ? (
        <Card>
          <CardContent className="space-y-3 text-sm">
            <div className="flex items-center justify-between">
              <h2 className="font-semibold">{open.subject}</h2>
              <Button variant="outline" size="sm" onClick={() => setOpen(null)}>
                Close
              </Button>
            </div>
            <dl className="grid grid-cols-[8rem_1fr] gap-y-1">
              <dt className="text-foreground-muted">To</dt>
              <dd>{open.recipient}</dd>
              <dt className="text-foreground-muted">From</dt>
              <dd>{open.sender ?? "—"}</dd>
              <dt className="text-foreground-muted">Sent</dt>
              <dd>{new Date(open.created_at).toLocaleString()}</dd>
              <dt className="text-foreground-muted">Provider</dt>
              <dd>{open.provider}</dd>
              <dt className="text-foreground-muted">Status</dt>
              <dd>{STATUS_LABEL[open.status]}</dd>
              <dt className="text-foreground-muted">Type</dt>
              <dd>{open.kind ?? "—"}</dd>
              <dt className="text-foreground-muted">Company</dt>
              <dd>{open.company_id ?? "—"}</dd>
              <dt className="text-foreground-muted">Request ID</dt>
              <dd>{open.request_id ?? "—"}</dd>
              <dt className="text-foreground-muted">Duration</dt>
              <dd>{open.duration_ms != null ? `${open.duration_ms} ms` : "—"}</dd>
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
            <pre className="max-h-96 overflow-auto whitespace-pre-wrap rounded border border-border bg-surface-secondary p-3 text-xs">
              {open.text_body}
            </pre>
          </CardContent>
        </Card>
      ) : null}
    </div>
  );
}
