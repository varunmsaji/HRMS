import { Badge } from "@/components/ui/badge";
import { formatDateTime } from "@/lib/attendance/format";
import type { CompanyProfile } from "@/lib/company/types";

function Field({
  label,
  value,
  mono = false,
}: {
  label: string;
  value: string | null | undefined;
  mono?: boolean;
}) {
  const hasValue = Boolean(value && value.trim());
  const display = hasValue ? value : "Not configured";
  return (
    <div className="py-1">
      <dt className="text-xs font-medium text-foreground-muted">{label}</dt>
      <dd
        className={`mt-0.5 text-sm ${
          hasValue ? "font-medium text-foreground" : "text-foreground-disabled"
        } ${mono && hasValue ? "font-mono" : ""}`}
      >
        {display}
      </dd>
    </div>
  );
}

const DAY_LABELS: Record<string, string> = {
  MON: "Mon",
  TUE: "Tue",
  WED: "Wed",
  THU: "Thu",
  FRI: "Fri",
  SAT: "Sat",
  SUN: "Sun",
};

export function CompanyProfileView({ profile }: { profile: CompanyProfile }) {
  const workingSummary = profile.working_days
    .filter((day) => day.is_working)
    .map((day) => DAY_LABELS[day.day] ?? day.day)
    .join(", ");

  return (
    <div className="divide-y divide-border">
      <section className="pb-6">
        <h3 className="text-xs font-semibold uppercase tracking-wider text-foreground-muted">
          Basic information
        </h3>
        <dl className="mt-3 grid grid-cols-1 gap-x-6 gap-y-3 sm:grid-cols-2 lg:grid-cols-4">
          <Field label="Company name" value={profile.name} />
          <Field label="Legal name" value={profile.legal_name} />
          <Field label="Registration number" value={profile.registration_number} mono />
          <Field label="Industry" value={profile.industry_code} />
          <Field label="Company size" value={profile.company_size} />
          <Field label="Country" value={profile.country_code} />
          <Field label="Currency" value={profile.currency} mono />
          <Field label="Timezone" value={profile.timezone} />
        </dl>
      </section>

      <section className="py-6">
        <h3 className="text-xs font-semibold uppercase tracking-wider text-foreground-muted">
          Contact &amp; Address
        </h3>
        <dl className="mt-3 grid grid-cols-1 gap-x-6 gap-y-3 sm:grid-cols-3">
          <Field label="Email" value={profile.contact?.email} />
          <Field label="Phone" value={profile.contact?.phone} />
          <Field label="Website" value={profile.contact?.website} />
          <Field label="Line 1" value={profile.address?.line1} />
          <Field label="Line 2" value={profile.address?.line2} />
          <Field label="City" value={profile.address?.city} />
          <Field label="State" value={profile.address?.state} />
          <Field label="Postal code" value={profile.address?.postal_code} mono />
          <Field label="Country code" value={profile.address?.country_code} />
        </dl>
      </section>

      <section className="py-6">
        <h3 className="text-xs font-semibold uppercase tracking-wider text-foreground-muted">
          Localization &amp; Schedule
        </h3>
        <dl className="mt-3 grid grid-cols-1 gap-x-6 gap-y-3 sm:grid-cols-3">
          <Field label="Language" value={profile.locale?.language_code} />
          <Field label="Date format" value={profile.locale?.date_format} mono />
          <Field
            label="Fiscal year start"
            value={profile.fiscal_year ? String(profile.fiscal_year.start_month) : null}
          />
          <Field label="Working days" value={workingSummary || null} />
          <Field label="Start" value={profile.business_hours?.start_time} mono />
          <Field label="End" value={profile.business_hours?.end_time} mono />
        </dl>
      </section>

      <section className="pt-6">
        <h3 className="text-xs font-semibold uppercase tracking-wider text-foreground-muted">
          Branding &amp; Metadata
        </h3>
        <dl className="mt-3 grid grid-cols-1 gap-x-6 gap-y-3 sm:grid-cols-3">
          <Field label="Logo URL" value={profile.branding?.logo_url} />
          <Field label="Primary color" value={profile.branding?.theme?.primary_color} mono />
          <div className="py-1">
            <dt className="text-xs font-medium text-foreground-muted">Status</dt>
            <dd className="mt-0.5">
              <Badge variant="secondary" className="uppercase">
                {profile.status}
              </Badge>
            </dd>
          </div>
          <Field label="Version" value={String(profile.version)} mono />
          <Field label="Subdomain" value={profile.subdomain} mono />
          <Field
            label="Onboarded at"
            value={profile.onboarded_at ? formatDateTime(profile.onboarded_at, profile.timezone) : null}
          />
          <Field
            label="Trial ends at"
            value={profile.trial_ends_at ? formatDateTime(profile.trial_ends_at, profile.timezone) : null}
          />
        </dl>
      </section>
    </div>
  );
}
