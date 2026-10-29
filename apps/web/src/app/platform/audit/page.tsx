"use client";

import { useEffect, useState } from "react";

import { PageHeader } from "@/components/common/page-header";
import { PaginationControls } from "@/components/common/pagination-controls";
import { Badge } from "@/components/ui/badge";
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
import { platformApi, type AuditEntry } from "@/lib/platform/api";

const ACTIONS = [
  "COMPANY_APPROVED",
  "COMPANY_REJECTED",
  "COMPANY_SUSPENDED",
  "COMPANY_REACTIVATED",
  "COMPANY_TERMINATED",
  "SUBSCRIPTION_CHANGED",
  "COMPANY_ADMIN_UNLOCKED",
  "COMPANY_ADMIN_VERIFICATION_RESENT",
  "PLATFORM_ADMIN_CREATED",
  "PLATFORM_ADMIN_DISABLED",
  "PLATFORM_ADMIN_ENABLED",
  "PLATFORM_ADMIN_PASSWORD_RESET",
  "PLATFORM_LOGIN",
  "PLATFORM_LOGOUT",
];

export default function PlatformAuditPage() {
  const [items, setItems] = useState<AuditEntry[]>([]);
  const [pagination, setPagination] = useState<PaginationMeta | null>(null);
  const [page, setPage] = useState(1);
  const [action, setAction] = useState("");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    platformApi
      .auditLog({ page, action: action || undefined })
      .then((r) => {
        setItems(r.items);
        setPagination(r.pagination);
      })
      .catch((e) => setError(describeApiError(e)));
  }, [page, action]);

  return (
    <div className="space-y-6">
      <PageHeader
        title="Audit log"
        description="Immutable record of platform administrative actions across all tenants."
      />
      {error ? (
        <p role="alert" className="text-sm text-danger">
          {error}
        </p>
      ) : null}
      <TableContainer>
        <TableToolbar>
          <NativeSelect
            className="w-72"
            value={action}
            onChange={(e) => {
              setAction(e.target.value);
              setPage(1);
            }}
            aria-label="Action filter"
          >
            <option value="">All actions</option>
            {ACTIONS.map((a) => (
              <option key={a} value={a}>
                {a.replaceAll("_", " ").toLowerCase()}
              </option>
            ))}
          </NativeSelect>
        </TableToolbar>
        <Table>
          <TableHeader>
            <TableRow className="hover:bg-transparent">
              <TableHead>When</TableHead>
              <TableHead>Who</TableHead>
              <TableHead>Action</TableHead>
              <TableHead>Change</TableHead>
              <TableHead>Reason</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {items.map((e) => (
              <TableRow key={e.id}>
                <TableCell className="whitespace-nowrap tabular-nums text-foreground-secondary">
                  {new Date(e.created_at).toLocaleString()}
                </TableCell>
                <TableCell className="font-medium text-foreground">
                  {e.actor_username ?? "—"}
                </TableCell>
                <TableCell>
                  <Badge variant="outline" className="font-mono text-2xs">
                    {e.action}
                  </Badge>
                </TableCell>
                <TableCell className="text-xs text-foreground-secondary">
                  {e.before_status && e.after_status
                    ? `${e.before_status} → ${e.after_status}`
                    : "—"}
                </TableCell>
                <TableCell className="text-foreground-secondary">{e.reason ?? "—"}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
        {pagination ? (
          <PaginationControls pagination={pagination} onPageChange={setPage} />
        ) : null}
      </TableContainer>
    </div>
  );
}
