export function PolicyCheckbox({
  label,
  description,
  checked,
  onChange,
}: {
  label: string;
  description?: string;
  checked: boolean;
  onChange: (checked: boolean) => void;
}) {
  return (
    <label className="flex items-start gap-2 text-sm text-foreground">
      <input
        type="checkbox"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
        className="mt-0.5 rounded border-border"
      />
      <span>
        {label}
        {description ? (
          <span className="block text-xs text-foreground-muted">{description}</span>
        ) : null}
      </span>
    </label>
  );
}
