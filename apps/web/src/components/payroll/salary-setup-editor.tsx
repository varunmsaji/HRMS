"use client";

import {
  useCallback,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

import { LoadingState } from "@/components/common/loading-state";
import { useToast } from "@/components/common/toast";
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
/** "a", "a and b", "a, b and c". */
export function joinList(items: string[]): string {
  if (items.length <= 1) return items.join("");
  return `${items.slice(0, -1).join(", ")} and ${items[items.length - 1]}`;
}

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
  // Set when Save is pressed with something missing: from then on the missing fields are marked.
  const [showMissing, setShowMissing] = useState(false);
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
      setShowMissing(false);
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

  // What still has to be filled in before the salary can be saved, in form order.
  const missing = {
    ctc: annualMinor === null,
    template: !templateId,
    lines: !complete,
    effectiveFrom: !effectiveFrom,
    reason: !reason.trim(),
  };
  const missingLabels = [
    missing.ctc && "the annual CTC",
    missing.template && "a structure",
    missing.lines && "a component on every pay line",
    missing.effectiveFrom && "the effective-from date",
    missing.reason && "a reason",
  ].filter((label): label is string => Boolean(label));
  const flag = (isMissing: boolean) => showMissing && isMissing;
  // Live: shrinks as each missing field is filled in, and disappears once nothing is missing.
  const shownError =
    showMissing && missingLabels.length > 0
      ? `Before saving, add ${joinList(missingLabels)}.`
      : formError;

  async function handleSave() {
    if (missingLabels.length > 0) {
      setShowMissing(true);
      setFormError(null);
      return;
    }
    if (!dirty) {
      setFormError("Nothing has changed yet. Edit the CTC, the structure or a pay line first.");
      return;
    }
    if (annualMinor === null) return;
    setShowMissing(false);
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

  const breakup = preview?.breakup ?? null;
  const label = "mb-1 block text-xs font-medium text-foreground-secondary";

  return (
    <Card>
      <CardHeader className="flex-row flex-wrap items-center justify-between gap-2 space-y-0 pb-3">
        <CardTitle className="text-base">Salary setup</CardTitle>
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
      <CardContent className="space-y-4">
        <div className="grid grid-cols-1 gap-3 rounded-md bg-surface-secondary/50 p-3 sm:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_auto]">
          <div>
            <label htmlFor="setup-ctc" className={label}>
              Annual CTC (₹)
            </label>
            <Input
              id="setup-ctc"
              className="h-9"
              aria-invalid={flag(missing.ctc)}
              inputMode="decimal"
              value={ctc}
              onChange={(e) => setCtc(e.target.value)}
            />
          </div>
          <div>
            <div className="flex items-baseline justify-between gap-2">
              <label htmlFor="setup-template" className={label}>
                Structure
              </label>
              {customised ? (
                <button
                  type="button"
                  className="text-xs text-primary hover:underline"
                  onClick={() => setRows(templateRows(template))}
                >
                  Reset to {template?.name}
                </button>
              ) : null}
            </div>
            <NativeSelect
              id="setup-template"
              className="h-9"
              aria-invalid={flag(missing.template)}
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
          </div>
          <dl className="flex gap-5 sm:pl-2">
            <div>
              <dt className={label}>CTC a month</dt>
              <dd className="text-lg font-semibold tabular-nums text-foreground">
                {annualMinor !== null
                  ? formatInr(Math.round(annualMinor / 12))
                  : "—"}
              </dd>
            </div>
            <div>
              <dt className={label}>Gross a month</dt>
              <dd className="text-lg font-semibold tabular-nums text-foreground">
                {breakup ? formatInr(breakup.gross_monthly_minor) : "—"}
              </dd>
            </div>
          </dl>
        </div>

        <StructureLinesEditor
          rows={rows}
          onChange={setRows}
          components={components}
          amounts={amounts}
          breakup={breakup}
          highlightMissing={showMissing}
        />
        {previewError ? (
          <p role="alert" className="text-sm text-danger">
            {previewError}
          </p>
        ) : (
          <p className="text-xs text-foreground-muted">
            One earning takes the rest of gross; employer contributions sit
            inside CTC. PF {setup.pf_applicable ? "applies" : "does not apply"}{" "}
            to this employee.
          </p>
        )}

        <div className="flex flex-wrap items-end gap-3 border-t border-border pt-4">
          <div className="w-40">
            <label htmlFor="setup-effective-from" className={label}>
              Effective from
            </label>
            <Input
              id="setup-effective-from"
              type="date"
              className="h-9"
              aria-invalid={flag(missing.effectiveFrom)}
              value={effectiveFrom}
              onChange={(e) => setEffectiveFrom(e.target.value)}
            />
          </div>
          {ctcChanged ? (
            <div className="w-48">
              <label htmlFor="setup-revision-type" className={label}>
                Why the CTC is changing
              </label>
              <NativeSelect
                id="setup-revision-type"
                className="h-9"
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
            </div>
          ) : null}
          <div className="min-w-48 flex-1">
            <label htmlFor="setup-reason" className={label}>
              Reason
            </label>
            <Input
              id="setup-reason"
              className="h-9"
              aria-invalid={flag(missing.reason)}
              placeholder="e.g. Annual review"
              value={reason}
              maxLength={500}
              onChange={(e) => setReason(e.target.value)}
            />
          </div>
          <Button
            type="button"
            onClick={() => void handleSave()}
            disabled={saving}
          >
            {saving ? "Saving…" : "Save salary"}
          </Button>
        </div>
        {shownError ? (
          <p role="alert" className="text-sm text-danger">
            {shownError}
          </p>
        ) : null}
      </CardContent>
    </Card>
  );
}
