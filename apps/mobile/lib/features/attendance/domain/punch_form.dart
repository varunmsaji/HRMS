import '../../../core/forms/form_spec.dart';

/// On-behalf punch (`POST /attendance/punches`) — HR/admin entering a punch for an employee. The
/// time is a wall-clock value in the *company* zone; the caller converts it to a UTC instant.
FormSpec punchOnBehalfSpec({required bool employeeLocked, required String zoneLabel}) => FormSpec(
      name: 'punch',
      label: 'Record punch',
      defaults: const {'direction': 'IN'},
      fields: [
        if (!employeeLocked) const FieldSpec('employee_id', 'Employee', kind: FieldKind.choice, choiceKey: 'employees', required: true),
        const FieldSpec('direction', 'Direction', kind: FieldKind.select, required: true, options: ['IN', 'OUT']),
        FieldSpec('punch_time', 'Punch time ($zoneLabel)', kind: FieldKind.dateTime, required: true),
        const FieldSpec('reference', 'Reason', kind: FieldKind.multiline, required: true, hint: 'Why is this punch being recorded on their behalf?'),
      ],
    );
