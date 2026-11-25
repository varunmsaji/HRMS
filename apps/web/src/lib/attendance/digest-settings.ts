/** `GET/PUT /v1/attendance/digest-settings`: whether this company receives the attendance digest
 * emails. Both are on until a company switches one off. */

export interface DigestSettings {
  /** The weekday-morning note to each manager about their team. */
  manager_daily_enabled: boolean;
  /** The Monday summary of last week, to people who see the whole company. */
  hr_weekly_enabled: boolean;
  /** Whether this deployment sends the digests at all; when it does not, nothing is sent. */
  deployment_enabled: boolean;
  updated_at: string | null;
}

export type DigestSettingsInput = Pick<DigestSettings, "manager_daily_enabled" | "hr_weekly_enabled">;

export const DIGEST_SETTINGS_PATH = "/attendance/digest-settings";
