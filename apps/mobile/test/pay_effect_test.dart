import 'package:flutter_test/flutter_test.dart';
import 'package:hrms_mobile/features/attendance/domain/pay_effect.dart';

void main() {
  Map<String, dynamic> row(Map<String, dynamic> over) =>
      {'attendance_status': 'PRESENT', 'paid_day_fraction': '0', 'lop_fraction': '0', 'leave_fraction': '0', 'unpaid_off_fraction': '0', ...over};

  test('words the day\'s pay fractions, matching the web', () {
    expect(payEffectLabel(row({'paid_day_fraction': '1.00'})), 'Full day paid');
    expect(payEffectLabel(row({'paid_day_fraction': '1.00', 'leave_fraction': '0.50'})), 'Full day paid · Half day on leave');
    expect(payEffectLabel(row({'lop_fraction': '1.00'})), 'Full day unpaid (loss of pay)');
    expect(payEffectLabel(row({'paid_day_fraction': '0.50', 'unpaid_off_fraction': '0.50'})), 'Half day paid · Half day unpaid day off');
    expect(payEffectLabel(row({'paid_day_fraction': '0.25'})), '0.25 day paid');
    expect(payEffectLabel(row({})), 'No pay effect');
    expect(payEffectLabel(row({'attendance_status': 'EXITED'})), 'Not employed on this day');
  });

  test('says nothing when the row carries no fractions', () {
    expect(payEffectLabel({'attendance_status': 'PRESENT'}), isNull);
  });
}
