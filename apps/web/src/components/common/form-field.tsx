import { cloneElement, isValidElement, type ReactElement, type ReactNode } from "react";

import { Label } from "@/components/ui/label";
import { cn } from "@/lib/utils";

interface FormFieldProps {
  id: string;
  label: string;
  error?: string;
  description?: string;
  required?: boolean;
  className?: string;
  children: ReactElement<Record<string, unknown>>;
}

/** Wires label/description/error to the single input child via id + aria-describedby, so every
 * form in the app gets the same accessible field structure without repeating the plumbing. */
export function FormField({
  id,
  label,
  error,
  description,
  required,
  className,
  children,
}: FormFieldProps) {
  const descriptionId = description ? `${id}-description` : undefined;
  const errorId = error ? `${id}-error` : undefined;
  const describedBy = [descriptionId, errorId].filter(Boolean).join(" ") || undefined;

  const field = isValidElement(children)
    ? cloneElement(children, {
        id,
        "aria-invalid": Boolean(error),
        "aria-describedby": describedBy,
        "aria-required": required,
      })
    : children;

  return (
    <div className={cn("space-y-1.5", className)}>
      <Label htmlFor={id} className="block">
        {label}
        {required ? (
          <span className="text-danger" aria-hidden="true">
            {" "}
            *
          </span>
        ) : null}
      </Label>
      {field}
      {description && !error ? (
        <p id={descriptionId} className="text-xs leading-relaxed text-foreground-muted">
          {description}
        </p>
      ) : null}
      {error ? (
        <p id={errorId} role="alert" className="text-xs font-medium text-danger">
          {error}
        </p>
      ) : null}
    </div>
  );
}

interface FormSectionProps {
  title: string;
  description?: string;
  children: ReactNode;
  className?: string;
}

/** Structured grouping for related fields inside forms and settings screens. */
export function FormSection({ title, description, children, className }: FormSectionProps) {
  return (
    <fieldset className={cn("space-y-4 border-t border-border pt-5 first:border-0 first:pt-0", className)}>
      <div>
        <legend className="text-sm font-semibold text-foreground">{title}</legend>
        {description ? (
          <p className="mt-0.5 text-xs text-foreground-secondary">{description}</p>
        ) : null}
      </div>
      {children}
    </fieldset>
  );
}
