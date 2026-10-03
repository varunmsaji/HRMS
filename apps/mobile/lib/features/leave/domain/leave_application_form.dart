import '../../../core/forms/form_spec.dart';

/// Applying for leave — mirrors `LeaveApplicationCreate` (`apps/api/.../leave/schemas.py`) and the
/// web dialog's validation. [onBehalf] adds the employee picker (HR / manager submitting for
/// someone); a self-service form never sends `employee_id` — the server uses the caller's own.
Map<String, String> _validateDates(Map<String, dynamic> v) {
  final start = (v['start_date'] ?? '') as String;
  final end = (v['end_date'] ?? '') as String;
  final errors = <String, String>{};
  if (start.isNotEmpty && end.isNotEmpty && end.compareTo(start) < 0) errors['end_date'] = 'End date must not be before start date.';
  if ((v['half_day'] ?? '') != '' && start.isNotEmpty && end.isNotEmpty && start != end) {
    errors['half_day'] = 'A half day applies to a single-day application.';
  }
  return errors;
}

FormSpec leaveApplicationSpec({required bool onBehalf}) => FormSpec(
      name: 'leave_application',
      label: 'Apply for leave',
      extraValidate: _validateDates,
      fields: [
        if (onBehalf) const FieldSpec('employee_id', 'Employee', kind: FieldKind.choice, choiceKey: 'employees', required: true),
        const FieldSpec('leave_type_id', 'Leave type', kind: FieldKind.choice, choiceKey: 'leave_types', required: true),
        const FieldSpec('start_date', 'Start date', kind: FieldKind.date, required: true),
        const FieldSpec('end_date', 'End date', kind: FieldKind.date, required: true),
        const FieldSpec('half_day', 'Half day', kind: FieldKind.select, options: ['FIRST_HALF', 'SECOND_HALF'], optionLabels: {'FIRST_HALF': 'First half', 'SECOND_HALF': 'Second half'}, hint: 'Only for a single-day application'),
        const FieldSpec('reason', 'Reason', kind: FieldKind.multiline),
        const FieldSpec('attachment_reference', 'Attachment reference', hint: 'For leave types that need a supporting document'),
        const FieldSpec('expected_delivery_date', 'Expected delivery date', kind: FieldKind.date, hint: 'Maternity leave only'),
      ],
    );

const leaveApplicationStatuses = ['SUBMITTED', 'APPROVED', 'REJECTED', 'CANCELLED'];

const leaveApplicationStatusLabels = {'SUBMITTED': 'Submitted', 'APPROVED': 'Approved', 'REJECTED': 'Rejected', 'CANCELLED': 'Cancelled'};
