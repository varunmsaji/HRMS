"use client";

import { Plus, Trash2 } from "lucide-react";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";

import { ErrorState } from "@/components/common/error-state";
import { FormField } from "@/components/common/form-field";
import { LoadingState } from "@/components/common/loading-state";
import { PageHeader } from "@/components/common/page-header";
import { useToast } from "@/components/common/toast";
import { SalaryBreakupTable } from "@/components/payroll/salary-breakup-table";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/native-select";
import {
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableHeader,
  TableRow,
  TableToolbar,
} from "@/components/ui/table";
import { apiClient } from "@/lib/api/client";
import { ApiError, describeApiError } from "@/lib/api/errors";
import { usePermissions } from "@/lib/auth/use-permissions";
import { formatCompanyDate } from "@/lib/dates/company-date";
import { useCompanyDatePattern } from "@/lib/dates/use-company-date";
import {
  APPLIES_WHEN,
  APPLIES_WHEN_LABELS,
  CALCULATION_TYPE_LABELS,
  CALCULATION_TYPES,
  currentVersion,
  draftVersion,
  formatInr,
  rupeesToMinor,
  type AppliesWhen,
  type CalculationType,
  type SalaryBreakup,
  type SalaryComponent,
  type SalaryStructure,
  type SalaryStructureLine,
  type SalaryStructureLineInput,
  type SalaryStructureVersion,
} from "@/lib/payroll/types";

interface LineRow {
  componentId: string;
  calculationType: CalculationType;
  percentage: string;
  amount: string;
  baseId: string;
  cap: string;
  appliesWhen: AppliesWhen;
}

function toRow(line: SalaryStructureLine): LineRow {
  return {
    componentId: line.salary_component_id,
    calculationType: line.calculation_type,
    percentage: line.percentage ?? "",
    amount: line.amount_monthly_minor !== null ? String(line.amount_monthly_minor / 100) : "",
    baseId: line.base_salary_component_id ?? "",
    cap: line.max_monthly_minor !== null ? String(line.max_monthly_minor / 100) : "",
    appliesWhen: line.applies_when,
  };
}

function toInput(row: LineRow, index: number): SalaryStructureLineInput {
  const needsPercentage = row.calculationType.startsWith("PERCENTAGE");
  return {
    salary_component_id: row.componentId,
    calculation_type: row.calculationType,
    percentage: needsPercentage && row.percentage ? row.percentage : null,
    amount_monthly_minor: row.calculationType === "FIXED" ? rupeesToMinor(row.amount) : null,
    base_salary_component_id:
      row.calculationType === "PERCENTAGE_OF_COMPONENT" && row.baseId ? row.baseId : null,
    max_monthly_minor: row.cap ? rupeesToMinor(row.cap) : null,
    applies_when: row.appliesWhen,
    display_order: (index + 1) * 10,
  };
}

function describeLine(line: SalaryStructureLine, components: SalaryComponent[]): string {
  const base = components.find((c) => c.id === line.base_salary_component_id);
  let text: string;
  switch (line.calculation_type) {
    case "FIXED":
      text = formatInr(line.amount_monthly_minor ?? 0);
      break;
    case "PERCENTAGE_OF_CTC":
      text = `${line.percentage}% of monthly CTC`;
      break;
    case "PERCENTAGE_OF_GROSS":
      text = `${line.percentage}% of gross`;
      break;
    case "PERCENTAGE_OF_COMPONENT":
      text = `${line.percentage}% of ${base?.name ?? "?"}`;
      break;
    default:
      text = "Balance of gross";
  }
  if (line.max_monthly_minor !== null) text += `, at most ${formatInr(line.max_monthly_minor)}`;
  if (line.applies_when !== "ALWAYS")
    text += ` (${APPLIES_WHEN_LABELS[line.applies_when].toLowerCase()})`;
  return text;
}

/** Payroll Phase 5.1 — one salary structure: its published versions (read-only) and its draft
 * (editable), with a live CTC breakup preview of whichever version is selected. */
