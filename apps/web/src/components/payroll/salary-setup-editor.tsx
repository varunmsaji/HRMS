"use client";

import {
  useCallback,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

import { FormField } from "@/components/common/form-field";
import { LoadingState } from "@/components/common/loading-state";
import { useToast } from "@/components/common/toast";
import { SalaryBreakupTable } from "@/components/payroll/salary-breakup-table";
import {
  StructureLinesEditor,
  toInput,
  toRow,
  type LineRow,
} from "@/components/payroll/structure-lines-editor";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/native-select";
import { apiClient } from "@/lib/api/client";
import { describeApiError } from "@/lib/api/errors";
import { REVISION_TYPE_VALUES, type RevisionType } from "@/lib/employee/types";
import { REVISION_TYPE_LABELS } from "@/lib/employee/validate-compensation";
import {
  currentVersion,
  formatInr,
  rupeesToMinor,
  type EmployeeSalarySetup,
  type EmployeeSalarySetupPreview,
  type SalaryComponent,
  type SalaryStructure,
} from "@/lib/payroll/types";

const PREVIEW_DELAY_MS = 400;

function templateRows(structure: SalaryStructure | undefined): LineRow[] {
  return structure ? (currentVersion(structure)?.lines.map(toRow) ?? []) : [];
}

/** What the rows pay, ignoring order and fields their calculation does not use — equal keys,
 * equal pay. */
function payKey(rows: LineRow[]): string {
  return JSON.stringify(
    rows
      .map((row, i) => {
        const input = toInput(row, i);
        return [
          input.salary_component_id,
          input.calculation_type,
          input.percentage === null ? null : Number(input.percentage),
          input.amount_monthly_minor,
          input.base_salary_component_id,
          input.max_monthly_minor,
          input.applies_when,
        ];
      })
      .sort((a, b) => String(a[0]).localeCompare(String(b[0]))),
  );
}

function rupees(minor: number | null): string {
  return minor === null ? "" : String(minor / 100);
}

/** The employee's CTC and salary structure edited together: pick a company template, change any
 * percentage for this employee, and every component's amount fills in as you type. Saving
 * records the CTC (when it changed) and the structure from one effective date; changed lines
 * become this employee's own structure and the template is left as it is. */
export function SalarySetupEditor({
  employeeId,
  today,
  onSaved,
  fallback,
}: {
  employeeId: string;
  today: string;
  onSaved: () => void;
  /** Shown instead for a daily-wage employee, or one not employed today. */
  fallback: ReactNode;
}) {
  const { toast } = useToast();
  const [setup, setSetup] = useState<EmployeeSalarySetup | null>(null);
  const [templates, setTemplates] = useState<SalaryStructure[]>([]);
  const [components, setComponents] = useState<SalaryComponent[]>([]);
  const [loadError, setLoadError] = useState<string | null>(null);

  const [templateId, setTemplateId] = useState("");
  const [ctc, setCtc] = useState("");
  const [rows, setRows] = useState<LineRow[]>([]);
  const [effectiveFrom, setEffectiveFrom] = useState(today);
  const [reason, setReason] = useState("");
  const [revisionType, setRevisionType] = useState<RevisionType>("ANNUAL");
  const [preview, setPreview] = useState<EmployeeSalarySetupPreview | null>(
    null,
  );
  const [previewError, setPreviewError] = useState<string | null>(null);
  const [formError, setFormError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const apply = useCallback(
    (data: EmployeeSalarySetup, structures: SalaryStructure[]) => {
      setSetup(data);
      const usable = structures.filter((s) => s.is_active && currentVersion(s));
      const template =
        usable.find((s) => s.id === data.template_structure_id) ??
        usable[0] ??
        undefined;
      setTemplateId(template?.id ?? "");
      setRows(
        data.lines.length > 0 ? data.lines.map(toRow) : templateRows(template),
      );
      setCtc(rupees(data.annual_ctc_minor));
      setRevisionType(data.annual_ctc_minor === null ? "JOINING" : "ANNUAL");
      setReason("");
      setFormError(null);
    },
    [],
  );

  useEffect(() => {
    let cancelled = false;
    Promise.all([
      apiClient.get<EmployeeSalarySetup>(
        `/employees/${employeeId}/salary/setup?as_of=${today}`,
      ),
      apiClient.get<SalaryStructure[]>("/payroll/salary-structures"),
      apiClient.get<SalaryComponent[]>("/payroll/salary-components"),
    ])
      .then(([data, structures, componentList]) => {
        if (cancelled) return;
        setTemplates(structures);
        setComponents(componentList);
        apply(data, structures);
      })
      .catch((err: unknown) => {
        if (!cancelled) setLoadError(describeApiError(err));
      });
    return () => {
      cancelled = true;
    };
  }, [apply, employeeId, today]);

  const usableTemplates = templates.filter(
    (s) => s.is_active && currentVersion(s),
  );
  const template = usableTemplates.find((s) => s.id === templateId);
  const annualMinor = rupeesToMinor(ctc);
  const customised =
    template !== undefined && payKey(rows) !== payKey(templateRows(template));
  const ctcChanged =
    annualMinor !== null && annualMinor !== (setup?.annual_ctc_minor ?? null);
  const dirty =
    setup !== null &&
    (ctcChanged ||
      templateId !== (setup.template_structure_id ?? "") ||
      payKey(rows) !== payKey(setup.lines.map(toRow)));

  // Live auto-fill: recompute the breakup shortly after the CTC or a line stops changing.
  const lineInputs = useMemo(() => rows.map(toInput), [rows]);
  const complete = rows.length > 0 && rows.every((r) => r.componentId);
  useEffect(() => {
    if (!setup || annualMinor === null || !complete) return;
    let cancelled = false;
    const timer = setTimeout(() => {
      apiClient
        .post<EmployeeSalarySetupPreview>(
          `/employees/${employeeId}/salary/setup/preview`,
          {
            annual_ctc_minor: annualMinor,
            as_of: effectiveFrom || today,
            lines: lineInputs,
          },
        )
        .then((data) => {
          if (cancelled) return;
          setPreview(data);
          setPreviewError(null);
        })
        .catch((err: unknown) => {
          if (cancelled) return;
          setPreview(null);
          setPreviewError(describeApiError(err));
        });
    }, PREVIEW_DELAY_MS);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [
    annualMinor,
    complete,
    effectiveFrom,
    employeeId,
    lineInputs,
    setup,
    today,
  ]);

  const amounts = useMemo(() => {
    if (!preview) return {};
    const idByCode = new Map(components.map((c) => [c.code, c.id]));
    const result: Record<string, number> = {};
    for (const line of preview.breakup.lines) {
      const id = idByCode.get(line.component_code);
      if (id) result[id] = line.monthly_minor;
    }
    return result;
  }, [components, preview]);

  async function handleSave() {
    if (annualMinor === null) {
      setFormError("Enter the annual CTC in rupees.");
      return;
    }
    setSaving(true);
    setFormError(null);
    try {
      const data = await apiClient.post<EmployeeSalarySetup>(
        `/employees/${employeeId}/salary/setup`,
        {
          effective_from: effectiveFrom,
          reason: reason.trim(),
          template_structure_id: templateId,
          lines: lineInputs,
          ...(ctcChanged
            ? { annual_ctc_minor: annualMinor, revision_type: revisionType }
            : {}),
        },
      );
      apply(data, templates);
      toast({ title: "Salary saved", variant: "success" });
      onSaved();
    } catch (err) {
      setFormError(describeApiError(err));
    } finally {
      setSaving(false);
    }
  }

  if (loadError) return <p className="text-sm text-danger">{loadError}</p>;
  if (!setup) return <LoadingState label="Loading salary…" />;
  if (setup.pay_basis !== "MONTHLY") return <>{fallback}</>;

  return (
    <Card>
      <CardHeader className="flex-row flex-wrap items-center justify-between gap-2 space-y-0">
        <CardTitle>Salary setup</CardTitle>
        {template ? (
          customised ? (
            <Badge variant="warning" dot>
              Customised for this employee
            </Badge>
          ) : (
            <Badge variant="success" dot>
              Same as {template.name}
            </Badge>
          )
        ) : null}
      </CardHeader>
      <CardContent className="space-y-5">
        <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
          <FormField
            id="setup-ctc"
            label="Annual CTC (₹)"
            required
            description={
              annualMinor !== null
                ? `${formatInr(Math.round(annualMinor / 12))} a month`
                : undefined
            }
          >
            <Input
              inputMode="decimal"
              value={ctc}
              onChange={(e) => setCtc(e.target.value)}
            />
          </FormField>
          <FormField
            id="setup-template"
            label="Start from structure"
            description="Changes below apply to this employee only."
          >
            <NativeSelect
              value={templateId}
              onChange={(e) => {
                setTemplateId(e.target.value);
                setRows(
                  templateRows(
                    usableTemplates.find((s) => s.id === e.target.value),
                  ),
                );
              }}
            >
              {usableTemplates.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name}
                </option>
              ))}
            </NativeSelect>
          </FormField>
          <div className="flex items-end">
            <Button
              type="button"
              variant="outline"
              disabled={!customised}
              onClick={() => setRows(templateRows(template))}
            >
              Reset to {template?.name ?? "template"}
            </Button>
          </div>
        </div>

        <StructureLinesEditor
          rows={rows}
          onChange={setRows}
          components={components}
          amounts={amounts}
        />
        <p className="text-xs text-foreground-muted">
          Exactly one earning must be &quot;Balance of gross&quot;. Employer
          contributions are part of CTC, so gross = CTC − employer
          contributions.{" "}
          {setup.pf_applicable
            ? "PF applies to this employee."
            : "PF does not apply to this employee."}
        </p>

        {previewError ? (
          <p role="alert" className="text-sm text-danger">
            {previewError}
          </p>
        ) : null}
        {preview ? <SalaryBreakupTable breakup={preview.breakup} /> : null}

        <div className="grid grid-cols-1 gap-4 border-t border-border pt-4 md:grid-cols-3">
          <FormField id="setup-effective-from" label="Effective from" required>
            <Input
              type="date"
              value={effectiveFrom}
              onChange={(e) => setEffectiveFrom(e.target.value)}
            />
          </FormField>
          {ctcChanged ? (
            <FormField
              id="setup-revision-type"
              label="Why the CTC is changing"
              required
            >
              <NativeSelect
                value={revisionType}
                onChange={(e) =>
                  setRevisionType(e.target.value as RevisionType)
                }
              >
                {REVISION_TYPE_VALUES.map((value) => (
                  <option key={value} value={value}>
                    {REVISION_TYPE_LABELS[value]}
                  </option>
                ))}
              </NativeSelect>
            </FormField>
          ) : null}
          <FormField id="setup-reason" label="Reason" required>
            <Input
              value={reason}
              maxLength={500}
              onChange={(e) => setReason(e.target.value)}
            />
          </FormField>
        </div>
        {formError ? (
          <p role="alert" className="text-sm text-danger">
            {formError}
          </p>
        ) : null}
        <div className="flex justify-end">
          <Button
            type="button"
            onClick={() => void handleSave()}
            disabled={
              saving ||
              !dirty ||
              !reason.trim() ||
              !effectiveFrom ||
              !templateId ||
              !complete
            }
          >
            {saving ? "Saving…" : "Save salary"}
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}
