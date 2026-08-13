import { Badge } from "@/components/ui/badge";
import type { CompanyProfile } from "@/lib/company/types";

function Field({ label, value }: { label: string; value: string | null | undefined }) {
  const display = value && value.trim() ? value : "Not configured";
  return (
    <div>
      <dt className="text-xs font-medium uppercase tracking-wide text-foreground-muted">{label}</dt>
      <dd className={`mt-0.5 text-sm ${value && value.trim() ? "text-foreground" : "text-foreground-muted"}`}>
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
    <div className="space-y-8">
      <section>
        <h3 className="text-sm font-medium text-foreground">Basic information</h3>
        <dl className="mt-3 grid grid-cols-1 gap-4 sm:grid-cols-2">
          <Field label="Company name" value={profile.name} />
          <Field label="Legal name" value={profile.legal_name} />
          <Field label="Registration number" value={profile.registration_number} />
          <Field label="Industry" value={profile.industry_code} />
          <Field label="Company size" value={profile.company_size} />
          <Field label="Country" value={profile.country_code} />
          <Field label="Currency" value={profile.currency} />
          <Field label="Timezone" value={profile.timezone} />
        </dl>
      </section>

      <section>
        <h3 className="text-sm font-medium text-foreground">Contact information</h3>
        <dl className="mt-3 grid grid-cols-1 gap-4 sm:grid-cols-3">
          <Field label="Email" value={profile.contact?.email} />
          <Field label="Phone" value={profile.contact?.phone} />
          <Field label="Website" value={profile.contact?.website} />
        </dl>
      </section>

      <section>
        <h3 className="text-sm font-medium text-foreground">Address</h3>
        <dl className="mt-3 grid grid-cols-1 gap-4 sm:grid-cols-3">
          <Field label="Line 1" value={profile.address?.line1} />
          <Field label="Line 2" value={profile.address?.line2} />
          <Field label="City" value={profile.address?.city} />
          <Field label="State" value={profile.address?.state} />
          <Field label="Postal code" value={profile.address?.postal_code} />
          <Field label="Country code" value={profile.address?.country_code} />
        </dl>
      </section>

      <section>
        <h3 className="text-sm font-medium text-foreground">Localization</h3>
        <dl className="mt-3 grid grid-cols-1 gap-4 sm:grid-cols-3">
          <Field label="Language" value={profile.locale?.language_code} />
          <Field label="Date format" value={profile.locale?.date_format} />
          <Field
            label="Fiscal year start"
            value={profile.fiscal_year ? String(profile.fiscal_year.start_month) : null}
          />
        </dl>
      </section>

      <section>
        <h3 className="text-sm font-medium text-foreground">Working schedule</h3>
        <dl className="mt-3 grid grid-cols-1 gap-4 sm:grid-cols-2">
          <Field label="Working days" value={workingSummary || null} />
        </dl>
      </section>

      <section>
        <h3 className="text-sm font-medium text-foreground">Business hours</h3>
        <dl className="mt-3 grid grid-cols-1 gap-4 sm:grid-cols-2">
          <Field label="Start" value={profile.business_hours?.start_time} />
          <Field label="End" value={profile.business_hours?.end_time} />
        </dl>
      </section>

      <section>
        <h3 className="text-sm font-medium text-foreground">Branding</h3>
        <dl className="mt-3 grid grid-cols-1 gap-4 sm:grid-cols-2">
          <Field label="Logo URL" value={profile.branding?.logo_url} />
          <Field label="Primary color" value={profile.branding?.theme?.primary_color} />
        </dl>
      </section>

      <section>
        <h3 className="text-sm font-medium text-foreground">Company metadata</h3>
        <dl className="mt-3 grid grid-cols-1 gap-4 sm:grid-cols-2">
          <div>
            <dt className="text-xs font-medium uppercase tracking-wide text-foreground-muted">Status</dt>
            <dd className="mt-0.5">
              <Badge variant="secondary" className="uppercase">
                {profile.status}
              </Badge>
            </dd>
          </div>
          <Field label="Version" value={String(profile.version)} />
          <Field label="Subdomain" value={profile.subdomain} />
          <Field label="Onboarded at" value={profile.onboarded_at} />
          <Field label="Trial ends at" value={profile.trial_ends_at} />
        </dl>
      </section>
    </div>
  );
}
