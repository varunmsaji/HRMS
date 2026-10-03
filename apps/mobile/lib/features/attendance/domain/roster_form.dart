import '../../../core/forms/form_spec.dart';

/// One roster entry — mirrors `ShiftRosterCreate`/`ShiftRosterUpdate` and the web `RosterEntryDialog`
/// (`lib/shift-roster/validate-shift-roster.ts`). `day_kind` is UI-only: it collapses
/// `shift_id` / `is_week_off_override` / `is_holiday_working_override` into one choice.
const rosterDayKindLabels = {'SHIFT': 'Assigned shift', 'WEEK_OFF': 'Week off', 'HOLIDAY_WORKING': 'Working holiday'};

Map<String, String> _validate(Map<String, dynamic> v) {
  final errors = <String, String>{};
  if (v['day_kind'] == 'SHIFT' && ((v['shift_id'] ?? '') as String).isEmpty) {
    errors['shift_id'] = 'Choose a shift, or pick a week-off / holiday-working override instead.';
  }
  return errors;
}

FormSpec rosterSpec({required bool employeeLocked}) => FormSpec(
      name: 'roster',
      label: 'Roster entry',
      defaults: const {'day_kind': 'SHIFT'},
      extraValidate: _validate,
      fields: [
        if (!employeeLocked) const FieldSpec('employee_id', 'Employee', kind: FieldKind.choice, choiceKey: 'employees', required: true, readOnlyOnEdit: true),
        const FieldSpec('roster_date', 'Date', kind: FieldKind.date, required: true, readOnlyOnEdit: true),
        const FieldSpec('day_kind', 'Day', kind: FieldKind.select, required: true, options: ['SHIFT', 'WEEK_OFF', 'HOLIDAY_WORKING'], optionLabels: rosterDayKindLabels),
        const FieldSpec('shift_id', 'Shift', kind: FieldKind.choice, choiceKey: 'shifts', hint: 'Needed for an assigned shift; optional for a working holiday'),
        const FieldSpec('reason', 'Reason', kind: FieldKind.multiline),
      ],
    );

/// The form's starting values for an existing `ShiftRosterRead`.
Map<String, dynamic> rosterToFormWire(Map<String, dynamic> r) => {
      ...r,
      'day_kind': r['is_week_off_override'] == true ? 'WEEK_OFF' : (r['is_holiday_working_override'] == true ? 'HOLIDAY_WORKING' : 'SHIFT'),
    };

Map<String, dynamic> _dayFields(Map<String, dynamic> p) => {
      'shift_id': p['day_kind'] == 'WEEK_OFF' ? null : p['shift_id'],
      'is_week_off_override': p['day_kind'] == 'WEEK_OFF',
      'is_holiday_working_override': p['day_kind'] == 'HOLIDAY_WORKING',
      if (p['reason'] != null) 'reason': p['reason'],
    };

Map<String, dynamic> rosterCreateBody(Map<String, dynamic> p, {String? employeeId}) => {
      'employee_id': employeeId ?? p['employee_id'],
      'roster_date': p['roster_date'],
      ..._dayFields(p),
    };

/// `PATCH /rosters/{id}` — always sends the whole day definition (as the web dialog does).
Map<String, dynamic> rosterPatchBody(Map<String, dynamic> p) => _dayFields(p);

String rosterDayLabel(Map<String, dynamic> r, Map<String, String> shiftNames) {
  final shift = r['shift_id'] == null ? null : (shiftNames[r['shift_id']] ?? 'Shift');
  if (r['is_week_off_override'] == true) return 'Week off';
  if (r['is_holiday_working_override'] == true) return shift == null ? 'Working holiday' : 'Working holiday · $shift';
  return shift ?? '—';
}
