import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:hrms_mobile/core/api/api_error.dart';
import 'package:hrms_mobile/core/auth/permissions.dart';
import 'package:hrms_mobile/core/providers.dart';
import 'package:hrms_mobile/features/attendance/data/attendance_repository.dart';
import 'package:hrms_mobile/features/attendance/domain/attendance_insights.dart';
import 'package:hrms_mobile/features/attendance/domain/attendance_reports.dart' show overtimeTotals;
import 'package:hrms_mobile/features/attendance/domain/attendance_totals.dart';
import 'package:hrms_mobile/features/attendance/domain/pattern_alerts.dart';
import 'package:hrms_mobile/features/attendance/presentation/attendance_insights_screen.dart';

import 'support/fake_api_client.dart';
import 'support/totals_fixture.dart';
import 'support/fake_auth.dart';

AttendanceDay day(String id, String emp, String date, String status, {String? firstIn, String? lastOut, int worked = 0, Map<String, dynamic> extra = const {}}) => AttendanceDay(
      id: id,
      employeeId: emp,
      attendanceDate: date,
      attendanceStatus: status,
      actualFirstIn: firstIn,
      actualLastOut: lastOut,
      workedMinutes: worked,
      isLocked: false,
      raw: extra,
    );

void main() {
  patternTests();
  auditFixTests();
  group('insights logic', () {
    test('ranges resolve like the web presets', () {
      expect(resolveInsightsRange(InsightsRange.week, '2026-10-14'), (from: '2026-10-12', to: '2026-10-14'));
      expect(resolveInsightsRange(InsightsRange.month, '2026-10-14'), (from: '2026-10-01', to: '2026-10-14'));
      expect(resolveInsightsRange(InsightsRange.last14, '2026-10-14'), (from: '2026-10-01', to: '2026-10-14'));
    });

    test('trend percentages use expected days as the denominator and gap when it is zero', () {
      // The summary's per-day counts: one of two attended on the 12th (8 hours), nobody expected on the 13th.
      const days = [
        TotalsDay(date: '2026-10-12', expected: 2, present: 1, rate: 50, absent: 1, checkedIn: 1, workedMinutes: 480),
        TotalsDay(date: '2026-10-13', expected: 0, present: 0, rate: null),
      ];
      final t = buildTrend(days, '2026-10-12', '2026-10-13', TrendMetric.presentPct, weekly: false);
      expect(t[0].value, 50);
      expect(t[1].value, isNull);
      final hours = buildTrend(days, '2026-10-12', '2026-10-12', TrendMetric.avgHours, weekly: false);
      expect(hours.single.value, 8);
      expect(buildTrend(days, '2026-10-12', '2026-10-13', TrendMetric.presentPct, weekly: true).single.label, 'Wk 12 Oct');
    });

    test('work hours compare worked against scheduled on attended days', () {
      final s = summarizeWorkHours([
        day('1', 'a', '2026-10-12', 'PRESENT', firstIn: 't', lastOut: 'o', worked: 420, extra: {'scheduled_minutes': 480, 'ot_minutes_detected': 30}),
        day('2', 'b', '2026-10-12', 'ABSENT', extra: {'scheduled_minutes': 480}),
      ]);
      expect(s.totalMinutes, 420);
      expect(s.expectedMinutes, 480);
      expect(s.deviationMinutes, -60);
      expect(s.underTimeMinutes, 60);
      expect(s.otDetectedMinutes, 30);
    });

    test('overtime sums the backend records by status and day class', () {
      final s = summarizeOvertime([
        {'employee_id': 'a', 'minutes_detected': 60, 'minutes_approved': 60, 'status': 'APPROVED', 'day_class': 'NORMAL', 'attendance_date': '2026-10-12'},
        {'employee_id': 'b', 'minutes_detected': 120, 'minutes_approved': 0, 'status': 'PENDING', 'day_class': 'HOLIDAY', 'attendance_date': '2026-10-13'},
      ], '2026-10-12', '2026-10-13');
      expect(s.totalDetectedMinutes, 180);
      expect(s.employees, 2);
      expect(s.pendingCount, 1);
      expect(s.pendingMinutes, 120);
      expect(s.byDayClass.first.dayClass, 'HOLIDAY');
      expect(s.trend.map((t) => t.minutes), [60, 120]);
    });

    test('needs-attention is ordered by severity and includes workflow items', () {
      final items = buildAttentionItems(
        rows: [day('1', 'a', '2026-10-12', 'CONFIG_ERROR'), day('2', 'a', '2026-10-13', 'PRESENT', extra: {'is_late': true})],
        pendingRegularizations: 2,
        pendingOvertime: 0,
        blockedPeriods: 1,
      );
      expect(items.first.severity, Severity.critical);
      expect(items.map((i) => i.label), containsAll(['Configuration errors', 'Late arrivals', 'Corrections pending', 'Payroll period blocked']));
      expect(items.firstWhere((i) => i.label == 'Corrections pending').route, '/app/regularizations');
    });

    test('repeat absences need the threshold and the heatmap keeps the last 14 days', () {
      final rows = [for (var i = 1; i <= 3; i++) day('$i', 'a', '2026-10-0$i', 'ABSENT'), day('x', 'b', '2026-10-01', 'ABSENT')];
      expect(repeatAbsences(rows).map((r) => r.employeeId), ['a']);
      final dates = musterDates('2026-09-01', '2026-10-14');
      expect(dates.length, 14);
      expect(dates.last, '2026-10-14');
    });
  });

  testWidgets('the insights screen renders every panel and degrades when overtime is forbidden', (tester) async {
    tester.view.physicalSize = const Size(800, 6000);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.reset);
    final api = FakeApiClient(
      lists: {
        '/employees': [
          {'id': 'e1', 'first_name': 'Asha', 'last_name': 'Rao', 'employee_code': 'E-1'}
        ],
        '/regularizations': [
          {'id': 'r1', 'employee_id': 'e1'}
        ],
        '/attendance-periods': const [],
      },
      failing: {'/overtime': Exception('boom')},
    );
    await tester.pumpWidget(ProviderScope(
      overrides: [
        attendanceRepositoryProvider.overrideWithValue(_Repo([day('1', 'e1', '2026-10-12', 'PRESENT', firstIn: 't', lastOut: 'o', worked: 480, extra: {'is_late': true, 'scheduled_minutes': 480})])),
        apiClientProvider.overrideWithValue(api),
        fakeAuth(const []),
      ],
      child: const MaterialApp(home: AttendanceInsightsScreen()),
    ));
    await tester.pumpAndSettle();
    // Today.
    expect(find.text('Needs attention'), findsOneWidget);
    expect(find.text('Patterns to look at'), findsOneWidget);
    expect(find.textContaining('No patterns found'), findsOneWidget);
    expect(find.text('Corrections pending'), findsOneWidget);
    expect(find.text('Attendance heatmap'), findsOneWidget);
    // Trends.
    await tester.tap(find.widgetWithText(Tab, 'Trends'));
    await tester.pumpAndSettle();
    expect(find.text('Departments & branches'), findsOneWidget, reason: 'from the summary, no directory grant needed');
    expect(find.text('Attendance trend'), findsOneWidget);
    expect(find.text('Punctuality'), findsOneWidget);
    expect(find.text('Absence & leave'), findsOneWidget);
    expect(find.text('By weekday'), findsOneWidget);
    expect(find.text('Work hours'), findsOneWidget);
    expect(find.text('Overtime'), findsWidgets);
    expect(find.text('Something went wrong.'), findsOneWidget); // overtime section only
    // Six cards, as on web: the duplicates and the period panels are gone.
    expect(find.text('Leave & absence'), findsNothing);
    expect(find.text('Absence by weekday'), findsNothing);
    expect(find.text('Attendance periods'), findsNothing);
    expect(find.text('Monthly attendance summary'), findsNothing);
  });
}

