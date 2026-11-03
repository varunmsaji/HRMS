import { Trash2 } from "lucide-react";

import { FormField } from "@/components/common/form-field";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/native-select";
import { PATTERN_KINDS, WEEKDAY_LABELS } from "@/lib/weekly-off-pattern/types";
import {
  EMPTY_RULE,
  type WeeklyOffPatternFormErrors,
  type WeeklyOffPatternFormValues,
  type WeeklyOffRuleFormValues,
} from "@/lib/weekly-off-pattern/validate-weekly-off-pattern";

interface WeeklyOffPatternFormProps {
  values: WeeklyOffPatternFormValues;
  errors: WeeklyOffPatternFormErrors;
  onChange: (values: WeeklyOffPatternFormValues) => void;
  idPrefix?: string;
}

const NTH_OPTIONS = [
  { value: "1", label: "1st" },
  { value: "2", label: "2nd" },
  { value: "3", label: "3rd" },
  { value: "4", label: "4th" },
  { value: "5", label: "5th" },
  { value: "-1", label: "Last" },
];

export function WeeklyOffPatternForm({
  values,
  errors,
  onChange,
  idPrefix = "",
}: WeeklyOffPatternFormProps) {
  const id = (name: string) => `${idPrefix}${name}`;

  function updateRule(index: number, patch: Partial<WeeklyOffRuleFormValues>) {
    const rules = values.rules.map((rule, i) => (i === index ? { ...rule, ...patch } : rule));
    onChange({ ...values, rules });
  }

  function addRule() {
    onChange({ ...values, rules: [...values.rules, { ...EMPTY_RULE }] });
  }

  function removeRule(index: number) {
    onChange({ ...values, rules: values.rules.filter((_, i) => i !== index) });
  }

  const showNth = values.patternKind === "NTH_WEEKDAY" || values.patternKind === "CUSTOM";
  const showCycle = values.patternKind === "ALTERNATE" || values.patternKind === "CUSTOM";

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <FormField id={id("name")} label="Pattern name" required error={errors.name}>
          <Input
            value={values.name}
            onChange={(e) => onChange({ ...values, name: e.target.value })}
          />
        </FormField>
        <FormField id={id("patternKind")} label="Pattern kind" required>
          <NativeSelect
            value={values.patternKind}
            onChange={(e) =>
              onChange({
                ...values,
                patternKind: e.target.value as WeeklyOffPatternFormValues["patternKind"],
              })
            }
          >
            {PATTERN_KINDS.map((kind) => (
              <option key={kind} value={kind}>
                {kind.replace("_", " ")}
              </option>
            ))}
          </NativeSelect>
        </FormField>
      </div>

      <section>
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-medium text-foreground">Rules</h3>
          <Button type="button" variant="outline" size="sm" onClick={addRule}>
            Add rule
          </Button>
        </div>
        {errors.rules ? <p className="mt-2 text-xs text-danger">{errors.rules}</p> : null}
        <div className="mt-3 space-y-3">
          {values.rules.map((rule, index) => (
            <div
              key={index}
              className="grid grid-cols-1 gap-3 rounded-md border border-border p-3 sm:grid-cols-5 sm:items-end"
            >
              <FormField id={id(`rule-${index}-weekday`)} label="Weekday">
                <NativeSelect
                  value={String(rule.weekday)}
                  onChange={(e) => updateRule(index, { weekday: Number(e.target.value) })}
                >
                  {WEEKDAY_LABELS.map((label, weekday) => (
                    <option key={weekday} value={weekday}>
                      {label}
                    </option>
                  ))}
                </NativeSelect>
              </FormField>

              {showNth ? (
                <FormField id={id(`rule-${index}-nth`)} label="Occurrence">
                  <NativeSelect
                    value={rule.nthInMonth}
                    onChange={(e) => updateRule(index, { nthInMonth: e.target.value })}
                  >
                    <option value="">Every week</option>
                    {NTH_OPTIONS.map((opt) => (
                      <option key={opt.value} value={opt.value}>
                        {opt.label}
                      </option>
                    ))}
                  </NativeSelect>
                </FormField>
              ) : null}

              {showCycle ? (
                <FormField id={id(`rule-${index}-cycle`)} label="Starting from">
                  <Input
                    type="date"
                    value={rule.cycleStartDate}
                    onChange={(e) => updateRule(index, { cycleStartDate: e.target.value })}
                  />
                </FormField>
              ) : null}

              {showCycle ? (
                <FormField id={id(`rule-${index}-parity`)} label="Off week">
                  <NativeSelect
                    value={rule.weekParity}
                    onChange={(e) =>
                      updateRule(index, {
                        weekParity: e.target.value as WeeklyOffRuleFormValues["weekParity"],
                      })
                    }
                  >
                    <option value="">Starting week</option>
                    <option value="EVEN">Same as starting week</option>
                    <option value="ODD">Opposite of starting week</option>
                  </NativeSelect>
                </FormField>
              ) : null}

              <FormField id={id(`rule-${index}-fraction`)} label="Off amount">
                <NativeSelect
                  value={rule.offFraction}
                  onChange={(e) =>
                    updateRule(index, {
                      offFraction: e.target.value as WeeklyOffRuleFormValues["offFraction"],
                    })
                  }
                >
                  <option value="1.00">Full day</option>
                  <option value="0.50">Half day</option>
                </NativeSelect>
              </FormField>

              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() => removeRule(index)}
                disabled={values.rules.length <= 1}
                aria-label="Remove rule"
              >
                <Trash2 className="h-4 w-4" />
              </Button>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}
