"use client";

import { Briefcase, Plus } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { DesignationForm } from "@/components/designation/designation-form";
import { EmptyState } from "@/components/common/empty-state";
import { ErrorState } from "@/components/common/error-state";
import { LoadingState } from "@/components/common/loading-state";
import { PageHeader } from "@/components/common/page-header";
import { useToast } from "@/components/common/toast";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
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
import type { Department } from "@/lib/department/types";
import type { Designation } from "@/lib/designation/types";
import {
  EMPTY_DESIGNATION_FORM_VALUES,
  buildCreatePayload,
  validateDesignationForm,
  type DesignationFormErrors,
  type DesignationFormValues,
} from "@/lib/designation/validate-designation";
import type { Grade } from "@/lib/grade/types";

export default function DesignationsPage() {
  const { toast } = useToast();
  const [designations, setDesignations] = useState<Designation[] | null>(null);
  const [departments, setDepartments] = useState<Department[]>([]);
  const [grades, setGrades] = useState<Grade[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<ApiError | null>(null);

  const [createOpen, setCreateOpen] = useState(false);
  const [formValues, setFormValues] = useState<DesignationFormValues>(
    EMPTY_DESIGNATION_FORM_VALUES,
  );
  const [formErrors, setFormErrors] = useState<DesignationFormErrors>({});
  const [saving, setSaving] = useState(false);

  const loadDesignations = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [designationData, departmentData, gradeData] = await Promise.all([
        apiClient.get<Designation[]>("/designations"),
        apiClient.get<Department[]>("/departments"),
        apiClient.get<Grade[]>("/grades"),
      ]);
      setDesignations(designationData);
      setDepartments(departmentData);
      setGrades(gradeData);
    } catch (err) {
      setDesignations(null);
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
    void loadDesignations();
  }, [loadDesignations]);

  function departmentName(departmentId: string | null): string | null {
    if (!departmentId) return null;
    return (
      departments.find((department) => department.id === departmentId)?.name ?? "Unknown department"
    );
  }

  function gradeName(gradeId: string | null): string | null {
    if (!gradeId) return null;
    return grades.find((grade) => grade.id === gradeId)?.name ?? "Unknown grade";
  }

  function openCreate() {
    setFormValues(EMPTY_DESIGNATION_FORM_VALUES);
    setFormErrors({});
    setCreateOpen(true);
  }

  async function handleCreate() {
    const clientErrors = validateDesignationForm(formValues);
    if (Object.keys(clientErrors).length > 0) {
      setFormErrors(clientErrors);
      return;
    }

    setSaving(true);
    setFormErrors({});
    try {
      await apiClient.post<Designation>("/designations", buildCreatePayload(formValues));
      setCreateOpen(false);
      toast({ title: "Designation added", variant: "success" });
      await loadDesignations();
    } catch (err) {
      if (err instanceof ApiError && err.status === 422) {
        setFormErrors({
          title: getFieldError(err.details, "title"),
          departmentId: getFieldError(err.details, "department_id"),
          gradeId: getFieldError(err.details, "grade_id"),
        });
        return;
      }
      if (err instanceof ApiError && err.status === 403) {
        setCreateOpen(false);
        toast({ title: "You don't have permission to add designations", variant: "danger" });
        return;
      }
      if (err instanceof ApiError && err.status === 409) {
        toast({
          title: "Could not add designation",
          description: describeApiError(err),
          variant: "danger",
        });
        return;
      }
      toast({
        title: "Could not add designation",
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
        backHref="/app/settings"
        backLabel="Settings"
        title="Designations"
        description="Job titles your employees will hold — optionally scoped to a department."
        actions={
          designations && designations.length > 0 ? (
            <Button type="button" onClick={openCreate}>
              <Plus className="h-4 w-4" aria-hidden="true" />
              Add Designation
            </Button>
          ) : null
        }
      />

      <TableContainer>
        {loading ? <LoadingState label="Loading designations…" /> : null}

        {error && !loading ? (
          <div className="p-6">
            <ErrorState
              message={
                error.status === 403
                  ? "You do not have permission to view designations."
                  : error.message
              }
              onRetry={() => void loadDesignations()}
            />
          </div>
        ) : null}

        {!loading && !error && designations && designations.length === 0 ? (
          <div className="p-6">
            <EmptyState
              icon={Briefcase}
              title="No designations have been configured yet."
              description="Add the job titles your employees will hold. A designation can optionally sit under a department."
              action={
                <Button type="button" onClick={openCreate}>
                  Add Designation
                </Button>
              }
            />
          </div>
        ) : null}

        {!loading && !error && designations && designations.length > 0 ? (
          <Table>
            <TableHeader>
              <TableRow className="hover:bg-transparent">
                <TableHead>Designation</TableHead>
                <TableHead>Department / Grade</TableHead>
                <TableHead>Status</TableHead>
                <TableHead align="right">Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {designations.map((designation) => (
                <TableRow key={designation.id}>
                  <TableCell>
                    <Link
                      href={`/app/designations/${designation.id}`}
                      className="font-medium text-foreground hover:text-primary hover:underline"
                    >
                      {designation.title}
                    </Link>
                  </TableCell>
                  <TableCell className="text-xs text-foreground-secondary">
                    {[departmentName(designation.department_id), gradeName(designation.grade_id)]
                      .filter(Boolean)
                      .join(" · ") || "No department · No grade"}
                  </TableCell>
                  <TableCell>
                    <Badge variant={designation.is_active ? "secondary" : "outline"}>
                      {designation.is_active ? "Active" : "Inactive"}
                    </Badge>
                  </TableCell>
                  <TableCell align="right">
                    <Link
                      href={`/app/designations/${designation.id}`}
                      className="text-xs font-medium text-primary hover:underline"
                    >
                      View
                    </Link>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        ) : null}
      </TableContainer>

      <Dialog open={createOpen} onOpenChange={(open) => (!saving ? setCreateOpen(open) : null)}>
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle>Add Designation</DialogTitle>
          </DialogHeader>
          <div className="max-h-[60vh] overflow-y-auto pr-1">
            <DesignationForm
              values={formValues}
              errors={formErrors}
              onChange={setFormValues}
              departments={departments}
              grades={grades}
              idPrefix="create-"
            />
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
            <Button type="button" onClick={() => void handleCreate()} disabled={saving}>
              {saving ? "Adding…" : "Add designation"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