const _thresholds = {'window_days': 30, 'weekday_window_days': 56, 'late_days': 5, 'absent_days': 4, 'incomplete_days': 3, 'weekday_absences': 3};

class _Repo implements AttendanceRepository {
  _Repo(this.days, {this.patterns, this.patternsForbidden = false, this.serverTotal, this.calculatedAt});
  final List<AttendanceDay> days;

  /// When set and above [days].length, the load reports itself as cut off at the page ceiling.
  final int? serverTotal;
  final String? calculatedAt;
  final Map<String, dynamic>? patterns;
  final bool patternsForbidden;

  @override
  Future<PatternAlerts> patternAlerts({String? asOf}) async {
    if (patternsForbidden) throw ApiError(status: 403, code: 'FORBIDDEN', message: 'no');
    return PatternAlerts.fromJson(patterns ?? {'as_of': asOf ?? '2026-10-14', 'thresholds': _thresholds, 'alerts': []});
  }

  @override
  Future<List<AttendanceDay>> listAttendanceDays({String? employeeId, required String dateFrom, required String dateTo, String? attendanceStatus}) async => days;

  @override
  Future<DaysCoverage> listAttendanceDaysCovered({String? employeeId, required String dateFrom, required String dateTo, String? attendanceStatus}) async {
    final all = await listAttendanceDays(employeeId: employeeId, dateFrom: dateFrom, dateTo: dateTo, attendanceStatus: attendanceStatus);
    final total = serverTotal ?? all.length;
    return DaysCoverage(days: all, total: total, truncated: total > all.length);
  }

  @override
  Future<AttendanceTotals> attendanceSummary({required String dateFrom, required String dateTo}) async =>
      AttendanceTotals.fromJson({...totalsJson(dateTo, addDaysIso(dateTo, -7)), 'calculated_at': calculatedAt});

