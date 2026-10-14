import 'package:flutter_test/flutter_test.dart';
import 'package:hrms_mobile/features/attendance/data/attendance_repository.dart';
import 'package:hrms_mobile/features/attendance/presentation/attendance_summary.dart';

AttendanceDay day(String status, {String? firstIn, int? late, Map<String, dynamic> extra = const {}}) => AttendanceDay(
      id: status,
      employeeId: 'e',
      attendanceDate: '2026-10-14',
      attendanceStatus: status,
      actualFirstIn: firstIn,
      lateMinutes: late,
      isLocked: false,
      raw: extra,
    );

void main() {
  test('buckets, KPIs and exceptions mirror the web dashboard', () {
    final s = AttendanceSummary.compute([
      day('PRESENT', firstIn: 't', late: 10),
      day('WFH', firstIn: 't'),
      day('ABSENT'),
      day('LEAVE'),
      day('EXITED'),
      day('NOT_EXPECTED', extra: {'calendar_day_type': 'HOLIDAY'}),
      day('INCOMPLETE', extra: {'missing_punch': true, 'ot_minutes_detected': 90}),
    ]);
    expect(s.employed, 6);
    expect(s.present, 2);
    expect(s.count('HOLIDAY'), 1);
    expect(s.late, 1);
    expect(s.notCheckedIn, 2);
    expect(s.exceptions, 1);
    expect(s.overtimeEmployees, 1);
    expect(s.overtimeMinutes, 90);
  });
}
