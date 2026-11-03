import 'package:flutter_test/flutter_test.dart';
import 'package:hrms_mobile/features/attendance/data/attendance_repository.dart';
import 'package:hrms_mobile/features/home/state/home_stats.dart';

AttendanceDay day(String date, String status, {int minutes = 0, String? type}) => AttendanceDay(
      id: date,
      employeeId: 'e',
      attendanceDate: date,
      attendanceStatus: status,
      workedMinutes: minutes,
      isLocked: false,
      raw: {if (type != null) 'calendar_day_type': type},
    );

void main() {
  test('an empty month is zeros, not a placeholder total', () {
    final summary = summariseMonth(const []);
    expect(summary.total, 0);
    expect(summary.present, 0);
    expect(summary.weeklyOffs, 0);
  });

  test('month tiles count present, leave, absent and off days from the day rows', () {
    final summary = summariseMonth([
      day('2026-10-01', 'PRESENT', minutes: 480),
      day('2026-10-02', 'LEAVE'),
      day('2026-10-03', 'ABSENT'),
      day('2026-10-04', 'NOT_EXPECTED', type: 'WEEKLY_OFF'),
      day('2026-10-05', 'NOT_EXPECTED', type: 'HOLIDAY'),
      day('2026-10-06', 'WFH', minutes: 420),
    ]);
    expect(summary.present, 2);
    expect(summary.onLeave, 1);
    expect(summary.absent, 1);
    expect(summary.weeklyOffs, 1);
    expect(summary.holidays, 1);
    expect(summary.total, 4);
  });

  test('today\'s provisional sweep row is neither absent nor counted', () {
    final rows = [
      day('2026-10-26', 'ABSENT'),
      day('2026-10-27', 'ABSENT'),
    ];
    final withToday = summariseMonth(rows, today: '2026-10-27');
    expect(withToday.absent, 1, reason: 'only the finished day is absent');
    expect(withToday.total, 1);
    expect(summariseMonth(rows).absent, 2, reason: 'without a today, every row is judged as before');
  });

  test('today with a punch, or a locked row, is judged normally', () {
    final punched = AttendanceDay(id: 't', employeeId: 'e', attendanceDate: '2026-10-27', attendanceStatus: 'INCOMPLETE', workedMinutes: 0, isLocked: false, actualFirstIn: '2026-10-27T04:00:00Z', raw: const {});
    final locked = AttendanceDay(id: 'l', employeeId: 'e', attendanceDate: '2026-10-27', attendanceStatus: 'ABSENT', workedMinutes: 0, isLocked: true, raw: const {});
    expect(summariseMonth([punched], today: '2026-10-27').other, 1);
    expect(summariseMonth([locked], today: '2026-10-27').absent, 1);
  });

  test('week bars are Monday to Sunday and missing days are zero hours', () {
    final bars = weekBars([day('2026-10-26', 'PRESENT', minutes: 400)], '2026-10-28');
    expect(bars.map((b) => b.label).toList(), ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']);
    expect(bars.first.date, '2026-10-26');
    expect(bars.first.hours, 6.7);
    expect(bars[2].date, '2026-10-28');
    expect(bars[2].hours, 0);
  });
}
