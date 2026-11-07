import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:hrms_mobile/core/auth/permissions.dart';
import 'package:hrms_mobile/core/providers.dart';
import 'package:hrms_mobile/core/time.dart';
import 'package:hrms_mobile/features/attendance/data/attendance_repository.dart';
import 'package:hrms_mobile/features/attendance/domain/attendance_insights.dart';
import 'package:hrms_mobile/features/attendance/domain/attendance_pulse.dart';
import 'package:hrms_mobile/features/attendance/presentation/attendance_insights_screen.dart';

import 'support/fake_api_client.dart';
import 'support/fake_auth.dart';

AttendanceDay day(String emp, String date, String status, {String? firstIn, int? late, Map<String, dynamic> extra = const {}}) => AttendanceDay(
      id: '$emp-$date',
      employeeId: emp,
      attendanceDate: date,
      attendanceStatus: status,
      actualFirstIn: firstIn,
      lateMinutes: late,
      isLocked: false,
      raw: {if (late != null) 'is_late': late > 0, ...extra},
    );

void main() {
  group('pulse logic (ported from web insights.ts / dashboard.ts)', () {
    test('the window is the range widened to at least 14 days', () {
      expect(windowRangeIso('2026-11-02', '2026-11-04'), (from: '2026-10-22', to: '2026-11-04'));
      expect(windowRangeIso('2026-10-01', '2026-11-04'), (from: '2026-10-01', to: '2026-11-04'));
    });

    test('the daily rate is present over expected, and compares with the same weekday last week', () {
      final rows = [
        day('a', '2026-11-04', 'PRESENT', firstIn: 't'),
        day('b', '2026-11-04', 'WFH', firstIn: 't'),
        day('c', '2026-11-04', 'ABSENT'),
        day('d', '2026-11-04', 'NOT_EXPECTED', extra: {'calendar_day_type': 'WEEKLY_OFF'}),
        day('a', '2026-10-28', 'PRESENT', firstIn: 't'),
        day('c', '2026-10-28', 'ABSENT'),
      ];
      final points = dailyAttendanceRate(rows, '2026-10-28', '2026-11-04');
      final today = points.last;
      expect(today.expected, 3, reason: 'a weekly off is not expected');
      expect(today.present, 2, reason: 'WFH counts as attending');
      expect(today.rate, closeTo(66.67, 0.01));
      expect(points.first.rate, 50);
      expect(rateDelta(points, '2026-11-04', sameWeekdayLastWeek('2026-11-04')), closeTo(16.67, 0.01));
      expect(points[1].rate, isNull, reason: 'nobody expected that day');
      expect(weekdayShort('2026-11-04'), 'Wed');
    });

    test('KPIs skip people not yet employed and count not-checked-in, late and exceptions', () {
      final k = computeKpis([
        day('a', '2026-11-04', 'PRESENT', firstIn: 't', late: 12, extra: {'ot_minutes_detected': 30, 'ot_minutes_approved': 10}),
        day('b', '2026-11-04', 'ABSENT'),
        day('c', '2026-11-04', 'INCOMPLETE', extra: {'missing_punch': true}),
        day('d', '2026-11-04', 'NOT_JOINED'),
        day('e', '2026-11-04', 'LEAVE'),
      ]);
      expect(k.employed, 4);
      expect(k.presentTotal, 1);
      expect(k.late, 1);
      expect(k.checkedIn, 1);
      expect(k.notCheckedIn, 2, reason: 'zero-punch absent and incomplete with no IN');
      expect(k.exceptions, 1);
      expect(k.overtimeEmployees, 1);
      expect(k.overtimeMinutesApproved, 10);
    });

    test('distribution keeps web order and wording, and only buckets that occur', () {
      final d = statusDistribution([day('a', 'x', 'LEAVE'), day('b', 'x', 'PRESENT'), day('c', 'x', 'PRESENT')]);
      expect([for (final e in d) '${e.label}=${e.count}'], ['Present=2', 'On leave=1']);
    });

    test('punctuality bands lateness and finds repeat late arrivals', () {
      final rows = [
        day('a', '2026-11-03', 'PRESENT', firstIn: 't', late: 5),
        day('a', '2026-11-04', 'PRESENT', firstIn: 't', late: 40),
        day('b', '2026-11-04', 'PRESENT', firstIn: 't', late: 0),
        day('c', '2026-11-04', 'PRESENT', firstIn: 't', extra: {'is_late': true}),
        day('d', '2026-11-04', 'ABSENT'),
      ];
      final s = punctualitySummary(rows);
      expect(s.checkedIn, 4);
      expect(s.late, 3);
      expect(s.onTimeRate, 25);
      expect([for (final b in s.bands) b.count], [2, 0, 1, 0], reason: 'a late day with no minutes lands in the smallest band');
      final f = frequentLateArrivals(rows);
      expect(f.single.employeeId, 'a');
      expect(f.single.totalLateMinutes, 45);
    });

    test('weekday absence names the worst weekday only when there is something to compare', () {
      final stats = weekdayAbsence([
        day('a', '2026-11-02', 'ABSENT'), // Mon
        day('b', '2026-11-02', 'PRESENT'),
        day('a', '2026-11-03', 'PRESENT'), // Tue
      ]);
      expect(stats[0].rate, 50);
      expect(stats[1].rate, 0);
      expect(worstWeekday(stats)?.label, 'Mon');
      expect(worstWeekday(weekdayAbsence([day('a', '2026-11-02', 'ABSENT')])), isNull);
    });

    test('the breakdown puts the lowest attendance first and unexpected groups last', () {
      final groups = {'a': 'Sales', 'b': 'Sales', 'c': 'Ops', 'd': null, 'e': 'Ops'};
      final stats = breakdownBy([
        day('a', 'x', 'PRESENT'),
        day('b', 'x', 'ABSENT'),
        day('c', 'x', 'PRESENT'),
        day('d', 'x', 'NOT_EXPECTED', extra: {'calendar_day_type': 'HOLIDAY'}),
        day('e', 'x', 'PRESENT'),
      ], (id) => groups[id]);
      expect([for (final g in stats) '${g.name}:${g.rate}'], ['Sales:50.0', 'Ops:100.0', 'Unassigned:null']);
    });

    test('periods: the default covers today, progress and countdown match web', () {
      final periods = [
        {'id': 'old', 'period_start': '2026-09-01', 'period_end': '2026-09-30'},
        {'id': 'now', 'period_start': '2026-11-01', 'period_end': '2026-11-30'},
      ];
      expect(pickDefaultPeriod(periods, '2026-11-04')?['id'], 'now');
      expect(pickDefaultPeriod(periods, '2026-12-15')?['id'], 'now', reason: 'else the most recent');
      final p = periodProgress(periods[1], '2026-11-04');
      expect((p.elapsedDays, p.totalDays, p.daysLeft), (4, 30, 26));
      expect(periodCountdown(0), 'Ends today');
      expect(periodCountdown(1), '1 day left');
      expect(periodCountdown(-2), 'Ended 2 days ago');
    });

    test('period totals sum decimal strings and keep all-null fields unknown', () {
      final t = sumPeriodSummary([
        {'present_days': '10.5', 'payable_days': '20', 'on_duty_days': null, 'ot_minutes_normal': 30, 'ot_minutes_night': 15, 'late_count': 2, 'frozen': true},
        {'present_days': '3', 'payable_days': null, 'on_duty_days': null, 'ot_minutes_holiday': 5, 'late_count': 1, 'frozen': true},
      ]);
      expect(formatDays(t.values['present_days']), '13.5');
      expect(formatDays(t.values['payable_days']), '20');
      expect(formatDays(t.values['on_duty_days']), '—');
      expect(formatDays(t.values['absent_days']), '0');
      expect(t.otMinutes, 50);
      expect(t.lateCount, 3);
      expect(t.frozen, isTrue);
    });
  });

  testWidgets('the insights screen shows the new panels with periods, summary and departments', (tester) async {
    tester.view.physicalSize = const Size(800, 12000);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.reset);
    final today = businessToday('Asia/Kolkata');
    final lastWeek = addDaysIso(today, -7);
    final days = [
      day('e1', today, 'PRESENT', firstIn: 't', late: 20),
      day('e2', today, 'ABSENT'),
      day('e1', lastWeek, 'PRESENT', firstIn: 't'),
      day('e2', lastWeek, 'PRESENT', firstIn: 't'),
    ];
    final api = _Api(
      lists: {
        '/employees': [
          {'id': 'e1', 'first_name': 'Asha', 'last_name': 'Rao', 'employee_code': 'E-1'},
        ],
        '/regularizations': const [],
        '/overtime': const [],
        '/attendance-periods': [
          {'id': 'p1', 'status': 'OPEN', 'period_start': addDaysIso(today, -3), 'period_end': addDaysIso(today, 2), 'last_validation_status': 'BLOCKED', 'legal_entity_id': 'le'},
        ],
        '/attendance-periods/p1/summary': [
          {'employee_id': 'e1', 'present_days': '4', 'payable_days': '6', 'late_count': 1, 'frozen': false},
        ],
      },
    );
    await tester.pumpWidget(ProviderScope(
      overrides: [
        attendanceRepositoryProvider.overrideWithValue(_Repo(days)),
        apiClientProvider.overrideWithValue(api),
        fakeAuth(const [employeeViewAll, attendanceViewAll]),
      ],
      child: const MaterialApp(home: AttendanceInsightsScreen()),
    ));
    await tester.pumpAndSettle();

    expect(find.text('Attendance at a glance'), findsOneWidget);
    expect(find.text('50.0%'), findsWidgets);
    expect(find.text('1 of 2 expected employees attended.'), findsOneWidget);
    expect(find.textContaining('−50.0 pts vs last'), findsOneWidget);
    expect(find.text("See who's in →"), findsOneWidget);

    expect(find.text('Not checked in'), findsOneWidget);
    expect(find.text('Payroll readiness'), findsOneWidget);
    expect(find.text('2 days left'), findsOneWidget);
    expect(find.text('Validation blocked'), findsWidgets);

    expect(find.text('Departments & branches'), findsOneWidget);
    expect(find.text('Ops'), findsOneWidget);
    expect(find.text('Sales'), findsOneWidget);
    expect(api.rowRequests, 1, reason: 'one batched directory request');

    expect(find.text('Punctuality'), findsOneWidget);
    expect(find.text('Absence by weekday'), findsOneWidget);
    expect(find.text('Attendance periods'), findsOneWidget);
    expect(find.text('Monthly attendance summary'), findsOneWidget);
    expect(find.text('Live preview'), findsOneWidget);
    expect(find.text('Payable days'), findsOneWidget);
    expect(find.textContaining('Not available yet'), findsNothing);

    await tester.tap(find.text('Open reports →'));
    await tester.pumpAndSettle();
    expect(find.widgetWithText(AppBar, 'Reports'), findsOneWidget);
    // The screen opens on "This month": last week's two days count only once the month is 8 days old.
    final inRange = lastWeek.compareTo('${today.substring(0, 7)}-01') >= 0 ? 4 : 2;
    expect(find.text('$inRange rows'), findsOneWidget);
  });

  testWidgets('without the directory grant there is no department panel and no directory request', (tester) async {
    tester.view.physicalSize = const Size(800, 12000);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.reset);
    final api = _Api(lists: const {'/attendance-periods': []});
    await tester.pumpWidget(ProviderScope(
      overrides: [
        attendanceRepositoryProvider.overrideWithValue(_Repo([day('e1', businessToday('Asia/Kolkata'), 'PRESENT', firstIn: 't')])),
        apiClientProvider.overrideWithValue(api),
        fakeAuth(const [attendanceViewAll]),
      ],
      child: const MaterialApp(home: AttendanceInsightsScreen()),
    ));
    await tester.pumpAndSettle();
    expect(find.text('Departments & branches'), findsNothing);
    expect(api.rowRequests, 0);
    expect(find.text('Payroll readiness'), findsNothing, reason: 'no open period');
    expect(find.text('No attendance period to summarise. Open a period for a company first.'), findsOneWidget);
  });
}

/// Serves `/employees/directory/rows` (a list, which the base fake cannot) for e1 → Sales, e2 → Ops.
class _Api extends FakeApiClient {
  _Api({super.lists});
  int rowRequests = 0;

  @override
  Future<T> get<T>(String path, {required T Function(dynamic) parse, bool authenticated = true}) async {
    if (path.startsWith('/employees/directory/rows?')) {
      rowRequests++;
      return parse([
        {'employee_id': 'e1', 'department': 'Sales', 'branch': 'HQ'},
        {'employee_id': 'e2', 'department': 'Ops', 'branch': 'HQ'},
      ]);
    }
    return super.get(path, parse: parse, authenticated: authenticated);
  }
}

class _Repo implements AttendanceRepository {
  _Repo(this.days);
  final List<AttendanceDay> days;

  @override
  Future<List<AttendanceDay>> listAttendanceDays({String? employeeId, required String dateFrom, required String dateTo, String? attendanceStatus}) async => days;

  @override
  dynamic noSuchMethod(Invocation invocation) => super.noSuchMethod(invocation);
}
