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
    <div className="flex items-center gap-2 text-sm font-medium text-foreground">
      <Building2 className="h-4 w-4 text-foreground-muted" aria-hidden="true" />
      <span>{company?.name ?? "…"}</span>
    </div>
  );
}
