import {
  BAND_RESULT_LABELS,
  formatMinutes,
  INCOMPLETE_AT_LOCK_LABELS,
  labelOf,
  MISSING_PUNCH_LABELS,
  MULTI_PUNCH_LABELS,
} from "@/lib/attendance-policy/labels";
import {
  GEOFENCE_MODE_LABELS,
  type AttendancePolicyVersion,
} from "@/lib/attendance-policy/types";

function Fact({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <dt className="text-xs font-medium text-foreground-muted">{label}</dt>
      <dd className="mt-0.5 text-sm text-foreground">{children}</dd>
    </div>
  );
}

function bandRange(band: { min_minutes: number; max_minutes: number | null }): string {
  return band.max_minutes === null
    ? `${formatMinutes(band.min_minutes)} or more`
    : `${formatMinutes(band.min_minutes)} to ${formatMinutes(band.max_minutes)}`;
}

/** The live rules in words, so reading a policy does not mean opening its editor. */
export function AttendancePolicySummary({ version }: { version: AttendancePolicyVersion }) {
  return (
    <dl className="grid grid-cols-1 gap-4 sm:grid-cols-2">
      <Fact label="Hours worked">
        {version.hour_bands.length === 0 ? (
          "No bands"
        ) : (
          <ul className="space-y-0.5">
            {version.hour_bands
              .slice()
              .sort((a, b) => a.min_minutes - b.min_minutes)
              .map((band) => (
                <li key={band.id}>
                  {bandRange(band)}: {labelOf(BAND_RESULT_LABELS, band.result_status)}
                </li>
              ))}
          </ul>
        )}
      </Fact>
      <Fact label="Grace">
        {version.grace_in_minutes} minutes late, {version.grace_out_minutes} minutes early
      </Fact>
      <Fact label="Late days before a half-day">
        {version.lates_to_half_day_count ?? "Off"}
      </Fact>
      <Fact label="Leaving early needs approval">
        {version.early_departure_requires_approval ? "Yes" : "No"}
      </Fact>
      <Fact label="When a punch is missing">
        {labelOf(MISSING_PUNCH_LABELS, version.missing_punch_behaviour)}
      </Fact>
      <Fact label="Location check">{GEOFENCE_MODE_LABELS[version.geofence_mode ?? "DISABLED"]}</Fact>
      <Fact label="Several punches a day">
        {labelOf(MULTI_PUNCH_LABELS, version.multi_punch_mode)}
      </Fact>
      <Fact label="Days still incomplete when the month closes">
        {labelOf(INCOMPLETE_AT_LOCK_LABELS, version.incomplete_at_lock_behaviour)}
      </Fact>
    </dl>
  );
}
