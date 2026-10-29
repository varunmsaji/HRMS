"use client";

import { Coins, Plus } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { EmptyState } from "@/components/common/empty-state";
import { ErrorState } from "@/components/common/error-state";
import { FormField } from "@/components/common/form-field";
import { LoadingState } from "@/components/common/loading-state";
import { PageHeader } from "@/components/common/page-header";
import { useToast } from "@/components/common/toast";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
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
} from "@/components/ui/table";
import { apiClient } from "@/lib/api/client";
import { ApiError, describeApiError, getFieldError } from "@/lib/api/errors";
import { usePermissions } from "@/lib/auth/use-permissions";
import {
  COMPONENT_TYPE_LABELS,
  COMPONENT_TYPES,
  type ComponentType,
  type SalaryComponent,
} from "@/lib/payroll/types";

const FLAG_LABELS: [keyof SalaryComponent, string][] = [
  ["is_taxable", "Taxable"],
  ["is_pf_wage", "Counts as PF wage"],
  ["is_esi_wage", "Counts as ESI wage"],
  ["is_prorated", "Prorated by paid days"],
  ["show_on_payslip", "Shown on payslip"],
];

interface ComponentFormValues {
  code: string;
  name: string;
  component_type: ComponentType;
  is_taxable: boolean;
  is_pf_wage: boolean;
  is_esi_wage: boolean;
  is_prorated: boolean;
  show_on_payslip: boolean;
  display_order: string;
}

const EMPTY_VALUES: ComponentFormValues = {
  code: "",
  name: "",
  component_type: "EARNING",
  is_taxable: true,
  is_pf_wage: false,
  is_esi_wage: false,
  is_prorated: true,
  show_on_payslip: true,
  display_order: "100",
};

/** Payroll Phase 5.1 — the company's salary component master (`/v1/payroll/salary-components`).
 * System components (Basic, HRA, Special Allowance, Employer PF/ESI) are seeded automatically;
 * their type is fixed, everything else is editable. */
