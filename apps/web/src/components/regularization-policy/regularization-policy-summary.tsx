import { APPROVAL_CHAIN_LABELS } from "@/lib/policy/approval-labels";
import { REGULARIZATION_TYPE_LABELS } from "@/lib/regularization-policy/labels";
import type { RegularizationPolicyVersion } from "@/lib/regularization-policy/types";

function Fact({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <dt className="text-xs font-medium text-foreground-muted">{label}</dt>
      <dd className="mt-0.5 text-sm text-foreground">{children}</dd>
    </div>
  );
}

/** The live rules in words, so reading a policy does not mean opening its editor. */
export function RegularizationPolicySummary({
  version,
}: {
  version: RegularizationPolicyVersion;
}) {
  const askers = [
    version.allow_employee_request ? "Employees" : null,
    version.allow_manager_request ? "Managers" : null,
    version.allow_hr_request ? "HR" : null,
  ].filter(Boolean);
  const types = version.allowed_types
    .slice()
    .sort((a, b) => a.sort_order - b.sort_order)
    .map((t) => REGULARIZATION_TYPE_LABELS[t.regularization_type] ?? t.regularization_type);

  return (
    <dl className="grid grid-cols-1 gap-4 sm:grid-cols-2">
      <Fact label="Who can ask">{askers.length > 0 ? askers.join(", ") : "Nobody"}</Fact>
      <Fact label="Approval">
        {APPROVAL_CHAIN_LABELS[version.approval_chain] ?? version.approval_chain}
      </Fact>
      <Fact label="What can be corrected">
        {types.length > 0 ? types.join(", ") : "Nothing"}
      </Fact>
      <Fact label="Evidence">
        {[
          version.reason_required ? "Reason required" : "No reason needed",
          version.attachment_required ? "proof required" : "no proof needed",
        ].join(", ")}
      </Fact>
      <Fact label="How far back">
        {version.max_backdated_days === null
          ? "No limit"
          : `${version.max_backdated_days} ${version.max_backdated_days === 1 ? "day" : "days"}`}
      </Fact>
      <Fact label="Requests per person per month">{version.max_requests_per_month ?? "No limit"}</Fact>
    </dl>
  );
}
