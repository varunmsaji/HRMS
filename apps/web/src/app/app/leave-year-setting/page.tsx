"use client";

import { useCallback, useEffect, useState } from "react";

import { ErrorState } from "@/components/common/error-state";
import { FormField } from "@/components/common/form-field";
import { LoadingState } from "@/components/common/loading-state";
import { PageHeader } from "@/components/common/page-header";
import { useToast } from "@/components/common/toast";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/native-select";
import { apiClient } from "@/lib/api/client";
import { ApiError, describeApiError } from "@/lib/api/errors";
import { usePermissions } from "@/lib/auth/use-permissions";
import { LEAVE_YEAR_TYPES, type LeaveYearSetting } from "@/lib/leave-year/types";
import {
  EMPTY_LEAVE_YEAR_FORM_VALUES,
  buildLeaveYearSettingPayload,
  leaveYearSettingToFormValues,
  validateLeaveYearForm,
  type LeaveYearFormErrors,
  type LeaveYearFormValues,
} from "@/lib/leave-year/validate-leave-year";

const LEAVE_YEAR_TYPE_LABELS: Record<string, string> = {
  CALENDAR: "Calendar year (Jan – Dec)",
  FINANCIAL: "Financial year (Apr – Mar)",
  ANNIVERSARY: "Employee's joining anniversary",
  CUSTOM: "Custom start date",
};

export default function LeaveYearSettingPage() {
  const { toast } = useToast();
  const { can } = usePermissions();
  const canManage = can("LEAVE.YEAR_SETTING_MANAGE");

  const [setting, setSetting] = useState<LeaveYearSetting | null>(null);
  const [values, setValues] = useState<LeaveYearFormValues>(EMPTY_LEAVE_YEAR_FORM_VALUES);
  const [errors, setErrors] = useState<LeaveYearFormErrors>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<ApiError | null>(null);
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await apiClient.get<LeaveYearSetting>("/leave-year-setting");
      setSetting(data);
      setValues(leaveYearSettingToFormValues(data));
    } catch (err) {
      setSetting(null);
      setError(
        err instanceof ApiError
          ? err
          : new ApiError({ status: 0, code: "UNKNOWN_ERROR", message: "Something went wrong." }),
      );
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function handleSave() {
    const clientErrors = validateLeaveYearForm(values);
    if (Object.keys(clientErrors).length > 0) {
      setErrors(clientErrors);
      return;
    }
    setSaving(true);
    setErrors({});
    try {
      const data = await apiClient.put<LeaveYearSetting>(
        "/leave-year-setting",
        buildLeaveYearSettingPayload(values),
      );
      setSetting(data);
      toast({ title: "Leave year setting saved", variant: "success" });
    } catch (err) {
      toast({
        title: "Could not save leave year setting",
        description: describeApiError(err),
        variant: "danger",
      });
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Leave Year"
        description="The 12-month period leave balances and yearly accrual/carry-forward run against — one setting per company (client spec §10)."
      />

      <Card>
        <CardContent className="space-y-4 pt-6">
          {loading ? <LoadingState label="Loading leave year setting…" /> : null}
          {error && !loading ? (
            <ErrorState
              message={
                error.status === 403
                  ? "You do not have permission to view this setting."
                  : error.message
              }
              onRetry={() => void load()}
            />
          ) : null}
          {!loading && !error && setting ? (
            <>
              <FormField id="leave-year-type" label="Leave year type" required>
                <NativeSelect
                  value={values.leaveYearType}
                  disabled={!canManage}
                  onChange={(e) =>
                    setValues((c) => ({
                      ...c,
                      leaveYearType: e.target.value as LeaveYearFormValues["leaveYearType"],
                    }))
                  }
                >
                  {LEAVE_YEAR_TYPES.map((type) => (
                    <option key={type} value={type}>
                      {LEAVE_YEAR_TYPE_LABELS[type] ?? type}
                    </option>
                  ))}
                </NativeSelect>
              </FormField>

              {values.leaveYearType === "CUSTOM" ? (
                <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                  <FormField
                    id="leave-year-start-month"
                    label="Start month"
                    required
                    error={errors.startMonth}
                    description="1 = January … 12 = December."
                  >
                    <Input
                      value={values.startMonth}
                      disabled={!canManage}
                      onChange={(e) => setValues((c) => ({ ...c, startMonth: e.target.value }))}
                      placeholder="7"
                    />
                  </FormField>
                  <FormField
                    id="leave-year-start-day"
                    label="Start day"
                    required
                    error={errors.startDay}
                  >
                    <Input
                      value={values.startDay}
                      disabled={!canManage}
                      onChange={(e) => setValues((c) => ({ ...c, startDay: e.target.value }))}
                      placeholder="1"
                    />
                  </FormField>
                </div>
              ) : null}

              {values.leaveYearType === "ANNIVERSARY" ? (
                <p className="text-sm text-foreground-muted">
                  Each employee's leave year starts on their own joining-date anniversary — there
                  is no single company-wide start date for this option.
                </p>
              ) : null}

              {canManage ? (
                <div>
                  <Button type="button" onClick={() => void handleSave()} disabled={saving}>
                    {saving ? "Saving…" : "Save"}
                  </Button>
                </div>
              ) : null}
            </>
          ) : null}
        </CardContent>
      </Card>
    </div>
  );
}
