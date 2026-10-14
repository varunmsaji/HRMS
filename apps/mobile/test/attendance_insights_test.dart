import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:hrms_mobile/core/providers.dart';
import 'package:hrms_mobile/features/attendance/data/attendance_repository.dart';
import 'package:hrms_mobile/features/attendance/domain/attendance_insights.dart';
import 'package:hrms_mobile/features/attendance/presentation/attendance_insights_screen.dart';

import 'support/fake_api_client.dart';
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
  group('insights logic', () {
    test('ranges resolve like the web presets', () {
      expect(resolveInsightsRange(InsightsRange.week, '2026-10-14'), (from: '2026-10-12', to: '2026-10-14'));
      expect(resolveInsightsRange(InsightsRange.month, '2026-10-14'), (from: '2026-10-01', to: '2026-10-14'));
      expect(resolveInsightsRange(InsightsRange.last14, '2026-10-14'), (from: '2026-10-01', to: '2026-10-14'));
    });

    test('trend percentages use expected days as the denominator and gap when it is zero', () {
      final days = [
        day('1', 'a', '2026-10-12', 'PRESENT', firstIn: 't', worked: 480),
        day('2', 'b', '2026-10-12', 'ABSENT'),
        day('3', 'a', '2026-10-13', 'NOT_EXPECTED', extra: {'calendar_day_type': 'WEEKLY_OFF'}),
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
      expect(items.map((i) => i.label), containsAll(['Configuration errors', 'Late arrivals', 'Regularization pending', 'Payroll period blocked']));
      expect(items.firstWhere((i) => i.label == 'Regularization pending').route, '/app/regularizations');
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
    expect(find.text('Needs attention'), findsOneWidget);
    expect(find.text('Regularization pending'), findsOneWidget);
    expect(find.text('Attendance trend'), findsOneWidget);
    expect(find.text('Leave & absence'), findsOneWidget);
    expect(find.text('Work hours'), findsOneWidget);
    expect(find.text('Overtime'), findsWidgets);
    expect(find.text('Something went wrong.'), findsOneWidget); // overtime section only
    expect(find.text('Attendance heatmap'), findsOneWidget);
    expect(find.textContaining('Not available yet'), findsOneWidget);
  });
}

class _Repo implements AttendanceRepository {
  _Repo(this.days);
  final List<AttendanceDay> days;

  @override
  Future<List<AttendanceDay>> listAttendanceDays({String? employeeId, required String dateFrom, required String dateTo, String? attendanceStatus}) async => days;

  @override
  dynamic noSuchMethod(Invocation invocation) => super.noSuchMethod(invocation);
}
