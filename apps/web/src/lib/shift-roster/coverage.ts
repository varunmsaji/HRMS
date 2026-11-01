import type { ShiftRoster } from "@/lib/shift-roster/types";

export interface CoverageRow {
  /** Shift id, or "OFF" for week-off overrides. */
  key: string;
  label: string;
  isOff: boolean;
  byDate: Map<string, number>;
  /** Distinct employees on this row anywhere in the range. */
  people: number;
}

export interface Coverage {
  rows: CoverageRow[];
  rosteredEmployees: number;
  draftEntries: number;
  totalEntries: number;
}

/** Headcount per shift per day, straight from the roster entries. Entries with neither a shift nor
 * a week-off override have nothing to count and are skipped. */
export function buildCoverage(
  entries: ShiftRoster[],
  dates: string[],
  shiftName: (id: string) => string | undefined,
): Coverage {
  const inRange = new Set(dates);
  const rows = new Map<string, CoverageRow & { who: Set<string> }>();
  const everyone = new Set<string>();
  let draft = 0;
  let total = 0;

  for (const e of entries) {
    if (!inRange.has(e.roster_date)) continue;
    total += 1;
    everyone.add(e.employee_id);
    if (e.status === "DRAFT") draft += 1;
    const isOff = e.is_week_off_override;
    if (!isOff && !e.shift_id) continue;
    const key = isOff ? "OFF" : (e.shift_id as string);
    let row = rows.get(key);
    if (!row) {
      row = {
        key,
        label: isOff ? "Week off" : (shiftName(key) ?? "Unknown shift"),
        isOff,
        byDate: new Map(),
        people: 0,
        who: new Set(),
      };
      rows.set(key, row);
    }
    row.byDate.set(e.roster_date, (row.byDate.get(e.roster_date) ?? 0) + 1);
    row.who.add(e.employee_id);
  }

  const out = [...rows.values()]
    .map(({ who, ...row }) => ({ ...row, people: who.size }))
    .sort((a, b) => Number(a.isOff) - Number(b.isOff) || b.people - a.people || a.label.localeCompare(b.label));
  return { rows: out, rosteredEmployees: everyone.size, draftEntries: draft, totalEntries: total };
}
