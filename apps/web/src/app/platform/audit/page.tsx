"use client";

import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import type { PaginationMeta } from "@/lib/api/types";
import { describeApiError } from "@/lib/api/errors";
import { platformApi, type AuditEntry } from "@/lib/platform/api";

export default function PlatformAuditPage() {
  const [items, setItems] = useState<AuditEntry[]>([]);
  const [pagination, setPagination] = useState<PaginationMeta | null>(null);
  const [page, setPage] = useState(1);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    platformApi
      .auditLog({ page })
      .then((r) => { setItems(r.items); setPagination(r.pagination); })
      .catch((e) => setError(describeApiError(e)));
  }, [page]);

  return (
    <div className="space-y-6">
      <h1 className="text-xl font-semibold">Audit log</h1>
      {error ? <p role="alert" className="text-sm text-danger">{error}</p> : null}
      <Card>
        <CardContent className="p-0">
          <table className="w-full text-sm">
            <thead className="border-b border-border text-left text-foreground-muted">
              <tr>
                <th className="px-4 py-2 font-medium">When</th>
                <th className="px-4 py-2 font-medium">Who</th>
                <th className="px-4 py-2 font-medium">Action</th>
                <th className="px-4 py-2 font-medium">Change</th>
                <th className="px-4 py-2 font-medium">Reason</th>
              </tr>
            </thead>
            <tbody>
              {items.map((e) => (
                <tr key={e.id} className="border-b border-border last:border-0">
                  <td className="px-4 py-2 whitespace-nowrap">{new Date(e.created_at).toLocaleString()}</td>
                  <td className="px-4 py-2">{e.actor_username ?? "—"}</td>
                  <td className="px-4 py-2">{e.action}</td>
                  <td className="px-4 py-2">{e.before_status && e.after_status ? `${e.before_status} → ${e.after_status}` : "—"}</td>
                  <td className="px-4 py-2">{e.reason ?? "—"}</td>
                </tr>
              ))}
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
    </div>
  );
}
