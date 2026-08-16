import { Badge } from "@/components/ui/badge";

interface EffectiveDateBadgeProps {
  effectiveTo: string | null;
}

/** Marks a single effective-dated row as the current one or a closed historical one — used
 * across Assignment/Compensation/Statutory/Bank history lists so "current vs history" reads
 * the same way everywhere. */
export function EffectiveDateBadge({ effectiveTo }: EffectiveDateBadgeProps) {
  if (effectiveTo === null) {
    return <Badge variant="secondary">Current</Badge>;
  }
  return <Badge variant="outline">Ended {effectiveTo}</Badge>;
}
