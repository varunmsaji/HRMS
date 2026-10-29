"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";

import { PageHeader } from "@/components/common/page-header";
import { PaginationControls } from "@/components/common/pagination-controls";
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
import { describeApiError } from "@/lib/api/errors";
import { platformApi, type CompanyListItem } from "@/lib/platform/api";
import type { PaginationMeta } from "@/lib/api/types";

import { StatusBadge } from "../status-badge";

const STATUSES = ["PENDING_APPROVAL", "TRIAL", "ACTIVE", "SUSPENDED", "REJECTED", "TERMINATED"];

function CompaniesList() {
  const [items, setItems] = useState<CompanyListItem[]>([]);
  const [pagination, setPagination] = useState<PaginationMeta | null>(null);
  const searchParams = useSearchParams();
  const [status, setStatus] = useState(searchParams.get("status") ?? "");
  const [q, setQ] = useState("");
  const [page, setPage] = useState(1);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    platformApi
      .listCompanies({ status: status || undefined, q: q.trim() || undefined, page })
      .then((list) => {
        if (cancelled) return;
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
      <PageHeader
        title="Companies"
        description="Tenant companies registered on the platform, their lifecycle status, and primary admin contacts."
      />

      {error ? (
        <p role="alert" className="text-sm text-danger">
          {error}
        </p>
      ) : null}

      <TableContainer>
        <TableToolbar>
          <div className="flex flex-wrap gap-3">
            <NativeSelect
              className="w-52"
              value={status}
              onChange={(e) => {
                setStatus(e.target.value);
                setPage(1);
              }}
              aria-label="Status filter"
            >
              <option value="">All statuses</option>
              {STATUSES.map((s) => (
                <option key={s} value={s}>
                  {s.replace("_", " ")}
                </option>
              ))}
            </NativeSelect>
            <Input
              className="w-64"
              placeholder="Search company or admin email"
              value={q}
              onChange={(e) => {
                setQ(e.target.value);
                setPage(1);
              }}
              aria-label="Search"
            />
          </div>
        </TableToolbar>

        <Table>
          <TableHeader>
            <TableRow className="hover:bg-transparent">
              <TableHead>Company</TableHead>
              <TableHead>Admin</TableHead>
              <TableHead>Status</TableHead>
              <TableHead>Registered</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {items.map((c) => (
              <TableRow key={c.id}>
                <TableCell>
                  <Link
                    href={`/platform/companies/${c.id}`}
                    className="font-medium text-primary hover:underline"
                  >
                    {c.name}
                  </Link>
                </TableCell>
                <TableCell>
                  <div className="font-medium text-foreground">{c.admin_name ?? "—"}</div>
                  <div className="text-xs text-foreground-muted">{c.admin_email}</div>
                </TableCell>
                <TableCell>
                  <StatusBadge status={c.status} />
                </TableCell>
                <TableCell className="tabular-nums text-foreground-secondary">
                  {new Date(c.created_at).toLocaleDateString()}
                </TableCell>
              </TableRow>
            ))}
            {!loading && items.length === 0 ? (
              <TableRow>
                <TableCell colSpan={4} className="py-8 text-center text-foreground-muted">
                  No companies match.
                </TableCell>
              </TableRow>
            ) : null}
          </TableBody>
        </Table>

        {pagination ? (
          <PaginationControls
            pagination={pagination}
            onPageChange={setPage}
            disabled={loading}
          />
        ) : null}
      </TableContainer>
    </div>
  );
}

export default function CompaniesPage() {
  return (
    <Suspense fallback={null}>
      <CompaniesList />
    </Suspense>
  );
}
