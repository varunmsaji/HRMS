import { FormField } from "@/components/common/form-field";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/native-select";
import type { HolidayCalendar } from "@/lib/holiday-calendar/types";
import type { WeeklyOffPattern } from "@/lib/weekly-off-pattern/types";
import type {
  WorkCalendarFormErrors,
  WorkCalendarFormValues,
} from "@/lib/work-calendar/validate-work-calendar";

interface WorkCalendarFormProps {
  values: WorkCalendarFormValues;
  errors: WorkCalendarFormErrors;
  onChange: (values: WorkCalendarFormValues) => void;
  holidayCalendars: HolidayCalendar[];
  weeklyOffPatterns: WeeklyOffPattern[];
  idPrefix?: string;
}

export function WorkCalendarForm({
  values,
  errors,
  onChange,
  holidayCalendars,
  weeklyOffPatterns,
  idPrefix = "",
}: WorkCalendarFormProps) {
  const id = (name: string) => `${idPrefix}${name}`;

  function toggleHolidayCalendar(calendarId: string, checked: boolean) {
    const holidayCalendarIds = checked
      ? [...values.holidayCalendarIds, calendarId]
      : values.holidayCalendarIds.filter((existing) => existing !== calendarId);
    onChange({ ...values, holidayCalendarIds });
  }

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <FormField id={id("name")} label="Calendar name" required error={errors.name}>
          <Input
            value={values.name}
            onChange={(e) => onChange({ ...values, name: e.target.value })}
          />
        </FormField>
        <FormField id={id("code")} label="Code" error={errors.code}>
          <Input
            value={values.code}
            onChange={(e) => onChange({ ...values, code: e.target.value })}
          />
        </FormField>
      </div>

      <FormField id={id("description")} label="Description" error={errors.description}>
        <Input
          value={values.description}
          onChange={(e) => onChange({ ...values, description: e.target.value })}
        />
      </FormField>

      <FormField id={id("weeklyOffPatternId")} label="Weekly-off pattern">
        <NativeSelect
          value={values.weeklyOffPatternId}
          onChange={(e) => onChange({ ...values, weeklyOffPatternId: e.target.value })}
        >
          <option value="">None</option>
          {weeklyOffPatterns.map((pattern) => (
            <option key={pattern.id} value={pattern.id}>
              {pattern.name}
            </option>
          ))}
        </NativeSelect>
      </FormField>

      <section>
        <h3 className="text-sm font-medium text-foreground">Holiday calendars</h3>
        <p className="mt-1 text-xs text-foreground-muted">
          Ordered composition — the first calendar checked supplies the display name when two
          calendars name the same date.
        </p>
        <div className="mt-3 space-y-2">
          {holidayCalendars.length === 0 ? (
            <p className="text-sm text-foreground-muted">No holiday calendars exist yet.</p>
          ) : (
            holidayCalendars.map((calendar) => (
              <label key={calendar.id} className="flex items-center gap-2 text-sm text-foreground">
                <input
                  type="checkbox"
                  className="rounded border-border"
                  checked={values.holidayCalendarIds.includes(calendar.id)}
                  onChange={(e) => toggleHolidayCalendar(calendar.id, e.target.checked)}
                />
                {calendar.name}
                {calendar.code ? (
                  <span className="text-foreground-muted"> ({calendar.code})</span>
                ) : null}
              </label>
            ))
          )}
        </div>
      </section>

      <label className="flex items-center gap-2 text-sm text-foreground">
        <input
          type="checkbox"
          className="rounded border-border"
          checked={values.restrictedHolidaysAreOffByDefault}
          onChange={(e) =>
            onChange({ ...values, restrictedHolidaysAreOffByDefault: e.target.checked })
          }
        />
        Treat optional/restricted holidays as off by default
      </label>
    </div>
  );
}
