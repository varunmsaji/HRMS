import type { ReactNode } from "react";

function same(a: unknown, b: unknown): boolean {
  return a === b || JSON.stringify(a) === JSON.stringify(b);
}

/** How many of `fields` differ from `defaults`. */
export function countChanged<V extends object>(
  values: V,
  defaults: V,
  fields: readonly (keyof V)[],
): number {
  return fields.filter((field) => !same(values[field], defaults[field])).length;
}

/** The fold for rarely needed settings on a policy form. It says how many of them differ from
 * the defaults, so closing it never hides a change, and opens by itself when one has an error. */
export function AdvancedSettings<V extends object>({
  values,
  defaults,
  fields,
  hasError = false,
  children,
}: {
  values: V;
  defaults: V;
  /** The settings inside this fold. */
  fields: readonly (keyof V)[];
  hasError?: boolean;
  children: ReactNode;
}) {
  const changed = countChanged(values, defaults, fields);
  return (
    <details open={hasError || undefined} className="rounded-md border border-border">
      <summary className="cursor-pointer px-4 py-3 text-sm font-medium text-foreground">
        Advanced settings
        <span className="ml-2 text-xs font-normal text-foreground-muted">
          {changed === 0 ? "all at their defaults" : `${changed} changed from the default`}
        </span>
      </summary>
      {children}
    </details>
  );
}