export default function SalaryComponentsPage() {
  const { toast } = useToast();
  const { can } = usePermissions();
  const canManage = can("PAYROLL.SETUP_MANAGE");

  const [components, setComponents] = useState<SalaryComponent[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<ApiError | null>(null);
  const [createOpen, setCreateOpen] = useState(false);
  const [values, setValues] = useState<ComponentFormValues>(EMPTY_VALUES);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string | undefined>>({});
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setComponents(await apiClient.get<SalaryComponent[]>("/payroll/salary-components"));
    } catch (err) {
      setComponents(null);
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

  async function handleCreate() {
    setSaving(true);
    setFieldErrors({});
    try {
      await apiClient.post<SalaryComponent>("/payroll/salary-components", {
        ...values,
        code: values.code.trim().toUpperCase(),
        name: values.name.trim(),
        display_order: Number(values.display_order) || 0,
      });
      setCreateOpen(false);
      setValues(EMPTY_VALUES);
      toast({ title: "Salary component created", variant: "success" });
      await load();
    } catch (err) {
      if (err instanceof ApiError && (err.status === 422 || err.status === 409)) {
        setFieldErrors({
          code: getFieldError(err.details, "code") ?? getFieldError(err.details, "body.code"),
          name: getFieldError(err.details, "body.name"),
        });
        if (err.status === 409) return;
      }
      toast({
        title: "Could not create component",
        description: describeApiError(err),
        variant: "danger",
      });
    } finally {
      setSaving(false);
    }
  }

  async function toggleActive(component: SalaryComponent) {
    try {
      await apiClient.patch<SalaryComponent>(
        `/payroll/salary-components/${component.id}`,
        { is_active: !component.is_active },
        { ifMatch: String(component.version) },
      );
      await load();
    } catch (err) {
      toast({
        title: "Could not update component",
        description: describeApiError(err),
        variant: "danger",
      });
    }
  }

  return (
    <div className="space-y-6">
      <PageHeader
        backHref="/app/settings"
        backLabel="Settings"
        title="Salary Components"
        description="The earnings and employer contributions a salary structure is built from."
        actions={
          canManage ? (
            <Button type="button" onClick={() => setCreateOpen(true)}>
              <Plus className="h-4 w-4" aria-hidden="true" />
              New component
            </Button>
          ) : undefined
        }
      />

      <TableContainer>
        {loading ? <LoadingState label="Loading salary components…" /> : null}
        {error && !loading ? (
          <div className="p-6">
            <ErrorState
              message={
                error.status === 403
                  ? "You do not have permission to manage payroll setup."
                  : error.message
              }
              onRetry={() => void load()}
            />
          </div>
        ) : null}
        {!loading && !error && components && components.length === 0 ? (
          <div className="p-6">
            <EmptyState icon={Coins} title="No salary components yet." />
          </div>
        ) : null}
        {!loading && !error && components && components.length > 0 ? (
          <Table>
            <TableHeader>
              <TableRow className="hover:bg-transparent">
                <TableHead>Component</TableHead>
                <TableHead>Type</TableHead>
                <TableHead>Treatment</TableHead>
                <TableHead>Status</TableHead>
                {canManage ? <TableHead align="right">Action</TableHead> : null}
              </TableRow>
            </TableHeader>
            <TableBody>
              {components.map((component) => (
                <TableRow key={component.id}>
                  <TableCell>
                    <div className="font-medium text-foreground">{component.name}</div>
                    <div className="font-mono text-xs text-foreground-muted">
                      {component.code}
                      {component.is_system ? (
                        <span className="font-sans"> · system</span>
                      ) : (
                        ""
                      )}
                    </div>
                  </TableCell>
                  <TableCell className="text-foreground-secondary">
                    {COMPONENT_TYPE_LABELS[component.component_type]}
                  </TableCell>
                  <TableCell className="text-xs text-foreground-secondary">
                    {FLAG_LABELS.filter(([key]) => component[key])
                      .map(([, label]) => label)
                      .join(", ") || "—"}
                  </TableCell>
                  <TableCell>
                    <Badge variant={component.is_active ? "success" : "outline"} dot>
                      {component.is_active ? "Active" : "Inactive"}
                    </Badge>
                  </TableCell>
                  {canManage ? (
                    <TableCell align="right">
                      <Button
                        type="button"
                        variant="outline"
                        size="xs"
                        onClick={() => void toggleActive(component)}
                      >
                        {component.is_active ? "Deactivate" : "Activate"}
                      </Button>
                    </TableCell>
                  ) : null}
                </TableRow>
              ))}
            </TableBody>
          </Table>
        ) : null}
      </TableContainer>

      <Dialog open={createOpen} onOpenChange={(next) => !saving && setCreateOpen(next)}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle>New salary component</DialogTitle>
            <DialogDescription>
              Deductions can be defined now; they become usable when pay runs arrive.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4">
            <FormField
              id="component-code"
              label="Code"
              required
              error={fieldErrors.code}
              description="Capital letters, digits and underscores, e.g. CONVEYANCE."
            >
              <Input
                value={values.code}
                maxLength={30}
                onChange={(e) => setValues({ ...values, code: e.target.value })}
              />
            </FormField>
            <FormField id="component-name" label="Name" required error={fieldErrors.name}>
              <Input
                value={values.name}
                maxLength={150}
                onChange={(e) => setValues({ ...values, name: e.target.value })}
              />
            </FormField>
            <FormField id="component-type" label="Type">
              <NativeSelect
                value={values.component_type}
                onChange={(e) =>
                  setValues({ ...values, component_type: e.target.value as ComponentType })
                }
              >
                {COMPONENT_TYPES.map((type) => (
                  <option key={type} value={type}>
                    {COMPONENT_TYPE_LABELS[type]}
                  </option>
                ))}
              </NativeSelect>
            </FormField>
            <div className="space-y-2">
              {FLAG_LABELS.map(([key, label]) => (
                <label key={key} className="flex items-center gap-2 text-sm text-foreground">
                  <Checkbox
                    checked={Boolean(values[key as keyof ComponentFormValues])}
                    onChange={(e) => setValues({ ...values, [key]: e.target.checked })}
                  />
                  {label}
                </label>
              ))}
            </div>
            <FormField id="component-order" label="Display order">
              <Input
                type="number"
                value={values.display_order}
                onChange={(e) => setValues({ ...values, display_order: e.target.value })}
              />
            </FormField>
          </div>
          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => setCreateOpen(false)}
              disabled={saving}
            >
              Cancel
            </Button>
            <Button
              type="button"
              onClick={() => void handleCreate()}
              disabled={saving || !values.code.trim() || !values.name.trim()}
            >
              {saving ? "Creating…" : "Create component"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
