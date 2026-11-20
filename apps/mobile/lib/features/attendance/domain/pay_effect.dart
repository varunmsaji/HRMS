/// What an attendance day is worth to pay, in words, from the row's own fractions (the same ones
/// the period summary hands to Payroll). Never the raw "0.50". Matches the web `payEffect`
/// (`apps/web/src/lib/attendance/day-detail.ts`).
///
/// Returns `null` when the row carries no pay fractions at all (nothing to say).
String? payEffectLabel(Map<String, dynamic> row) {
  final status = row['attendance_status'];
  if (status == 'NOT_JOINED' || status == 'EXITED') return 'Not employed on this day';
  if (row['paid_day_fraction'] == null && row['lop_fraction'] == null) return null;
  double f(String key) => double.tryParse('${row[key] ?? 0}') ?? 0;
  final paid = f('paid_day_fraction');
  final lop = f('lop_fraction');
  final leave = f('leave_fraction');
  final unpaidOff = f('unpaid_off_fraction');
  final parts = [
    if (paid > 0) '${_amount(paid)} paid',
    if (lop > 0) '${_amount(lop)} unpaid (loss of pay)',
    if (unpaidOff > 0) '${_amount(unpaidOff)} unpaid day off',
    if (leave > 0) '${_amount(leave)} on leave',
  ];
  return parts.isEmpty ? 'No pay effect' : parts.join(' · ');
}

String _amount(double fraction) {
  if (fraction == 1) return 'Full day';
  if (fraction == 0.5) return 'Half day';
  final text = fraction.toString();
  return '${text.endsWith('.0') ? text.substring(0, text.length - 2) : text} day';
}
