/** The name fields every employee read model carries. */
export interface EmployeeNameParts {
  first_name: string;
  middle_name?: string | null;
  last_name: string | null;
  display_name?: string | null;
}

/** An employee's name as both apps show it: the display name when one is set, otherwise the
 * full legal name — first, middle and last — so it matches statutory documents and tells apart
 * two people who share a first and last name. Mirrors mobile's `Employee.fullName`. */
export function employeeFullName(employee: EmployeeNameParts): string {
  const display = employee.display_name?.trim();
  if (display) return display;
  return [employee.first_name, employee.middle_name, employee.last_name]
    .map((part) => part?.trim())
    .filter(Boolean)
    .join(" ");
}
