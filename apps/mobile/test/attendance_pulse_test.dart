import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:hrms_mobile/core/api/api_error.dart';
import 'package:hrms_mobile/core/auth/permissions.dart';
import 'package:hrms_mobile/core/providers.dart';
import 'package:hrms_mobile/core/time.dart';
import 'package:hrms_mobile/features/attendance/data/attendance_repository.dart';
import 'package:hrms_mobile/features/attendance/domain/attendance_insights.dart';
import 'package:hrms_mobile/features/attendance/domain/attendance_pulse.dart';
import 'package:hrms_mobile/features/attendance/domain/attendance_totals.dart';
import 'package:hrms_mobile/features/attendance/presentation/attendance_insights_screen.dart';

import 'support/fake_api_client.dart';
import 'support/totals_fixture.dart';
import 'support/fake_auth.dart';

AttendanceDay day(String emp, String date, String status, {String? firstIn, int? late, Map<String, dynamic> extra = const {}}) => AttendanceDay(
      id: '$emp-$date',
      employeeId: emp,
      attendanceDate: date,
      attendanceStatus: status,
      actualFirstIn: firstIn,
      // A check-in in these fixtures is a complete IN/OUT pair.
      actualLastOut: firstIn,
      lateMinutes: late,
      isLocked: false,
      raw: {if (late != null) 'is_late': late > 0, ...extra},
    );

void main() {
  group('insights helpers and the summary response', () {
    test('the window is the range widened to at least 14 days', () {
      expect(windowRangeIso('2026-11-02', '2026-11-04'), (from: '2026-10-22', to: '2026-11-04'));
      expect(windowRangeIso('2026-10-01', '2026-11-04'), (from: '2026-10-01', to: '2026-11-04'));
    });

    test('the summary response is read as the backend counted it', () {
      final t = AttendanceTotals.fromJson(totalsJson('2026-11-04', '2026-10-28'));
      expect(t.focusDay.rate, closeTo(66.67, 0.01));
      expect((t.focusDay.present, t.focusDay.expected), (2, 3));
      expect(t.rateDelta, closeTo(16.67, 0.01), reason: 'against the same weekday last week');
      expect(t.focus.presentTotal, 2, reason: 'office + remote + on duty');
      expect(t.focus.noRecord, 1);
      expect(t.compare?.absent, 1);
      expect([for (final d in t.distribution) '${d.bucket}=${d.count}'], ['PRESENT=1', 'REMOTE=1', 'ABSENT=1']);
      expect(t.punctuality.onTimeRate, 75);
      expect([for (final b in t.punctuality.bands) b.count], [1, 0, 0, 0]);
      expect(t.frequentLate.single.employeeId, 'e1');
      expect([for (final g in t.byDepartment) '${g.name}:${g.rate}'], ['Ops:0.0', 'Sales:100.0', 'Unassigned:null']);
      expect(t.byDepartment.last.id, isNull);
      expect(weekdayShort('2026-11-04'), 'Wed');
    });

    test('no comparison and no rate when the summary has nothing to divide by', () {
      final json = totalsJson('2026-11-04', '2026-10-28');
      json['compare'] = null;
      final daily = json['daily'] as List;
      daily[0] = <String, dynamic>{...daily[0] as Map<String, dynamic>, 'rate': null};
      final t = AttendanceTotals.fromJson(json);
      expect(t.compare, isNull);
      expect(t.rateDelta, isNull);
    });

    test('the worst weekday is named only when there is something to compare', () {
      WeekdayStat w(String label, int expected, int absent) => WeekdayStat(label: label, expected: expected, absent: absent, rate: expected > 0 ? absent / expected * 100 : null);
      expect(worstWeekday([w('Mon', 2, 1), w('Tue', 1, 0)])?.label, 'Mon');
      expect(worstWeekday([w('Mon', 2, 1), w('Tue', 0, 0)]), isNull, reason: 'one weekday with data');
      expect(worstWeekday([w('Mon', 2, 0), w('Tue', 1, 0)]), isNull, reason: 'no absences');
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
        attendanceRepositoryProvider.overrideWithValue(_Repo(days, totals: totalsJson(today, lastWeek))),
        apiClientProvider.overrideWithValue(api),
        fakeAuth(const [employeeViewAll, attendanceViewAll]),
      ],
      child: const MaterialApp(home: AttendanceInsightsScreen()),
    ));
    await tester.pumpAndSettle();

    // Every total is the summary's, not a count of the two rows above.
    expect(find.text('Attendance at a glance'), findsOneWidget);
    expect(find.text('66.7%'), findsWidgets);
    expect(find.text('2 of 3 expected employees attended.'), findsOneWidget);
    expect(find.textContaining('+16.7 pts vs last'), findsOneWidget);
    expect(find.text('1 with no record yet'), findsOneWidget);
    expect(find.text("See who's in →"), findsOneWidget);

    expect(find.text('Not checked in'), findsOneWidget);
    expect(find.text('Payroll readiness'), findsOneWidget);
    expect(find.text('2 days left'), findsOneWidget);
    expect(find.text('Validation blocked'), findsWidgets);

    expect(find.text('Departments & branches'), findsOneWidget);
    expect(find.text('Ops'), findsOneWidget);
    expect(find.text('Sales'), findsOneWidget);
    expect(api.rowRequests, 0, reason: 'the breakdown comes with the summary');
    expect(find.text('Weds have the highest absence — 40.0% of expected days.'), findsNothing, reason: 'one weekday is nothing to compare');

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

  testWidgets('the department panel needs no directory grant, and a failed summary blanks only the totals', (tester) async {
    tester.view.physicalSize = const Size(800, 12000);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.reset);
    final api = _Api(lists: const {'/attendance-periods': []});
    await tester.pumpWidget(ProviderScope(
      overrides: [
        attendanceRepositoryProvider.overrideWithValue(_Repo([day('e1', businessToday('Asia/Kolkata'), 'PRESENT', firstIn: 't')], totals: null)),
        apiClientProvider.overrideWithValue(api),
        fakeAuth(const [attendanceViewAll]),
      ],
      child: const MaterialApp(home: AttendanceInsightsScreen()),
    ));
    await tester.pumpAndSettle();
    expect(find.text('Departments & branches'), findsOneWidget);
    expect(find.text('The summary is down.'), findsNWidgets(6), reason: 'pulse, KPIs, breakdown, trend, punctuality and weekdays');
    expect(find.text('Work hours'), findsOneWidget, reason: 'the per-person panels still render');
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
  _Repo(this.days, {required this.totals});
  final List<AttendanceDay> days;

  /// The summary to serve; null makes it fail.
  final Map<String, dynamic>? totals;

  @override
  Future<AttendanceTotals> attendanceSummary({required String dateFrom, required String dateTo}) async {
    if (totals == null) throw ApiError(status: 500, code: 'BOOM', message: 'The summary is down.');
    return AttendanceTotals.fromJson(totals!);
  }

  @override
  Future<List<AttendanceDay>> listAttendanceDays({String? employeeId, required String dateFrom, required String dateTo, String? attendanceStatus}) async => days;

  @override
  dynamic noSuchMethod(Invocation invocation) => super.noSuchMethod(invocation);
}
