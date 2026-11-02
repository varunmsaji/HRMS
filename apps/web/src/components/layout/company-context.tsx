"use client";

import { Building2 } from "lucide-react";
import { useEffect, useState } from "react";

import { apiClient } from "@/lib/api/client";
import { useAuth } from "@/lib/auth/auth-context";

interface CompanyDetail {
  id: string;
  name: string;
  status: string;
}

/** Uses `GET /v1/auth/companies/{id}` for a lightweight top-bar name/status lookup.
 * Full profile editing lives on `/app/company` via `GET /v1/companies/current`. */
export function CompanyContext() {
  const { session } = useAuth();
  const [company, setCompany] = useState<CompanyDetail | null>(null);

  useEffect(() => {
    if (!session) return;
    let cancelled = false;
    apiClient
      .get<CompanyDetail>(`/auth/companies/${session.companyId}`)
      .then((data) => {
        if (!cancelled) setCompany(data);
      })
      .catch(() => {
        // Non-critical for the shell to render — the topbar just shows a placeholder.
      });
    return () => {
      cancelled = true;
    };
  }, [session]);

  return (
    // A plain label, not a bordered chip: it only shows the active company and is not a control.
    <div
      className="flex shrink-0 items-center gap-2 text-sm font-semibold text-foreground"
      title={company?.name}
    >
      <Building2 className="h-4 w-4 shrink-0 text-foreground-muted" aria-hidden="true" />
      <span className="max-w-[200px] truncate">{company?.name ?? "…"}</span>
    </div>
  );
}
