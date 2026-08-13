import { Badge } from "@/components/ui/badge";
import type { CompanyDetail } from "@/lib/company/types";

export function CompanySummary({ company }: { company: CompanyDetail }) {
  return (
    <div className="flex items-center justify-between gap-4">
      <div>
        <p className="text-lg font-semibold text-foreground">{company.name}</p>
        <p className="text-sm text-foreground-muted">Company ID: {company.id}</p>
      </div>
      <Badge variant="secondary" className="uppercase">
        {company.status}
      </Badge>
    </div>
  );
}
