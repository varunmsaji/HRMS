"use client";

import { useCallback, useEffect, useState } from "react";

import { CompanyProfileForm } from "@/components/company/company-profile-form";
import { CompanyProfileView } from "@/components/company/company-profile-view";
import { ErrorState } from "@/components/common/error-state";
import { LoadingState } from "@/components/common/loading-state";
import { PageHeader } from "@/components/common/page-header";
import { useToast } from "@/components/common/toast";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { apiClient } from "@/lib/api/client";
import { ApiError, describeApiError, getFieldError, getStaleResourceCurrent } from "@/lib/api/errors";
import type { CompanyProfile } from "@/lib/company/types";
import { rememberCompanyDateFormat } from "@/lib/dates/use-company-date";
import {
  buildProfilePatch,
  profileToFormValues,
  validateCompanyProfileForm,
  type CompanyProfileFormErrors,
  type CompanyProfileFormValues,
} from "@/lib/company/validate-company-profile";

export default function CompanyProfilePage() {
  const { toast } = useToast();
  const [profile, setProfile] = useState<CompanyProfile | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<ApiError | null>(null);
  const [editing, setEditing] = useState(false);
  const [formValues, setFormValues] = useState<CompanyProfileFormValues | null>(null);
  const [formErrors, setFormErrors] = useState<CompanyProfileFormErrors>({});
  const [saving, setSaving] = useState(false);
  const [staleMessage, setStaleMessage] = useState<string | null>(null);

  const loadProfile = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await apiClient.get<CompanyProfile>("/companies/current");
      setProfile(data);
      rememberCompanyDateFormat(data.locale?.date_format);
      return data;
    } catch (err) {
      setProfile(null);
      setError(
        err instanceof ApiError
          ? err
          : new ApiError({ status: 0, code: "UNKNOWN_ERROR", message: "Something went wrong." }),
      );
      return null;
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadProfile();
  }, [loadProfile]);

  function startEditing() {
    if (!profile) return;
    setFormValues(profileToFormValues(profile));
    setFormErrors({});
    setStaleMessage(null);
    setEditing(true);
  }

  function cancelEditing() {
    setEditing(false);
    setFormValues(null);
    setFormErrors({});
    setStaleMessage(null);
  }

  async function handleSave() {
    if (!profile || !formValues) return;

    const clientErrors = validateCompanyProfileForm(formValues);
    if (Object.keys(clientErrors).length > 0) {
      setFormErrors(clientErrors);
      return;
    }

    const patch = buildProfilePatch(formValues, profile);
    if (Object.keys(patch).length === 0) {
      setEditing(false);
      setFormValues(null);
      toast({ title: "No changes to save", variant: "default" });
      return;
    }

    setSaving(true);
    setFormErrors({});
    setStaleMessage(null);
    try {
      const updated = await apiClient.patch<CompanyProfile>("/companies/current", patch, {
        ifMatch: String(profile.version),
      });
      setProfile(updated);
      rememberCompanyDateFormat(updated.locale?.date_format);
      setEditing(false);
      setFormValues(null);
      toast({ title: "Company profile saved", variant: "success" });
    } catch (err) {
      if (err instanceof ApiError) {
        if (err.status === 409 && err.code === "STALE_RESOURCE") {
          setStaleMessage("The company profile was changed by someone else.");
          return;
        }
        if (err.status === 422) {
          setFormErrors({
            name: getFieldError(err.details, "name"),
            currency: getFieldError(err.details, "currency"),
            timezone: getFieldError(err.details, "timezone"),
            businessHoursStart: getFieldError(err.details, "business_hours"),
            businessHoursEnd: getFieldError(err.details, "business_hours"),
            workingDays: getFieldError(err.details, "working_days"),
            fiscalYearStartMonth: getFieldError(err.details, "fiscal_year"),
          });
          return;
        }
        if (err.status === 403) {
          setError(err);
          setEditing(false);
          return;
        }
        if (err.status === 423) {
          setStaleMessage(err.message);
          return;
        }
      }
      toast({ title: "Could not save profile", description: describeApiError(err), variant: "danger" });
    } finally {
      setSaving(false);
    }
  }

  async function reloadLatestProfile() {
    const latest = await loadProfile();
    if (latest) {
      setEditing(false);
      setFormValues(null);
      setStaleMessage(null);
      toast({ title: "Profile reloaded", variant: "success" });
    }
  }

  const currencyLocked = profile ? profile.status !== "TRIAL" : false;

  return (
    <div className="space-y-6">
      <PageHeader
        backHref="/app/settings"
        backLabel="Settings"
        title="Company profile"
        description="Your organisation's registered details."
        actions={
          profile && !editing ? (
            <Button type="button" onClick={startEditing}>
              Edit
            </Button>
          ) : null
        }
      />

      <Card>
        <CardContent className="pt-6">
          {loading ? <LoadingState label="Loading profile…" /> : null}
          {error && !loading ? (
            <ErrorState
              message={
                error.status === 403
                  ? "You do not have permission to view this company profile."
                  : error.message
              }
              onRetry={() => void loadProfile()}
            />
          ) : null}

          {staleMessage ? (
            <div
              className="mb-4 rounded-md border border-warning/30 bg-warning/5 p-4"
              role="alert"
            >
              <p className="text-sm font-medium text-foreground">{staleMessage}</p>
              <div className="mt-3 flex flex-wrap gap-2">
                <Button type="button" size="sm" onClick={() => void reloadLatestProfile()}>
                  Reload latest profile
                </Button>
                <Button type="button" size="sm" variant="outline" onClick={cancelEditing}>
                  Cancel current changes
                </Button>
              </div>
            </div>
          ) : null}

          {!loading && !error && profile && editing && formValues ? (
            <div className="space-y-6">
              <CompanyProfileForm
                values={formValues}
                errors={formErrors}
                onChange={setFormValues}
                currencyLocked={currencyLocked}
              />
              <div className="flex flex-wrap gap-2">
                <Button type="button" onClick={() => void handleSave()} disabled={saving}>
                  {saving ? "Saving…" : "Save changes"}
                </Button>
                <Button type="button" variant="outline" onClick={cancelEditing} disabled={saving}>
                  Cancel
                </Button>
              </div>
            </div>
          ) : null}

          {!loading && !error && profile && !editing ? (
            <CompanyProfileView profile={profile} />
          ) : null}
        </CardContent>
      </Card>
    </div>
  );
}
