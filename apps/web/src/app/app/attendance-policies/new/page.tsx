"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { AttendancePolicyForm } from "@/components/attendance-policy/attendance-policy-form";
import { AttendancePolicyVersionForm } from "@/components/attendance-policy/attendance-policy-version-form";
import { PageHeader } from "@/components/common/page-header";
import { useToast } from "@/components/common/toast";
import {
  PublishAssignDialog,
  type PublishChoice,
} from "@/components/policy-assignment/publish-assign-dialog";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { apiClient } from "@/lib/api/client";
import { ApiError, describeApiError, getFieldError } from "@/lib/api/errors";
import { ATTENDANCE_POLICY_TEMPLATES } from "@/lib/attendance-policy/templates";
import type { AttendancePolicy } from "@/lib/attendance-policy/types";
import {
  buildAttendancePolicyVersionPayload,
  mapAttendancePolicyVersionApiErrors,
  validateAttendancePolicyForm,
  validateAttendancePolicyForPublish,
  validateAttendancePolicyVersionForm,
  type AttendancePolicyFormErrors,
  type AttendancePolicyVersionFormErrors,
} from "@/lib/attendance-policy/validate-attendance-policy";
import { businessToday } from "@/lib/attendance/format";
import { useAuth } from "@/lib/auth/auth-context";
import { cn } from "@/lib/utils";

const FIRST = ATTENDANCE_POLICY_TEMPLATES[0];

export default function NewAttendancePolicyPage() {
  const router = useRouter();
  const { toast } = useToast();
  const { user } = useAuth();
  const today = businessToday(user?.company_timezone ?? "Asia/Kolkata");

  const [templateKey, setTemplateKey] = useState(FIRST.key);
  const [name, setName] = useState(FIRST.defaultName);
  const [rules, setRules] = useState(FIRST.values);
  const [nameErrors, setNameErrors] = useState<AttendancePolicyFormErrors>({});
  const [ruleErrors, setRuleErrors] = useState<AttendancePolicyVersionFormErrors>({});
  const [shiftTypes, setShiftTypes] = useState<string[] | null>(null);
  const [publishOpen, setPublishOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [publishError, setPublishError] = useState<string | null>(null);

  useEffect(() => {
    apiClient
      .get<{ shift_types_in_use: string[] }>("/attendance-policies/form-context")
      .then((context) => setShiftTypes(context.shift_types_in_use))
      .catch(() => setShiftTypes(null));
  }, []);

  function chooseTemplate(key: string) {
    const template = ATTENDANCE_POLICY_TEMPLATES.find((t) => t.key === key);
    if (!template) return;
    const nameIsUntouched = ATTENDANCE_POLICY_TEMPLATES.some(
      (t) => t.key === templateKey && t.defaultName === name,
    );
    setTemplateKey(key);
    setRules(template.values);
    setRuleErrors({});
    if (nameIsUntouched) setName(template.defaultName);
  }

  function checkName(): boolean {
    const errors = validateAttendancePolicyForm({ name });
    setNameErrors(errors);
    return Object.keys(errors).length === 0;
  }

  async function save(choice: PublishChoice | null) {
    setSaving(true);
    setPublishError(null);
    try {
      const data = await apiClient.post<{ policy: AttendancePolicy }>("/attendance-policies/setup", {
        name: name.trim(),
        rules: buildAttendancePolicyVersionPayload({
          ...rules,
          effectiveFrom: choice?.effectiveFrom ?? "",
        }),
        publish: choice !== null,
        publish_reason: choice?.reason || null,
        assign: choice?.assign
          ? {
              scope_type: choice.assign.scopeType,
              scope_id: choice.assign.scopeId,
              expected_version: choice.assign.expectedVersion,
            }
          : null,
      });
      toast({
        title: choice ? "Policy published" : "Draft saved",
        variant: "success",
      });
      router.push(`/app/attendance-policies/${data.policy.id}`);
    } catch (err) {
      if (err instanceof ApiError && err.status === 422) {
        const nameError = getFieldError(err.details, "name");
        if (nameError) setNameErrors({ name: nameError });
        setRuleErrors(mapAttendancePolicyVersionApiErrors(err.details));
      }
      if (choice) {
        setPublishError(`Nothing was saved. ${describeApiError(err)}`);
      } else {
        toast({ title: "Could not save", description: describeApiError(err), variant: "danger" });
      }
    } finally {
      setSaving(false);
    }
  }

  function handleSaveDraft() {
    const errors = validateAttendancePolicyVersionForm(rules);
    setRuleErrors(errors);
    if (!checkName() || Object.keys(errors).length > 0) {
      toast({ title: "Fix the highlighted fields", variant: "danger" });
      return;
    }
    void save(null);
  }

  function handlePublish() {
    const errors = validateAttendancePolicyForPublish(rules);
    setRuleErrors(errors);
    if (!checkName() || Object.keys(errors).length > 0) {
      toast({ title: "Fix the highlighted fields", variant: "danger" });
      return;
    }
    setPublishError(null);
    setPublishOpen(true);
  }

  return (
    <div className="space-y-6">
      <PageHeader
        backHref="/app/attendance-policies"
        backLabel="Attendance Policies"
        title="New attendance policy"
        description="Start from a template, change what you need, and publish."
      />

      <Card>
        <CardContent className="space-y-3 pt-6">
          <h2 className="text-sm font-medium text-foreground">Start from</h2>
          <div className="grid gap-3 sm:grid-cols-2" role="radiogroup" aria-label="Start from">
            {ATTENDANCE_POLICY_TEMPLATES.map((template) => (
              <label
                key={template.key}
                className={cn(
                  "flex cursor-pointer items-start gap-3 rounded-lg border p-3 transition-colors",
                  templateKey === template.key
                    ? "border-primary bg-primary-subtle"
                    : "border-border hover:border-primary/40",
                )}
              >
                <input
                  type="radio"
                  name="attendance-policy-template"
                  className="mt-1"
                  checked={templateKey === template.key}
                  onChange={() => chooseTemplate(template.key)}
                />
                <span>
                  <span className="block text-sm font-medium text-foreground">{template.label}</span>
                  <span className="block text-xs text-foreground-secondary">
                    {template.description}
                  </span>
                </span>
              </label>
            ))}
          </div>
          <p className="text-xs text-foreground-muted">
            Choosing a template replaces the rules below.
          </p>
        </CardContent>
      </Card>

      <Card>
        <CardContent className="space-y-6 pt-6">
          <AttendancePolicyForm
            values={{ name }}
            errors={nameErrors}
            onChange={(values) => setName(values.name)}
          />
          <AttendancePolicyVersionForm
            values={rules}
            errors={ruleErrors}
            onChange={setRules}
            shiftTypesInUse={shiftTypes}
          />
          <div className="flex flex-wrap gap-2 border-t border-border pt-4">
            <Button type="button" onClick={handlePublish} disabled={saving}>
              Save &amp; publish…
            </Button>
            <Button type="button" variant="outline" onClick={handleSaveDraft} disabled={saving}>
              {saving && !publishOpen ? "Saving…" : "Save as draft"}
            </Button>
          </div>
        </CardContent>
      </Card>

      {publishOpen ? (
        <PublishAssignDialog
          policyKind="ATTENDANCE_POLICY"
          today={today}
          initialDate={today}
          notBefore={null}
          saving={saving}
          error={publishError}
          onCancel={() => setPublishOpen(false)}
          onConfirm={(choice) => void save(choice)}
        />
      ) : null}
    </div>
  );
}
