import { ACCRUAL_LABELS, LEAVE_APPROVAL_LABELS } from "@/lib/leave-policy/labels";
import { YEAR_END_ACTION_LABELS, type LeavePolicyVersion } from "@/lib/leave-policy/types";

function Fact({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <dt className="text-xs font-medium text-foreground-muted">{label}</dt>
      <dd className="mt-0.5 text-sm text-foreground">{children}</dd>
    </div>
  );
}

function yesNo(value: boolean): string {
  return value ? "Yes" : "No";
}

/** The live rules in words, so reading a policy does not mean opening its editor. */
export function LeavePolicySummary({ version }: { version: LeavePolicyVersion }) {
  const applicants = [
    version.allow_employee_request ? "Employees" : null,
    version.allow_manager_request_on_behalf ? "Managers for their reports" : null,
    version.allow_hr_request_on_behalf ? "HR for anyone" : null,
  ].filter(Boolean);

  return (
    <dl className="grid grid-cols-1 gap-4 sm:grid-cols-2">
      <Fact label="Who can apply">{applicants.length > 0 ? applicants.join(", ") : "Nobody"}</Fact>
      <Fact label="Approval">
        {LEAVE_APPROVAL_LABELS[version.approval_chain] ?? version.approval_chain}
      </Fact>
      <Fact label="Days credited">
        {version.accrual_frequency === "NONE"
          ? ACCRUAL_LABELS.NONE
          : `${version.accrual_rate_per_cycle ?? "0"} ${
              version.accrual_frequency === "MONTHLY" ? "each month" : "each year"
            }`}
      </Fact>
      <Fact label="At the end of the leave year">
        {YEAR_END_ACTION_LABELS[version.year_end_action] ?? version.year_end_action}
        {version.year_end_action !== "LAPSE" && version.max_carry_forward_days
          ? `, up to ${version.max_carry_forward_days} days`
          : ""}
      </Fact>
      <Fact label="Reason required">{yesNo(version.reason_required)}</Fact>
      <Fact label="Half-days">{yesNo(version.half_day_allowed)}</Fact>
      <Fact label="Weekly offs and holidays between leave days count">
        {yesNo(version.sandwich_rule_enabled)}
      </Fact>
      <Fact label="Document required">{yesNo(version.attachment_required)}</Fact>
      <Fact label="Furthest back an application can start">
        {version.max_backdated_days === null ? "No limit" : `${version.max_backdated_days} days`}
      </Fact>
      <Fact label="Most applications per month">
        {version.max_requests_per_month === null ? "No limit" : version.max_requests_per_month}
      </Fact>
      <Fact label="On probation">
        {version.allowed_during_probation ? "Can apply" : "Cannot apply"},{" "}
        {version.accrue_during_probation ? "earn days" : "do not earn days"}
      </Fact>
      <Fact label="Balance below zero">
        {version.allow_negative_balance
          ? `Up to ${version.negative_balance_floor ?? "0"} days`
          : "Not allowed"}
      </Fact>
      <Fact label="Encashment">
        {version.encashment_allowed
          ? version.max_encashment_days
            ? `Up to ${version.max_encashment_days} days`
            : "Allowed"
          : "Not allowed"}
      </Fact>
    </dl>
  );
}
