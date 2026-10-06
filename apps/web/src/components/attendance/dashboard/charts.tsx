import { cn } from "@/lib/utils";

/** Small dependency-free SVG/CSS charts. Every chart carries an accessible name and a visually
 * hidden data table, so the numbers are never available only as a picture. Colours come from the
 * existing design tokens (`stroke-primary`, `bg-success`, …) so light/dark follow the theme. */

export interface LinePoint {
  key: string;
  label: string;
  value: number | null;
}

interface LineChartProps {
  points: LinePoint[];
  ariaLabel: string;
  /** Formats a value for the axis, tooltips and the hidden table. */
  format: (value: number) => string;
  /** Fix the top of the y axis (e.g. 100 for percentages). */
  yMax?: number;
  className?: string;
}

const W = 600;
const H = 200;
const PAD = { top: 12, right: 12, bottom: 26, left: 38 };

function niceMax(max: number): number {
  if (max <= 0) return 1;
  const pow = 10 ** Math.floor(Math.log10(max));
  const step = max / pow;
  const nice = step <= 1 ? 1 : step <= 2 ? 2 : step <= 5 ? 5 : 10;
  return nice * pow;
}

export function LineChart({ points, ariaLabel, format, yMax, className }: LineChartProps) {
  const values = points.map((p) => p.value).filter((v): v is number => v !== null);
  const top = yMax ?? niceMax(Math.max(0, ...values));
  const innerW = W - PAD.left - PAD.right;
  const innerH = H - PAD.top - PAD.bottom;
  const x = (i: number) => PAD.left + (points.length <= 1 ? innerW / 2 : (i / (points.length - 1)) * innerW);
  const y = (v: number) => PAD.top + innerH - (Math.min(v, top) / top) * innerH;

  // Break the line wherever a value is missing — a gap is honest, an interpolated line is not.
  const segments: string[] = [];
  let current = "";
  points.forEach((p, i) => {
    if (p.value === null) {
      if (current) segments.push(current);
      current = "";
      return;
    }
    current += `${current ? "L" : "M"}${x(i).toFixed(1)},${y(p.value).toFixed(1)}`;
  });
  if (current) segments.push(current);

  const ticks = [0, 0.25, 0.5, 0.75, 1];
  const labelEvery = Math.max(1, Math.ceil(points.length / 7));

  return (
    <div className={className}>
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={ariaLabel} className="h-auto w-full">
        {ticks.map((t) => (
          <g key={t}>
            <line
              x1={PAD.left}
              x2={W - PAD.right}
              y1={y(top * t)}
              y2={y(top * t)}
              className="stroke-border"
              strokeWidth={1}
            />
            <text x={PAD.left - 6} y={y(top * t) + 4} textAnchor="end" className="fill-foreground-muted text-[10px]">
              {format(top * t)}
            </text>
          </g>
        ))}
        {segments.map((d) => (
          <path key={d} d={d} fill="none" className="stroke-primary" strokeWidth={2} strokeLinejoin="round" />
        ))}
        {points.map((p, i) =>
          p.value === null ? null : (
            <circle key={p.key} cx={x(i)} cy={y(p.value)} r={3} className="fill-primary">
              <title>{`${p.label}: ${format(p.value)}`}</title>
            </circle>
          ),
        )}
        {points.map((p, i) =>
          i % labelEvery === 0 ? (
            <text key={p.key} x={x(i)} y={H - 8} textAnchor="middle" className="fill-foreground-muted text-[10px]">
              {p.label}
            </text>
          ) : null,
        )}
      </svg>
      <table className="sr-only">
        <caption>{ariaLabel}</caption>
        <tbody>
          {points.map((p) => (
            <tr key={p.key}>
              <th scope="row">{p.label}</th>
              <td>{p.value === null ? "No data" : format(p.value)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export interface ColumnDatum {
  key: string;
  label: string;
  /** Primary series (e.g. worked). */
  value: number;
  /** Optional comparison series (e.g. scheduled). */
  reference?: number;
}

interface ColumnChartProps {
  data: ColumnDatum[];
  ariaLabel: string;
  format: (value: number) => string;
  valueLabel: string;
  referenceLabel?: string;
}

/** Paired columns; the reference series is the outlined bar behind the primary one. */
export function ColumnChart({ data, ariaLabel, format, valueLabel, referenceLabel }: ColumnChartProps) {
  const max = niceMax(Math.max(0, ...data.map((d) => Math.max(d.value, d.reference ?? 0))));
  const labelEvery = Math.max(1, Math.ceil(data.length / 7));
  return (
    <div>
      <div role="img" aria-label={ariaLabel} className="flex h-40 items-end gap-1">
        {data.map((d) => (
          <div key={d.key} className="relative flex h-full min-w-0 flex-1 items-end" title={`${d.label}: ${format(d.value)}${d.reference !== undefined ? ` of ${format(d.reference)}` : ""}`}>
            {d.reference !== undefined ? (
              <div
                className="absolute inset-x-0 bottom-0 rounded-sm border border-border-strong"
                style={{ height: `${(d.reference / max) * 100}%` }}
              />
            ) : null}
            <div
              className="relative w-full rounded-sm bg-primary"
              style={{ height: `${(d.value / max) * 100}%` }}
            />
          </div>
        ))}
      </div>
      <div className="mt-1 flex gap-1" aria-hidden="true">
        {data.map((d, i) => (
          <div key={d.key} className="min-w-0 flex-1 truncate text-center text-[10px] text-foreground-muted">
            {i % labelEvery === 0 ? d.label : ""}
          </div>
        ))}
      </div>
      <div className="mt-2 flex gap-4 text-xs text-foreground-secondary">
        <span className="flex items-center gap-1.5">
          <span className="h-2 w-2 rounded-sm bg-primary" aria-hidden="true" />
          {valueLabel}
        </span>
        {referenceLabel ? (
          <span className="flex items-center gap-1.5">
            <span className="h-2 w-2 rounded-sm border border-border-strong" aria-hidden="true" />
            {referenceLabel}
          </span>
        ) : null}
      </div>
      <table className="sr-only">
        <caption>{ariaLabel}</caption>
        <thead>
          <tr>
            <th scope="col">Date</th>
            <th scope="col">{valueLabel}</th>
            {referenceLabel ? <th scope="col">{referenceLabel}</th> : null}
          </tr>
        </thead>
        <tbody>
          {data.map((d) => (
            <tr key={d.key}>
              <th scope="row">{d.label}</th>
              <td>{format(d.value)}</td>
              {referenceLabel ? <td>{d.reference !== undefined ? format(d.reference) : "—"}</td> : null}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

interface ProportionBarProps {
  segments: { key: string; label: string; count: number; barClass: string }[];
  ariaLabel: string;
  className?: string;
}

/** One stacked bar, proportional to counts. */
export function ProportionBar({ segments, ariaLabel, className }: ProportionBarProps) {
  const total = segments.reduce((acc, s) => acc + s.count, 0);
  return (
    <div
      role="img"
      aria-label={ariaLabel}
      className={cn("flex h-3 w-full overflow-hidden rounded-full bg-muted", className)}
    >
      {total > 0
        ? segments
            .filter((s) => s.count > 0)
            .map((s) => (
              <div
                key={s.key}
                className={s.barClass}
                style={{ width: `${(s.count / total) * 100}%` }}
                title={`${s.label}: ${s.count}`}
              />
            ))
        : null}
    </div>
  );
}
