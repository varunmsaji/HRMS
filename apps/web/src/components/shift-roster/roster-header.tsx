import type { ReactNode } from "react";

/** Title row shared by every roster view: heading and a one-line description on the left, the
 * view's controls (range pill, filters, add button) on the right. */
export function RosterHeader({
  title,
  description,
  children,
}: {
  title: string;
  description?: ReactNode;
  children?: ReactNode;
}) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-4">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-primary">{title}</h1>
        {description ? <p className="mt-1 max-w-xl text-sm text-foreground-secondary">{description}</p> : null}
      </div>
      {children ? <div className="flex flex-wrap items-center gap-3">{children}</div> : null}
    </div>
  );
}
