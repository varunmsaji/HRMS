"use client";

import { Layers, Plus } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { GradeForm } from "@/components/grade/grade-form";
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
  TableRowAction,
} from "@/components/ui/table";
import { apiClient } from "@/lib/api/client";
import { ApiError, describeApiError, getFieldError } from "@/lib/api/errors";
import type { Grade } from "@/lib/grade/types";
import {
  EMPTY_GRADE_FORM_VALUES,
  buildCreatePayload,
  validateGradeForm,
  type GradeFormErrors,
  type GradeFormValues,
} from "@/lib/grade/validate-grade";

export default function GradesPage() {
  const { toast } = useToast();
  const [grades, setGrades] = useState<Grade[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<ApiError | null>(null);

  const [createOpen, setCreateOpen] = useState(false);
  const [formValues, setFormValues] = useState<GradeFormValues>(EMPTY_GRADE_FORM_VALUES);
  const [formErrors, setFormErrors] = useState<GradeFormErrors>({});
  const [saving, setSaving] = useState(false);

  const loadGrades = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await apiClient.get<Grade[]>("/grades");
      setGrades(data);
    } catch (err) {
      setGrades(null);
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
    void loadGrades();
  }, [loadGrades]);

  function openCreate() {
    setFormValues(EMPTY_GRADE_FORM_VALUES);
    setFormErrors({});
    setCreateOpen(true);
  }

  async function handleCreate() {
    const clientErrors = validateGradeForm(formValues);
    if (Object.keys(clientErrors).length > 0) {
      setFormErrors(clientErrors);
      return;
    }

    setSaving(true);
    setFormErrors({});
    try {
      await apiClient.post<Grade>("/grades", buildCreatePayload(formValues));
      setCreateOpen(false);
      toast({ title: "Grade added", variant: "success" });
      await loadGrades();
    } catch (err) {
      if (err instanceof ApiError && err.status === 422) {
        setFormErrors({
          code: getFieldError(err.details, "code"),
          name: getFieldError(err.details, "name"),
          maxCtc: getFieldError(err.details, "max_ctc"),
        });
        return;
      }
      if (err instanceof ApiError && err.status === 403) {
        setCreateOpen(false);
        toast({ title: "You don't have permission to add grades", variant: "danger" });
        return;
      }
      if (
        err instanceof ApiError &&
        err.status === 409 &&
        err.code === "GRADE_CODE_ALREADY_EXISTS"
      ) {
        setFormErrors({ code: "A grade with this code already exists." });
        return;
      }
      toast({
        title: "Could not add grade",
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
        title="Grades"
        description="Compensation grades/bands your designations can reference."
        actions={
          grades && grades.length > 0 ? (
            <Button type="button" onClick={openCreate}>
              <Plus className="h-4 w-4" aria-hidden="true" />
              Add Grade
            </Button>
          ) : null
        }
      />

      <TableContainer>
        {loading ? <LoadingState label="Loading grades…" /> : null}

        {error && !loading ? (
          <div className="p-6">
            <ErrorState
              message={
                error.status === 403
                  ? "You do not have permission to view grades."
                  : error.message
              }
              onRetry={() => void loadGrades()}
            />
          </div>
        ) : null}

        {!loading && !error && grades && grades.length === 0 ? (
          <div className="p-6">
            <EmptyState
              icon={Layers}
              title="No grades have been configured yet."
              description="Add the compensation grades/bands your designations will reference."
              action={
                <Button type="button" onClick={openCreate}>
                  Add Grade
                </Button>
              }
            />
          </div>
        ) : null}

        {!loading && !error && grades && grades.length > 0 ? (
          <Table>
            <TableHeader>
              <TableRow className="hover:bg-transparent">
                <TableHead>Grade</TableHead>
                <TableHead>Level</TableHead>
                <TableHead>Status</TableHead>
                <TableHead align="right">Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {grades.map((grade) => (
                <TableRow key={grade.id}>
                  <TableCell>
                    <Link
                      href={`/app/grades/${grade.id}`}
                      className="font-medium text-foreground hover:text-primary hover:underline"
                    >
                      {grade.name}{" "}
                      <span className="font-mono text-xs text-foreground-muted">
                        ({grade.code})
                      </span>
                    </Link>
                  </TableCell>
                  <TableCell className="text-xs tabular-nums text-foreground-secondary">
                    {grade.level !== null ? `Level ${grade.level}` : "No level set"}
                  </TableCell>
                  <TableCell>
                    <Badge variant={grade.is_active ? "secondary" : "outline"}>
                      {grade.is_active ? "Active" : "Inactive"}
                    </Badge>
                  </TableCell>
                  <TableCell align="right">
                    <TableRowAction href={`/app/grades/${grade.id}`}>View</TableRowAction>
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
            <DialogTitle>Add Grade</DialogTitle>
          </DialogHeader>
          <div className="max-h-[60vh] overflow-y-auto pr-1">
            <GradeForm
              values={formValues}
              errors={formErrors}
              onChange={setFormValues}
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
              {saving ? "Adding…" : "Add grade"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
