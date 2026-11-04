"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { FormField } from "@/components/common/form-field";
import { PageHeader } from "@/components/common/page-header";
import { useToast } from "@/components/common/toast";
import type {
  PolicyBase,
  PolicyKindConfig,
  PolicyVersionBase,
} from "@/components/policy/policy-kind-config";
import {
  PublishAssignDialog,
  type PublishChoice,
} from "@/components/policy-assignment/publish-assign-dialog";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/native-select";
import { apiClient } from "@/lib/api/client";
import { ApiError, describeApiError, getFieldError } from "@/lib/api/errors";
import { businessToday } from "@/lib/attendance/format";
import { useAuth } from "@/lib/auth/auth-context";
import { useLeaveTypes } from "@/lib/leave-type/use-leave-types";
import { cn } from "@/lib/utils";

export function NewPolicyPage<
  P extends PolicyBase,
  V extends PolicyVersionBase,
  F extends { effectiveFrom: string },
  E extends object,
  C,
>({ config }: { config: PolicyKindConfig<P, V, F, E, C> }) {
  const router = useRouter();
  const { toast } = useToast();
  const { user } = useAuth();
  const today = businessToday(user?.company_timezone ?? "Asia/Kolkata");
  const first = config.templates[0];
  const leaveTypes = useLeaveTypes(Boolean(config.leaveTyped));
  const [leaveTypeId, setLeaveTypeId] = useState("");
  const [leaveTypeError, setLeaveTypeError] = useState<string | undefined>();

  const [templateKey, setTemplateKey] = useState(first.key);
  const [name, setName] = useState(first.defaultName);
  const [rules, setRules] = useState<F>(first.values);
  const [nameError, setNameError] = useState<string | undefined>();
  const [ruleErrors, setRuleErrors] = useState<E>({} as E);
  const [context, setContext] = useState<C | null>(null);
  const [publishOpen, setPublishOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [publishError, setPublishError] = useState<string | null>(null);

  const { loadContext } = config;
  useEffect(() => {
    if (!loadContext) return;
    loadContext()
      .then(setContext)
      .catch(() => setContext(null));
  }, [loadContext]);

  function chooseTemplate(key: string) {
    const template = config.templates.find((t) => t.key === key);
    if (!template) return;
    const nameIsUntouched = config.templates.some(
      (t) => t.key === templateKey && t.defaultName === name,
    );
    setTemplateKey(key);
    setRules(template.values);
    setRuleErrors({} as E);
    if (nameIsUntouched) setName(template.defaultName);
  }

  function checkName(): boolean {
    const missing = !name.trim();
    setNameError(missing ? "Name is required." : undefined);
    const noType = Boolean(config.leaveTyped) && !leaveTypeId;
    setLeaveTypeError(noType ? "Choose a leave type." : undefined);
    return !missing && !noType;
  }

  async function save(choice: PublishChoice | null) {
    setSaving(true);
    setPublishError(null);
    try {
      const data = await apiClient.post<{ policy: P }>(`${config.path}/setup`, {
        ...(config.leaveTyped ? { leave_type_id: leaveTypeId } : {}),
        name: name.trim(),
        rules: config.toPayload({ ...rules, effectiveFrom: choice?.effectiveFrom ?? "" }),
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
      toast({ title: choice ? "Policy published" : "Draft saved", variant: "success" });
      router.push(`/app${config.path}/${data.policy.id}`);
    } catch (err) {
      if (err instanceof ApiError && err.status === 422) {
        const nameProblem = getFieldError(err.details, "name");
        if (nameProblem) setNameError(nameProblem);
        const typeProblem = getFieldError(err.details, "leave_type_id");
        if (typeProblem) setLeaveTypeError(typeProblem);
        setRuleErrors(config.mapApiErrors(err.details));
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

  function hasErrors(errors: E): boolean {
    return Object.keys(errors).length > 0;
  }

  function handleSaveDraft() {
    const errors = config.validateDraft(rules);
    setRuleErrors(errors);
    if (!checkName() || hasErrors(errors)) {
      toast({ title: "Fix the highlighted fields", variant: "danger" });
      return;
    }
    void save(null);
  }

  function handlePublish() {
    const errors = config.validateForPublish(rules);
    setRuleErrors(errors);
    if (!checkName() || hasErrors(errors)) {
      toast({ title: "Fix the highlighted fields", variant: "danger" });
      return;
    }
    setPublishError(null);
    setPublishOpen(true);
  }

  const Form = config.Form;

  return (
    <div className="space-y-6">
      <PageHeader
        backHref={`/app${config.path}`}
        backLabel={config.pluralLabel}
        title={`New ${config.singularLabel}`}
        description="Start from a template, change what you need, and publish."
      />

      <Card>
        <CardContent className="space-y-3 pt-6">
          <h2 className="text-sm font-medium text-foreground">Start from</h2>
          <div className="grid gap-3 sm:grid-cols-2" role="radiogroup" aria-label="Start from">
            {config.templates.map((template) => (
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
                  name="policy-template"
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
          {config.leaveTyped ? (
            <FormField
              id="policy-leave-type"
              label="Leave type"
              required
              error={leaveTypeError}
              description="Each policy covers one leave type, and this can't be changed later."
            >
              <NativeSelect value={leaveTypeId} onChange={(e) => setLeaveTypeId(e.target.value)}>
                <option value="">Choose…</option>
                {leaveTypes
                  .filter((type) => type.is_active)
                  .map((type) => (
                    <option key={type.id} value={type.id}>
                      {type.name} ({type.code})
                    </option>
                  ))}
              </NativeSelect>
            </FormField>
          ) : null}
          <FormField id="policy-name" label="Policy name" required error={nameError}>
            <Input value={name} onChange={(e) => setName(e.target.value)} />
          </FormField>
          <Form values={rules} errors={ruleErrors} onChange={setRules} context={context} />
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
          policyKind={config.kind}
          leaveTypeId={config.leaveTyped ? leaveTypeId : null}
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
