/** Types and pure helpers for `GET /employees/directory/{summary,rows}`. Every figure is the backend's. */

export interface DirectorySummary {
  total: number;
  active: number;
  on_probation: number;
  on_notice: number;
  department_count: number;
  department_names: string[];
}

export interface DirectoryRow {
  employee_id: string;
  designation: string | null;
  department: string | null;
  branch: string | null;
  /** The current assignment's department / branch ids (what the dashboard filters match). */
  department_id?: string | null;
  branch_id?: string | null;
  manager_name: string | null;
  shift_name: string | null;
}

export function directoryRowsPath(ids: string[]): string {
  return `/employees/directory/rows?${ids.map((id) => `ids=${encodeURIComponent(id)}`).join("&")}`;
}

function csvCell(value: string | null | undefined): string {
  const v = value ?? "";
  return /[",\n]/.test(v) ? `"${v.replaceAll('"', '""')}"` : v;
}

export interface CsvEmployee {
  code: string;
  name: string;
  email: string | null;
  mobile: string | null;
  status: string;
  designation: string | null;
  department: string | null;
  manager: string | null;
  shift: string | null;
}

/** CSV of exactly the rows given (the caller decides which — the directory exports what it shows). */
export function employeesToCsv(rows: CsvEmployee[]): string {
  const header = ["Employee code", "Name", "Email", "Mobile", "Status", "Designation", "Department", "Reporting manager", "Shift"];
  const lines = rows.map((r) =>
    [r.code, r.name, r.email, r.mobile, r.status, r.designation, r.department, r.manager, r.shift]
      .map(csvCell)
      .join(","),
  );
  return [header.join(","), ...lines].join("\n");
}
