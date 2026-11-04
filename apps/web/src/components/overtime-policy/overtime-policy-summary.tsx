import { formatMinutes } from "@/lib/attendance-policy/labels";
import {
  DAY_CLASS_LABELS,
  ELIGIBILITY_LABELS,
  NIGHT_MODE_LABELS,
  ROUNDING_LABELS,
} from "@/lib/overtime-policy/labels";
import type { OvertimePolicyVersion } from "@/lib/overtime-policy/types";
import { APPROVAL_CHAIN_LABELS } from "@/lib/policy/approval-labels";

function Fact({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <dt className="text-xs font-medium text-foreground-muted">{label}</dt>
      <dd className="mt-0.5 text-sm text-foreground">{children}</dd>
    </div>
  );
}

function cap(minutes: number | null): string {
  return minutes === null ? "No limit" : formatMinutes(minutes);
}

/** The live rules in words, so reading a policy does not mean opening its editor. */
export function OvertimePolicySummary({ version }: { version: OvertimePolicyVersion }) {
  return (
    <dl className="grid grid-cols-1 gap-4 sm:grid-cols-2">
      <Fact label="Who can earn overtime">
        {ELIGIBILITY_LABELS[version.eligibility] ?? version.eligibility}
      </Fact>
      <Fact label="Minimum overtime">
        {version.min_ot_minutes > 0 ? formatMinutes(version.min_ot_minutes) : "None"}
      </Fact>
      <Fact label="Approval">
        {APPROVAL_CHAIN_LABELS[version.approval_chain] ?? version.approval_chain}
        {version.requires_post_approval ? ", after it is worked" : ""}
      </Fact>
      <Fact label="Rounding">
        {version.rounding_mode === "NONE"
          ? ROUNDING_LABELS.NONE
          : `${ROUNDING_LABELS[version.rounding_mode] ?? version.rounding_mode}${
              version.rounding_minutes ? ` ${version.rounding_minutes} minutes` : ""
            }`}
      </Fact>
      <Fact label="Limit per day, week, month">
        {cap(version.daily_cap_minutes)}, {cap(version.weekly_cap_minutes)},{" "}
        {cap(version.monthly_cap_minutes)}
      </Fact>
      <Fact label="Overtime paid as">
        {version.comp_off_instead_of_pay ? "Comp-off days" : "Pay"}
      </Fact>
      <Fact label="Night overtime">
        {NIGHT_MODE_LABELS[version.night_ot_mode] ?? version.night_ot_mode}
        {version.night_window_start && version.night_window_end
          ? `, ${version.night_window_start} to ${version.night_window_end}`
          : ""}
      </Fact>
      <Fact label="Payroll labels">
        {version.rate_rows.length === 0 ? (
          "None"
        ) : (
          <ul className="space-y-0.5">
            {version.rate_rows
              .slice()
              .sort((a, b) => a.sort_order - b.sort_order)
              .map((row) => (
                <li key={row.id}>
                  {DAY_CLASS_LABELS[row.day_class] ?? row.day_class}: {row.classification_code}
                  {row.multiplier_decimal ? ` (×${row.multiplier_decimal})` : ""}
                </li>
              ))}
          </ul>
        )}
      </Fact>
    </dl>
  );
}