  @override
  dynamic noSuchMethod(Invocation invocation) => super.noSuchMethod(invocation);
}

Future<void> _pumpToday(WidgetTester tester, _Repo repo, {List<String> permissions = const []}) async {
  tester.view.physicalSize = const Size(800, 6000);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
  final api = FakeApiClient(lists: {
    '/employees': [
      {'id': 'e1', 'first_name': 'Asha', 'last_name': 'Rao', 'employee_code': 'E-1'}
    ],
    '/regularizations': const [],
    '/attendance-periods': const [],
    '/overtime': const [],
  });
  await tester.pumpWidget(ProviderScope(
    overrides: [attendanceRepositoryProvider.overrideWithValue(repo), apiClientProvider.overrideWithValue(api), fakeAuth(permissions)],
    child: const MaterialApp(home: AttendanceInsightsScreen()),
  ));
  await tester.pumpAndSettle();
}

void patternTests() {
  testWidgets('pattern alerts name the person, the pattern in words and the days behind it', (tester) async {
    await _pumpToday(
      tester,
      _Repo(const [], patterns: {
        'as_of': '2026-10-14',
        'thresholds': _thresholds,
        'alerts': [
          {'employee_id': 'e1', 'kind': 'repeat_late', 'count': 7, 'dates': ['2026-10-12', '2026-10-09'], 'weekday': null},
          {'employee_id': 'e1', 'kind': 'repeat_absent_weekday', 'count': 3, 'dates': ['2026-10-05'], 'weekday': 0},
        ],
      }),
    );
    expect(find.textContaining('Often late: late on 7 days in the last 30'), findsOneWidget);
    expect(find.textContaining('and 5 earlier'), findsOneWidget);
    expect(find.textContaining('absent on 3 Mondays in the last 56 days'), findsOneWidget);
  });

  testWidgets('the card is left out when the caller may not see pattern alerts', (tester) async {
    await _pumpToday(tester, _Repo(const [], patternsForbidden: true));
    expect(find.text('Patterns to look at'), findsNothing);
    expect(find.text('Needs attention'), findsOneWidget);
  });
}

/// The fixes from docs/audits/ATTENDANCE_METRICS_WEB_MOBILE_AUDIT_2026-11-26.md (F1, F2, F7).
void auditFixTests() {
  testWidgets('F1: says the lists are partial when the day load stopped at the ceiling', (tester) async {
    await _pumpToday(tester, _Repo([day('1', 'e1', '2026-10-12', 'PRESENT')], serverTotal: 12500));
    expect(find.byKey(const ValueKey('days-truncated')), findsOneWidget);
    expect(find.textContaining('the most recent 1 of 12,500 in this range'), findsOneWidget);
  });

  testWidgets('F1: no partial note when every day was loaded', (tester) async {
    await _pumpToday(tester, _Repo([day('1', 'e1', '2026-10-12', 'PRESENT')]));
    expect(find.byKey(const ValueKey('days-truncated')), findsNothing);
  });

  testWidgets('F2: shows when the focus day was last calculated', (tester) async {
    await _pumpToday(tester, _Repo(const [], calculatedAt: '2026-10-14T04:05:00Z'));
    expect(find.textContaining('Last calculated'), findsOneWidget);
  });

  testWidgets('F2: no freshness line when the focus day has no rows yet', (tester) async {
    await _pumpToday(tester, _Repo(const []));
    expect(find.textContaining('Last calculated'), findsNothing);
  });

  testWidgets('F7: the payroll report is offered only in the organisation view', (tester) async {
    await _pumpToday(tester, _Repo(const []));
    await tester.tap(find.widgetWithText(Tab, 'Reports'));
    await tester.pumpAndSettle();
    expect(find.widgetWithText(ChoiceChip, 'Daily attendance'), findsOneWidget);
    expect(find.widgetWithText(ChoiceChip, 'Payroll attendance'), findsNothing);
  });

  test('F8: overtime totals add found, approved and still-pending minutes (web overtimeTotals)', () {
    final t = overtimeTotals([
      {'status': 'PENDING', 'minutes_detected': 90, 'minutes_approved': 30},
      {'status': 'APPROVED', 'minutes_detected': 60, 'minutes_approved': 60},
      {'status': 'REJECTED', 'minutes_detected': 45, 'minutes_approved': 0},
    ]);
    expect(t, (found: 195, approved: 90, pending: 60));
  });

  testWidgets('F7: the organisation view keeps the payroll report', (tester) async {
    await _pumpToday(tester, _Repo(const []), permissions: const [attendanceViewAll]);
    await tester.tap(find.widgetWithText(Tab, 'Reports'));
    await tester.pumpAndSettle();
    expect(find.widgetWithText(ChoiceChip, 'Payroll attendance'), findsOneWidget);
  });
}
