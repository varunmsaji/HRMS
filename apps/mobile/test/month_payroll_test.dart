import 'package:flutter_test/flutter_test.dart';
import 'package:hrms_mobile/features/attendance/domain/hr_calendar.dart';
import 'package:hrms_mobile/features/attendance/domain/month_payroll.dart';

Map<String, dynamic> _json({String id = 'e1', Map<String, dynamic> over = const {}}) => {
      'employee_id': id,
      'present_days': '1.50',
      'absent_days': '1.00',
      'leave_days': '1.50',
      'holiday_days': '0.00',
      'weekly_off_days': '4.00',
      'half_days': '1.00',
      'lop_days': '1.50',
      'on_duty_days': '0.00',
      'paid_days': '3.00',
      'late_count': 2,
      'ot_minutes_normal': 30,
      'ot_minutes_weekly_off': 0,
      'ot_minutes_holiday': 0,
      'ot_minutes_night': 15,
      'frozen': false,
      ...over,
    };

void main() {
  test('parses the payroll month figures', () {
    final p = MonthPayroll.fromJson(_json());
    expect(p.leave, 1.5);
    expect(p.paid, 3);
    expect(p.lateCount, 2);
    expect(p.overtimeApprovedMinutes, 45);
    expect(p.frozen, false);
    expect(MonthPayroll.fromJson(_json(over: {'paid_days': null, 'frozen': true})).paid, isNull);
  });

  test('days read without trailing zeros', () {
    expect(formatPayrollDays(1.5), '1.5');
    expect(formatPayrollDays(21), '21');
    expect(formatPayrollDays(null), '–');
  });

  test('payroll totals replace a row\'s own; a row without an entry keeps them', () {
    final own = HrCalendarRow(employeeId: 'e1', name: 'A')
      ..present = 99
      ..absent = 99
      ..leave = 99
      ..late = 99;
    final other = HrCalendarRow(employeeId: 'e2', name: 'B')..present = 7;
    final rows = withPayrollTotals([own, other], [MonthPayroll.fromJson(_json())]);
    expect(rows[0].present, 2); // 1.5 present + half of one band half day
    expect(rows[0].leave, 1.5); // half-day leave is half leave, not "1 present, 0 leave"
    expect(rows[0].absent, 1);
    expect(rows[0].late, 2);
    expect(rows[1].present, 7);
  });
}
