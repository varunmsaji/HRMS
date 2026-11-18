import 'package:flutter_test/flutter_test.dart';
import 'package:hrms_mobile/features/attendance/data/attendance_repository.dart';
import 'package:hrms_mobile/features/attendance/domain/employee_analytics.dart';

AttendanceDay _day(String date, String status, {Map<String, dynamic> extra = const {}, String? firstIn, String? lastOut, int? worked}) => AttendanceDay.fromJson({
      'id': 'd-$date',
      'employee_id': 'e-1',
      'attendance_date': date,
      'attendance_status': status,
      'actual_first_in': firstIn,
      'actual_last_out': lastOut,
      'worked_minutes': worked,
      'is_locked': false,
      ...extra,
    });

Punch _punch(String dir, String at) => Punch(id: 'p-$at', employeeId: 'e-1', punchTime: at, direction: dir, source: 'WEB');

void main() {
  group('monthStats', () {
    final days = [
      _day('2026-11-02', 'PRESENT', firstIn: '2026-11-02T04:00:00Z', worked: 480),
      _day('2026-11-03', 'PRESENT', firstIn: '2026-11-03T04:30:00Z', worked: 420, extra: {'is_late': true, 'late_minutes': 30, 'is_early_out': true, 'early_departure_minutes': 15}),
      _day('2026-11-04', 'HALF_DAY', firstIn: '2026-11-04T04:00:00Z', worked: 240, extra: {'ot_minutes_detected': 60, 'ot_minutes_approved': 30}),
      _day('2026-11-05', 'ABSENT'),
      _day('2026-11-06', 'LEAVE'),
      _day('2026-11-07', 'NOT_EXPECTED', extra: {'calendar_day_type': 'WEEKLY_OFF'}),
      _day('2026-11-08', 'INCOMPLETE', extra: {'missing_punch': true}),
      _day('2026-11-25', 'PRESENT', firstIn: '2026-11-25T04:00:00Z', worked: 480),
    ];

    test('counts expected, worked, absent, leave and days off up to today only', () {
      final s = monthStats(days, '2026-11-18');
      expect(s.expectedDays, 6); // 3 worked + absent + leave + incomplete
      expect(s.daysWorked, 2.5);
      expect(s.absent, 1);
      expect(s.leave, 1);
      expect(s.halfDays, 1);
      expect(s.daysOff, 1);
      expect(s.missingPunch, 1);
    });

    test('late, early, hours, average, overtime and punctuality', () {
      final s = monthStats(days, '2026-11-18');
      expect(s.lateDays, 1);
      expect(s.lateMinutes, 30);
      expect(s.earlyOutDays, 1);
      expect(s.earlyOutMinutes, 15);
      expect(s.workedMinutes, 1140);
      expect(s.avgWorkedMinutes, 380);
      expect(s.otDetectedMinutes, 60);
      expect(s.otApprovedMinutes, 30);
      expect(s.punctuality, 67); // 2 of 3 worked days on time
      expect(formatWorkedDays(s.daysWorked), '2.5');
      expect(formatWorkedDays(2), '2');
    });

    test('nothing worked means no average and no punctuality', () {
      final s = monthStats([_day('2026-11-05', 'ABSENT')], '2026-11-18');
      expect(s.avgWorkedMinutes, isNull);
      expect(s.punctuality, isNull);
    });
  });

  test('month calendar is Monday-first with leading and trailing blanks', () {
    final weeks = monthWeeks('2026-11', [_day('2026-11-03', 'PRESENT')], '2026-11-18');
    expect(weeks.every((w) => w.length == 7), isTrue);
    // 1 Nov 2026 is a Sunday: six blanks, then the 1st in the last column.
    expect(weeks.first.take(6).every((c) => c == null), isTrue);
    expect(weeks.first.last!.date, '2026-11-01');
    final nov3 = weeks.expand((w) => w).whereType<CalendarCell>().firstWhere((c) => c.date == '2026-11-03');
    expect(nov3.bucket, 'PRESENT');
    final nov18 = weeks.expand((w) => w).whereType<CalendarCell>().firstWhere((c) => c.date == '2026-11-18');
    expect(nov18.isToday, isTrue);
    expect(nov18.bucket, isNull);
    expect(weeks.expand((w) => w).whereType<CalendarCell>().firstWhere((c) => c.date == '2026-11-19').isFuture, isTrue);
    expect(shiftMonth('2026-01', -1), '2025-12');
    expect(shiftMonth('2026-12', 1), '2027-01');
    expect(monthRange('2026-02'), (from: '2026-02-01', to: '2026-02-28'));
  });

  group('todayStatus', () {
    final now = DateTime.utc(2026, 11, 18, 6, 30);
    final day = _day('2026-11-18', 'PRESENT', extra: {'scheduled_start': '2026-11-18T03:30:00Z', 'scheduled_end': '2026-11-18T12:30:00Z'});

    test('an open IN is working, with minutes since the first punch and the countdown to shift end', () {
      final t = todayStatus(day, [_punch('IN', '2026-11-18T03:45:00Z')], now);
      expect(t.state, TodayState.working);
      expect(t.workedMinutes, 165);
      expect(t.minutesToShiftEnd, 360);
      expect(formatCountdown(t.minutesToShiftEnd!), '6h');
    });

    test('an open break means on a break', () {
      final withBreak = _day('2026-11-18', 'PRESENT', extra: {'breaks': [{'break_start': '2026-11-18T06:00:00Z', 'break_end': null}]});
      expect(todayStatus(withBreak, [_punch('IN', '2026-11-18T03:45:00Z')], now).state, TodayState.onBreak);
    });

    test('an OUT last means checked out, with the engine hours', () {
      final out = _day('2026-11-18', 'PRESENT', worked: 300);
      final t = todayStatus(out, [_punch('IN', '2026-11-18T03:45:00Z'), _punch('OUT', '2026-11-18T06:00:00Z')], now);
      expect(t.state, TodayState.checkedOut);
      expect(t.workedMinutes, 300);
    });

    test('no punches: leave, holiday, absent, not started, not checked in, nothing scheduled', () {
      expect(todayStatus(_day('2026-11-18', 'LEAVE'), [], now).state, TodayState.onLeave);
      expect(todayStatus(_day('2026-11-18', 'NOT_EXPECTED', extra: {'calendar_day_type': 'HOLIDAY', 'holiday_name': 'Diwali'}), [], now).holidayName, 'Diwali');
      expect(todayStatus(_day('2026-11-18', 'ABSENT'), [], now).state, TodayState.absent);
      final later = _day('2026-11-18', 'INCOMPLETE', extra: {'scheduled_start': '2026-11-18T09:30:00Z'});
      expect(todayStatus(later, [], now).state, TodayState.notStarted);
      expect(todayStatus(_day('2026-11-18', 'INCOMPLETE', extra: {'scheduled_start': '2026-11-18T03:30:00Z'}), [], now).state, TodayState.notCheckedIn);
      expect(todayStatus(null, [], now).state, TodayState.noShift);
    });
  });

  test('dailyHours picks the most common scheduled length and skips days without worked time', () {
    final days = [
      _day('2026-11-02', 'PRESENT', firstIn: 'x', worked: 480, extra: {'scheduled_minutes': 480}),
      _day('2026-11-03', 'PRESENT', firstIn: 'x', worked: 400, extra: {'scheduled_minutes': 480, 'is_late': true}),
      _day('2026-11-04', 'ABSENT', extra: {'scheduled_minutes': 360}),
      _day('2026-11-30', 'PRESENT', firstIn: 'x', worked: 480),
    ];
    final h = dailyHours(days, '2026-11-18');
    expect(h.scheduledMinutes, 480);
    expect(h.bars.map((b) => b.date), ['2026-11-02', '2026-11-03']);
    expect(h.bars.last.isLate, isTrue);
  });

  test('statusBreakdown leaves out future and not-employed days and keeps the legend order', () {
    final b = statusBreakdown([
      _day('2026-11-02', 'ABSENT'),
      _day('2026-11-03', 'PRESENT'),
      _day('2026-11-04', 'PRESENT'),
      _day('2026-11-05', 'NOT_JOINED'),
      _day('2026-11-30', 'PRESENT'),
    ], '2026-11-18');
    expect(b, [(bucket: 'PRESENT', count: 2), (bucket: 'ABSENT', count: 1)]);
  });

  test('tenureLabel', () {
    final today = DateTime(2026, 11, 18);
    expect(tenureLabel('2020-09-18', today), '6 yrs 2 mos');
    expect(tenureLabel('2025-11-18', today), '1 yr');
    expect(tenureLabel('2026-11-10', today), 'Less than a month');
    expect(tenureLabel('2026-12-01', today), isNull);
    expect(tenureLabel('2026-10-19', today), 'Less than a month'); // 29 days
  });
}
