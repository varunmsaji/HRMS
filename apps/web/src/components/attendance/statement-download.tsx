"use client";

import { Download } from "lucide-react";
import { useState } from "react";

import { useToast } from "@/components/common/toast";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/native-select";
import { apiClient } from "@/lib/api/client";
import { describeApiError } from "@/lib/api/errors";
import { EXPORT_FORMAT_LABELS, saveDownloadedFile, statementPath, type ExportFormat } from "@/lib/attendance/export";

interface StatementDownloadProps {
  employeeId: string;
  /** The latest month that can be asked for, `YYYY-MM` (the current month). */
  maxMonth: string;
  /** The month to download. Leave it out and the control offers its own month picker. */
  month?: string;
}

/** Downloads one employee's attendance statement for a month. The server builds the file from the
 * stored days, only for people the caller may see, and records each download. */
export function StatementDownload({ employeeId, maxMonth, month }: StatementDownloadProps) {
  const { toast } = useToast();
  const [picked, setPicked] = useState(maxMonth);
  const [format, setFormat] = useState<ExportFormat>("pdf");
  const [busy, setBusy] = useState(false);
  const chosen = month ?? picked;

  async function download() {
    setBusy(true);
    try {
      const file = await apiClient.download(statementPath(employeeId, chosen, format));
      saveDownloadedFile(file, `statement_${chosen}.${format}`);
    } catch (err) {
      toast({ title: "Could not download the statement", description: describeApiError(err), variant: "danger" });
    } finally {
      setBusy(false);
    }
  }

  return (
    <div role="group" aria-label="Download attendance statement" className="flex flex-wrap items-center gap-2">
      {month === undefined ? (
        <>
          <label htmlFor="att-statement-month" className="sr-only">
            Statement month
          </label>
          <Input
            id="att-statement-month"
            type="month"
            max={maxMonth}
            value={picked}
            onChange={(e) => e.target.value && setPicked(e.target.value)}
            className="w-40"
          />
        </>
      ) : null}
      <label htmlFor="att-statement-format" className="sr-only">
        Statement format
      </label>
      <NativeSelect id="att-statement-format" className="h-9 w-28" value={format} onChange={(e) => setFormat(e.target.value as ExportFormat)}>
        {(Object.keys(EXPORT_FORMAT_LABELS) as ExportFormat[]).map((f) => (
          <option key={f} value={f}>
            {EXPORT_FORMAT_LABELS[f]}
          </option>
        ))}
      </NativeSelect>
      <Button type="button" size="sm" variant="outline" disabled={busy} onClick={download}>
        <Download className="mr-1.5 h-4 w-4" aria-hidden="true" />
        {busy ? "Preparing…" : "Download statement"}
      </Button>
    </div>
  );
}
