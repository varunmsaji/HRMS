import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:hrms_mobile/core/auth/permissions.dart';
import 'package:hrms_mobile/core/providers.dart';
import 'package:hrms_mobile/core/theme/app_theme.dart';
import 'package:hrms_mobile/features/attendance/data/attendance_repository.dart';
import 'package:hrms_mobile/features/attendance/domain/employee_attendance_summary.dart';
import 'package:hrms_mobile/features/attendance/presentation/employee_attendance_panel.dart';
import 'package:hrms_mobile/features/attendance/presentation/employee_attendance_profile_screen.dart';

import 'support/fake_api_client.dart';
import 'support/fake_auth.dart';

/// HR's view of one employee's attendance — web `attendance/employee/[employeeId]/page.tsx`,
/// `EmployeeMonthView`, and the range summary of `employee-attendance-panel.tsx`.

// 2026-10-15 12:00 IST.
final _now = DateTime.utc(2026, 10, 15, 6, 30);

Map<String, dynamic> _row(String date, String status, {Map<String, dynamic> over = const {}}) => {
      'id': 'd-$date',
      'employee_id': 'e-1',
      'attendance_date': date,
      'attendance_status': status,
      'timezone': 'Asia/Kolkata',
      'actual_first_in': status == 'ABSENT' ? null : '${date}T03:30:00Z',
      'actual_last_out': status == 'ABSENT' ? null : '${date}T12:30:00Z',
      'worked_minutes': status == 'ABSENT' ? 0 : 480,
      'is_locked': false,
      ...over,
    };

AttendanceDay _day(String date, String status, {Map<String, dynamic> over = const {}}) => AttendanceDay.fromJson(_row(date, status, over: over));

class _Repo implements AttendanceRepository {
  _Repo(this.rows, {this.punches = const []});
  final List<Map<String, dynamic>> rows;
  final List<Map<String, dynamic>> punches;
  final asked = <(String, String)>[];

  @override
  Future<List<AttendanceDay>> listAttendanceDays({String? employeeId, required String dateFrom, required String dateTo, String? attendanceStatus}) async {
    asked.add((dateFrom, dateTo));
    return [
      for (final r in rows)
        if ((r['attendance_date'] as String).compareTo(dateFrom) >= 0 && (r['attendance_date'] as String).compareTo(dateTo) <= 0) AttendanceDay.fromJson(r),
    ];
  }

  @override
  Future<List<Punch>> listPunches({required String employeeId, required String dateFrom, required String dateTo}) async => punches.map(Punch.fromJson).toList();

  @override
  dynamic noSuchMethod(Invocation invocation) => super.noSuchMethod(invocation);
}