export default function SalaryStructureDetailPage() {
  const params = useParams<{ id: string }>();
  const { toast } = useToast();
  const { can } = usePermissions();
  const datePattern = useCompanyDatePattern();
  const canManage = can("PAYROLL.SETUP_MANAGE");

  const [structure, setStructure] = useState<SalaryStructure | null>(null);
  const [components, setComponents] = useState<SalaryComponent[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<ApiError | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [rows, setRows] = useState<LineRow[]>([]);
  const [saving, setSaving] = useState(false);
  const [publishOpen, setPublishOpen] = useState(false);
  const [publishDate, setPublishDate] = useState("");
  const [ctc, setCtc] = useState("1200000");
  const [pf, setPf] = useState(true);
  const [preview, setPreview] = useState<SalaryBreakup | null>(null);
  const [previewError, setPreviewError] = useState<string | null>(null);

  const apply = useCallback((data: SalaryStructure, keepSelection?: string | null) => {
    setStructure(data);
    const draft = draftVersion(data);
    const fallback = draft ?? currentVersion(data) ?? data.versions[0] ?? null;
    const selected = data.versions.find((v) => v.id === keepSelection) ?? fallback;
    setSelectedId(selected?.id ?? null);
    setRows((draft ?? selected)?.lines.map(toRow) ?? []);
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [data, componentList] = await Promise.all([
        apiClient.get<SalaryStructure>(`/payroll/salary-structures/${params.id}`),
        apiClient.get<SalaryComponent[]>("/payroll/salary-components"),
      ]);
      setComponents(componentList);
      apply(data);
    } catch (err) {
      setError(
        err instanceof ApiError
          ? err
          : new ApiError({ status: 0, code: "UNKNOWN_ERROR", message: "Something went wrong." }),
      );
    } finally {
      setLoading(false);
    }
  }, [apply, params.id]);

  useEffect(() => {
    void load();
  }, [load]);

  const selected: SalaryStructureVersion | null =
    structure?.versions.find((v) => v.id === selectedId) ?? null;
  const draft = structure ? draftVersion(structure) : null;
  const editing = canManage && selected?.status === "DRAFT";
  const usable = components.filter((c) => c.is_active && c.component_type !== "DEDUCTION");
  const earnings = usable.filter((c) => c.component_type === "EARNING");

  const runPreview = useCallback(async () => {
    if (!structure || !selected) return;
    const annual = rupeesToMinor(ctc);
    if (!annual) {
      setPreviewError("Enter an annual CTC in rupees.");
      return;
    }
    setPreviewError(null);
    try {
      setPreview(
        await apiClient.post<SalaryBreakup>(
          `/payroll/salary-structures/${structure.id}/versions/${selected.id}/preview`,
          { annual_ctc_minor: annual, pf_applicable: pf },
        ),
      );
    } catch (err) {
      setPreview(null);
      setPreviewError(describeApiError(err));
    }
  }, [ctc, pf, selected, structure]);

  useEffect(() => {
    if (selected && selected.lines.length > 0) void runPreview();
    else setPreview(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selected?.id, selected?.version]);

  const dirty = useMemo(() => {
    if (!draft) return false;
    return JSON.stringify(draft.lines.map(toRow)) !== JSON.stringify(rows);
  }, [draft, rows]);

  async function run(
    action: () => Promise<SalaryStructure>,
    success: string,
    keepSelection = true,
  ) {
    setSaving(true);
    try {
      const data = await action();
      apply(data, keepSelection ? selectedId : null);
      toast({ title: success, variant: "success" });
      return true;
    } catch (err) {
      toast({ title: "Could not save", description: describeApiError(err), variant: "danger" });
      return false;
    } finally {
      setSaving(false);
    }
  }

  function updateRow(index: number, patch: Partial<LineRow>) {
    setRows(rows.map((row, i) => (i === index ? { ...row, ...patch } : row)));
  }

  if (loading) return <LoadingState label="Loading salary structure…" />;
  if (error || !structure) {
    return (
      <ErrorState
        message={error?.status === 404 ? "Salary structure not found." : (error?.message ?? "")}
        onRetry={() => void load()}
      />
    );
  }

  return (
    <div className="space-y-6">
      <PageHeader
        backHref="/app/payroll/salary-structures"
        backLabel="Salary Structures"
        title={structure.name}
        description={structure.description ?? structure.code}
        actions={
          canManage && !draft ? (
            <Button
              type="button"
              onClick={() =>
                void run(
                  () =>
                    apiClient.post<SalaryStructure>(
                      `/payroll/salary-structures/${structure.id}/versions`,
                      {},
                    ),
                  "Draft created from the current version",
                  false,
                )
              }
              disabled={saving}
            >
              Edit (new draft)
            </Button>
          ) : undefined
        }
      />

      <div className="flex flex-wrap gap-2">
        {structure.versions.map((version) => (
          <Button
            key={version.id}
            type="button"
            size="sm"
            variant={version.id === selectedId ? "default" : "outline"}
            onClick={() => {
              setSelectedId(version.id);
              setRows(version.lines.map(toRow));
            }}
          >
            v{version.version_number} ·{" "}
            {version.status === "DRAFT"
              ? "Draft"
              : `${formatCompanyDate(version.effective_from, datePattern)} → ${version.effective_to ? formatCompanyDate(version.effective_to, datePattern) : "now"}`}
          </Button>
        ))}
      </div>

      {selected ? (
        editing ? (
          <Card>
            <CardHeader className="flex-row flex-wrap items-center justify-between gap-2 space-y-0">
              <div className="flex items-center gap-2">
                <CardTitle>Components</CardTitle>
                <Badge variant="warning" dot>
                  Draft
                </Badge>
              </div>
              <div className="flex flex-wrap gap-2">
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  disabled={saving}
                  onClick={() =>
                    void run(
                      () =>
                        apiClient.delete<SalaryStructure>(
                          `/payroll/salary-structures/${structure.id}/versions/${selected.id}`,
                        ),
                      "Draft discarded",
                      false,
                    )
                  }
                >
                  Discard draft
                </Button>
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  disabled={saving || !dirty}
                  onClick={() =>
                    void run(
                      () =>
                        apiClient.put<SalaryStructure>(
                          `/payroll/salary-structures/${structure.id}/versions/${selected.id}/lines`,
                          { lines: rows.map(toInput) },
                          { ifMatch: String(selected.version) },
                        ),
                      "Draft saved",
                    )
                  }
                >
                  Save draft
                </Button>
                <Button
                  type="button"
                  size="sm"
                  disabled={saving || dirty || selected.lines.length === 0}
                  onClick={() => setPublishOpen(true)}
                >
                  Publish
                </Button>
              </div>
            </CardHeader>
            <CardContent className="space-y-3">
              {rows.map((row, index) => {
                const component = usable.find((c) => c.id === row.componentId);
                return (
                  <div
                    key={index}
                    className="grid grid-cols-1 gap-2 rounded-md border border-border bg-surface-secondary/30 p-3 md:grid-cols-6"
                  >
                    <NativeSelect
                      aria-label="Component"
                      value={row.componentId}
                      onChange={(e) => updateRow(index, { componentId: e.target.value })}
                    >
                      <option value="">Component…</option>
                      {usable.map((c) => (
                        <option key={c.id} value={c.id}>
                          {c.name}
                        </option>
                      ))}
                    </NativeSelect>
                    <NativeSelect
                      aria-label="Calculation"
                      value={row.calculationType}
                      onChange={(e) =>
                        updateRow(index, { calculationType: e.target.value as CalculationType })
                      }
                    >
                      {CALCULATION_TYPES.filter(
                        (t) =>
                          component?.component_type !== "EMPLOYER_CONTRIBUTION" ||
                          (t !== "BALANCING" && t !== "PERCENTAGE_OF_GROSS"),
                      ).map((t) => (
                        <option key={t} value={t}>
                          {CALCULATION_TYPE_LABELS[t]}
                        </option>
                      ))}
                    </NativeSelect>
                    {row.calculationType === "FIXED" ? (
                      <Input
                        aria-label="Monthly amount (₹)"
                        placeholder="₹ a month"
                        value={row.amount}
                        onChange={(e) => updateRow(index, { amount: e.target.value })}
                      />
                    ) : row.calculationType === "BALANCING" ? (
                      <div className="self-center text-xs text-foreground-muted">
                        Takes whatever remains of gross
                      </div>
                    ) : (
                      <Input
                        aria-label="Percentage"
                        placeholder="%"
                        value={row.percentage}
                        onChange={(e) => updateRow(index, { percentage: e.target.value })}
                      />
                    )}
                    {row.calculationType === "PERCENTAGE_OF_COMPONENT" ? (
                      <NativeSelect
                        aria-label="Of component"
                        value={row.baseId}
                        onChange={(e) => updateRow(index, { baseId: e.target.value })}
                      >
                        <option value="">Of…</option>
                        {earnings
                          .filter((c) => c.id !== row.componentId)
                          .map((c) => (
                            <option key={c.id} value={c.id}>
                              {c.name}
                            </option>
                          ))}
                      </NativeSelect>
                    ) : (
                      <div />
                    )}
                    <Input
                      aria-label="Monthly cap (₹)"
                      placeholder="Cap ₹ (optional)"
                      value={row.cap}
                      disabled={row.calculationType === "BALANCING"}
                      onChange={(e) => updateRow(index, { cap: e.target.value })}
                    />
                    <div className="flex gap-2">
                      <NativeSelect
                        aria-label="Applies"
                        value={row.appliesWhen}
                        onChange={(e) =>
                          updateRow(index, { appliesWhen: e.target.value as AppliesWhen })
                        }
                      >
                        {APPLIES_WHEN.map((a) => (
                          <option key={a} value={a}>
                            {APPLIES_WHEN_LABELS[a]}
                          </option>
                        ))}
                      </NativeSelect>
                      <Button
                        type="button"
                        variant="ghost"
                        size="icon"
                        aria-label="Remove line"
                        onClick={() => setRows(rows.filter((_, i) => i !== index))}
                      >
                        <Trash2 />
                      </Button>
                    </div>
                  </div>
                );
              })}
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() =>
                  setRows([
                    ...rows,
                    {
                      componentId: "",
                      calculationType: "FIXED",
                      percentage: "",
                      amount: "",
                      baseId: "",
                      cap: "",
                      appliesWhen: "ALWAYS",
                    },
                  ])
                }
              >
                <Plus /> Add component
              </Button>
              <p className="text-xs text-foreground-muted">
                Exactly one earning must be &quot;Balance of gross&quot;. Employer contributions
                are part of CTC, so gross = CTC − employer contributions. Save the draft to
                preview it.
              </p>
            </CardContent>
          </Card>
        ) : (
          <TableContainer>
            <TableToolbar>
              <div className="flex items-center gap-2">
                <h2 className="text-sm font-semibold text-foreground">Components</h2>
                <Badge variant="success" dot>
                  Published
                </Badge>
              </div>
            </TableToolbar>
            <Table>
              <TableHeader>
                <TableRow className="hover:bg-transparent">
                  <TableHead>Component</TableHead>
                  <TableHead align="right">Formula / Amount</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {selected.lines.map((line) => (
                  <TableRow key={line.id}>
                    <TableCell className="font-medium text-foreground">
                      {line.component_name}
                    </TableCell>
                    <TableCell align="right" numeric className="text-foreground-secondary">
                      {describeLine(line, components)}
                    </TableCell>
                  </TableRow>
                ))}
                {selected.lines.length === 0 ? (
                  <TableRow>
                    <TableCell colSpan={2} className="text-center text-foreground-muted">
                      No components yet.
                    </TableCell>
                  </TableRow>
                ) : null}
              </TableBody>
            </Table>
          </TableContainer>
        )
      ) : null}

      {selected && selected.lines.length > 0 ? (
        <Card>
          <CardHeader>
            <CardTitle>Preview a CTC</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="flex flex-wrap items-end gap-3">
              <FormField id="preview-ctc" label="Annual CTC (₹)" className="w-48">
                <Input value={ctc} onChange={(e) => setCtc(e.target.value)} />
              </FormField>
              <label className="flex items-center gap-2 pb-2 text-sm text-foreground">
                <Checkbox checked={pf} onChange={(e) => setPf(e.target.checked)} />
                PF applies
              </label>
              <Button type="button" variant="outline" onClick={() => void runPreview()}>
                Calculate
              </Button>
            </div>
            {previewError ? (
              <p role="alert" className="text-sm text-danger">
                {previewError}
              </p>
            ) : null}
            {preview ? <SalaryBreakupTable breakup={preview} /> : null}
          </CardContent>
        </Card>
      ) : null}

      <Dialog open={publishOpen} onOpenChange={(next) => !saving && setPublishOpen(next)}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle>Publish this version</DialogTitle>
            <DialogDescription>
              Employees on this structure are paid by this version from the date you choose; the
              current version ends the day before. A published version cannot be edited.
            </DialogDescription>
          </DialogHeader>
          <FormField id="publish-date" label="Effective from" required>
            <Input
              type="date"
              value={publishDate}
              onChange={(e) => setPublishDate(e.target.value)}
            />
          </FormField>
          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => setPublishOpen(false)}
              disabled={saving}
            >
              Cancel
            </Button>
            <Button
              type="button"
              disabled={saving || !publishDate || !selected}
              onClick={() =>
                selected &&
                void run(
                  () =>
                    apiClient.post<SalaryStructure>(
                      `/payroll/salary-structures/${structure.id}/versions/${selected.id}/publish`,
                      { effective_from: publishDate },
                      { ifMatch: String(selected.version) },
                    ),
                  "Version published",
                ).then((ok) => ok && setPublishOpen(false))
              }
            >
              {saving ? "Publishing…" : "Publish"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