void main() {
  group('summary helpers', () {
    test('range presets come from the business date', () {
      final p = attendanceRangePresets('2026-03-05');
      expect(p.map((e) => (e.label, e.from, e.to)), [
        ('Last 7 days', '2026-02-27', '2026-03-05'),
        ('This month', '2026-03-01', '2026-03-05'),
        ('Last month', '2026-02-01', '2026-02-28'),
      ]);
    });

    test('month bounds stop at today', () {
      expect(attendanceMonthBounds('2026-10', '2026-10-15'), (from: '2026-10-01', to: '2026-10-15'));
      expect(attendanceMonthBounds('2026-09', '2026-10-15'), (from: '2026-09-01', to: '2026-09-30'));
    });

    test('counts follow web summarizeMonth; worked time only from days with a check-in', () {
      final s = AttendanceRangeSummary.compute([
        _day('2026-10-01', 'PRESENT', over: {'is_late': true, 'ot_minutes_detected': 60, 'ot_minutes_approved': 30}),
        _day('2026-10-02', 'WFH'),
        _day('2026-10-03', 'ABSENT', over: {'worked_minutes': 99}),
        _day('2026-10-04', 'INCOMPLETE', over: {'missing_punch': true, 'actual_last_out': null}),
        _day('2026-10-05', 'NOT_EXPECTED', over: {'calendar_day_type': 'WEEKLY_OFF', 'actual_first_in': null}),
      ]);
      expect(s.present, 2);
      expect(s.count('ABSENT'), 1);
      expect(s.count('WEEKLY_OFF'), 1);
      expect(s.late, 1);
      expect(s.missingPunch, 1);
      expect(s.otDetectedMinutes, 60);
      expect(s.otApprovedMinutes, 30);
      expect(s.workedMinutes, 480 * 3);
    });

    test('problem labels and presence', () {
      expect(attendanceProblemLabels(_day('2026-10-04', 'INCOMPLETE', over: {'missing_punch': true, 'is_pending_approval': true})), ['Missing punch', 'Incomplete', 'Pending approval']);
      expect(attendancePresenceLabel(_day('2026-10-04', 'PRESENT')), 'Checked out');
      expect(attendancePresenceLabel(_day('2026-10-04', 'INCOMPLETE', over: {'actual_last_out': null})), 'Working');
      expect(
        attendancePresenceLabel(_day('2026-10-04', 'INCOMPLETE', over: {
          'actual_last_out': null,
          'breaks': [
            {'break_start': '2026-10-04T07:00:00Z', 'break_end': null},
          ],
        })),
        'On break',
      );
      expect(attendancePresenceLabel(_day('2026-10-04', 'ABSENT')), 'Not checked in');
    });
  });

  group('profile screen', () {
    Future<FakeApiClient> pump(WidgetTester tester, _Repo repo, {List<Map<String, dynamic>> regs = const []}) async {
      tester.view.physicalSize = const Size(420, 3200);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.reset);
      final api = FakeApiClient(lists: {'/regularizations': regs});
      await tester.pumpWidget(ProviderScope(
        overrides: [attendanceRepositoryProvider.overrideWithValue(repo), apiClientProvider.overrideWithValue(api), fakeAuth(const [attendanceView, attendanceViewAll])],
        child: MaterialApp(theme: AppTheme.employee, home: EmployeeAttendanceProfileScreen(employeeId: 'e-1', employeeLabel: 'Asha Rao', now: _now)),
      ));
      await tester.pumpAndSettle();
      return api;
    }

    testWidgets("today's status, times and punches in the company zone", (tester) async {
      await pump(
        tester,
        _Repo([_row('2026-10-15', 'INCOMPLETE', over: {'actual_last_out': null, 'scheduled_start': '2026-10-15T03:30:00Z', 'scheduled_end': '2026-10-15T12:30:00Z'})], punches: [
          {'id': 'p1', 'employee_id': 'e-1', 'punch_time': '2026-10-15T03:30:00Z', 'direction': 'IN', 'source': 'MOBILE'},
        ]),
      );
      expect(find.text('Asha Rao'), findsOneWidget);
      expect(find.text('Working'), findsOneWidget);
      expect(find.text('Check-in'), findsOneWidget);
      expect(find.textContaining('9:00 am'), findsWidgets);
      expect(find.textContaining('IN 9:00 am'), findsOneWidget);
      expect(find.text('Full day detail →'), findsOneWidget);
    });

    testWidgets('no row for today says so', (tester) async {
      await pump(tester, _Repo(const []));
      expect(find.text('No attendance record for today yet.'), findsOneWidget);
    });

    testWidgets('the month: figures, issues newest first, and the requests', (tester) async {
      final api = await pump(
        tester,
        _Repo([
          _row('2026-10-01', 'PRESENT', over: {'is_late': true}),
          _row('2026-10-02', 'ABSENT'),
          _row('2026-10-06', 'INCOMPLETE', over: {'missing_punch': true, 'actual_last_out': null}),
          _row('2026-10-08', 'CONFIG_ERROR', over: {'actual_first_in': null, 'actual_last_out': null}),
        ]),
        regs: [
          {'id': 'r1', 'attendance_date': '2026-10-06', 'request_type': 'MISSING_PUNCH', 'status': 'SUBMITTED'},
        ],
      );
      expect(api.listCalls.single.filters, {'employee_id': 'e-1'});
      expect(find.text('Late arrivals'), findsOneWidget);
      expect(find.text('ATTENDANCE ISSUES'), findsOneWidget);
      final issueDates = tester.widgetList<Text>(find.descendant(of: find.byType(ListTile), matching: find.byType(Text))).map((t) => t.data).where((d) => d == '8 Oct' || d == '6 Oct').toList();
      expect(issueDates.take(2), ['8 Oct', '6 Oct']);
      expect(find.text('Missing punch'), findsWidgets);
      expect(find.text('Config error'), findsWidgets);
      expect(find.text('REGULARIZATION REQUESTS'), findsOneWidget);
      expect(find.text('Submitted'), findsOneWidget);
    });

    testWidgets('requests that fail to load say so; the rest still shows', (tester) async {
      tester.view.physicalSize = const Size(420, 3200);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.reset);
      await tester.pumpWidget(ProviderScope(
        overrides: [
          attendanceRepositoryProvider.overrideWithValue(_Repo(const [])),
          apiClientProvider.overrideWithValue(FakeApiClient(failing: {'/regularizations': Exception('x')})),
          fakeAuth(const [attendanceView]),
        ],
        child: MaterialApp(theme: AppTheme.employee, home: EmployeeAttendanceProfileScreen(employeeId: 'e-1', employeeLabel: 'Asha Rao', now: _now)),
      ));
      await tester.pumpAndSettle();
      expect(find.text("Regularization requests couldn't be loaded."), findsOneWidget);
      expect(find.text('No attendance issues this month.'), findsOneWidget);
    });
  });

  group('record tab panel', () {
    testWidgets('opens on Last 7 days, shows the range summary, and a quick range reloads', (tester) async {
      tester.view.physicalSize = const Size(420, 2400);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.reset);
      final today = DateTime.now().toUtc().add(const Duration(hours: 5, minutes: 30)).toIso8601String().substring(0, 10);
      final repo = _Repo([_row(today, 'PRESENT', over: {'missing_punch': true})]);
      await tester.pumpWidget(ProviderScope(
        overrides: [attendanceRepositoryProvider.overrideWithValue(repo), fakeAuth(const [attendanceView])],
        child: MaterialApp(theme: AppTheme.employee, home: const Scaffold(body: EmployeeAttendancePanel(employeeId: 'e-1'))),
      ));
      await tester.pumpAndSettle();
      final presets = attendanceRangePresets(today);
      expect(repo.asked.single, (presets[0].from, presets[0].to));
      expect(tester.widget<ChoiceChip>(find.widgetWithText(ChoiceChip, 'Last 7 days')).selected, isTrue);
      expect(find.text('Missing punch'), findsWidgets);
      expect(find.text('8h 0m'), findsWidgets);
      await tester.tap(find.text('Last month'));
      await tester.pumpAndSettle();
      expect(repo.asked.last, (presets[2].from, presets[2].to));
    });
  });
}
