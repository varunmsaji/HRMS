import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:hrms_mobile/core/auth/permissions.dart';
import 'package:hrms_mobile/core/theme/app_theme.dart';
import 'package:hrms_mobile/core/time.dart';
import 'package:hrms_mobile/features/attendance/data/attendance_repository.dart';
import 'package:hrms_mobile/features/attendance/presentation/attendance_day_detail_screen.dart';
import 'package:hrms_mobile/features/attendance/presentation/attendance_month_card.dart';

import 'support/fake_auth.dart';
import 'support/test_themes.dart';

const _zone = 'Asia/Kolkata';

Map<String, dynamic> _row(String id, String date, String status, {Map<String, dynamic> over = const {}}) => {
      'id': id,
      'employee_id': 'e-1',
      'attendance_date': date,
      'attendance_status': status,
      'timezone': _zone,
      'actual_first_in': '${date}T04:00:00Z',
      'actual_last_out': '${date}T12:30:00Z',
      'worked_minutes': 510,
      'is_locked': false,
      'calculation_version': 3,
      'calculated_at': '${date}T12:31:00Z',
      ...over,
    };

class _Repo implements AttendanceRepository {
  _Repo(this.rows, {this.projections = const []});
  final List<Map<String, dynamic>> rows;
  final List<LeaveDayProjection> projections;

  @override
  Future<List<AttendanceDay>> listAttendanceDays({String? employeeId, required String dateFrom, required String dateTo, String? attendanceStatus}) async =>
      rows.map(AttendanceDay.fromJson).toList();

  @override
  Future<AttendanceDay> getAttendanceDay(String id) async => AttendanceDay.fromJson(rows.firstWhere((r) => r['id'] == id));

  @override
  Future<List<LeaveDayProjection>> listLeaveProjections({required String employeeId, required String dateFrom, required String dateTo}) async => projections;

  @override
  dynamic noSuchMethod(Invocation invocation) => super.noSuchMethod(invocation);
}

Future<void> _pumpMonth(WidgetTester tester, _Repo repo, {double width = 360}) async {
  tester.view.physicalSize = Size(width, 900);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
  await tester.pumpWidget(ProviderScope(
    overrides: [attendanceRepositoryProvider.overrideWithValue(repo), fakeAuth(const [attendanceView], employeeId: 'e-1')],
    child: MaterialApp(theme: AppTheme.employee, home: Scaffold(body: SingleChildScrollView(child: Padding(padding: const EdgeInsets.all(16), child: AttendanceMonthCard(employeeId: 'e-1', zone: _zone))))),
  ));
  await tester.pumpAndSettle();
}

void main() {
  setUpAll(primeThemes);

  group('month card (T1-07)', () {
    final today = businessToday(_zone);
    final yesterdayish = '${today.substring(0, 8)}01';

    testWidgets('Monday-first two-letter labels', (tester) async {
      await _pumpMonth(tester, _Repo([]));
      final labels = ['Mo', 'Tu', 'We', 'Th', 'Fr', 'Sa', 'Su'];
      final lefts = [for (final l in labels) tester.getTopLeft(find.text(l)).dx];
      expect(lefts, [...lefts]..sort());
      for (final l in labels) {
        expect(find.text(l), findsOneWidget);
      }
    });

    testWidgets('a recorded day has a glyph and a spoken label; a day with no record is plain and not tappable', (tester) async {
      await _pumpMonth(tester, _Repo([_row('d1', yesterdayish, 'PRESENT')]));
      expect(find.byIcon(Icons.check_rounded), findsWidgets);
      final day = DateTime.parse(yesterdayish);
      const months = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'];
      expect(find.bySemanticsLabel(RegExp('^1 ${months[day.month - 1]}, Present')), findsOneWidget);
      expect(find.bySemanticsLabel(RegExp('No record')), findsWidgets);
    });

    testWidgets('legend names the statuses present this month, and the summary uses the shared buckets', (tester) async {
      await _pumpMonth(tester, _Repo([_row('d1', yesterdayish, 'PRESENT'), _row('d2', '${today.substring(0, 8)}02', 'LEAVE')]));
      expect(find.text('Present'), findsOneWidget);
      expect(find.text('On leave'), findsOneWidget);
      expect(find.byWidgetPredicate((w) => w is Semantics && w.properties.label == 'Present 1'), findsOneWidget);
      expect(find.byWidgetPredicate((w) => w is Semantics && w.properties.label == 'Absent 0'), findsOneWidget);
      expect(find.byWidgetPredicate((w) => w is Semantics && w.properties.label == 'Leave 1'), findsOneWidget);
    });

    testWidgets('today carries a ring', (tester) async {
      await _pumpMonth(tester, _Repo([]));
      final ringed = tester.widgetList<Container>(find.byType(Container)).where((c) {
        final d = c.decoration;
        return d is BoxDecoration && d.border is Border && (d.border! as Border).top.width == 1.5;
      });
      expect(ringed, hasLength(1));
    });

    testWidgets('fits a 320 px phone at text scale 2.0 without overflow', (tester) async {
      tester.platformDispatcher.textScaleFactorTestValue = 2.0;
      addTearDown(tester.platformDispatcher.clearTextScaleFactorTestValue);
      await _pumpMonth(tester, _Repo([_row('d1', yesterdayish, 'PRESENT')]), width: 320);
      expect(tester.takeException(), isNull);
    });
  });

  group('day detail (T1-08)', () {
    Future<void> pump(WidgetTester tester, List<String> permissions) async {
      tester.view.physicalSize = const Size(800, 4000);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.reset);
      await tester.pumpWidget(ProviderScope(
        overrides: [attendanceRepositoryProvider.overrideWithValue(_Repo([_row('day-1', '2026-10-01', 'PRESENT')])), fakeAuth(permissions)],
        child: MaterialApp(theme: AppTheme.employee, home: const AttendanceDayDetailScreen(dayId: 'day-1')),
      ));
      await tester.pumpAndSettle();
    }

    testWidgets('the gradient hero is gone; a status header with the status chip, date and worked time replaces it', (tester) async {
      await pump(tester, const [attendanceView]);
      expect(find.text('Present'), findsWidgets);
      expect(find.text('2026-10-01'), findsOneWidget);
      expect(find.text('8h 30m'), findsWidgets);
      final gradients = tester.widgetList<Container>(find.byType(Container)).where((c) => c.decoration is BoxDecoration && (c.decoration! as BoxDecoration).gradient != null);
      expect(gradients, isEmpty);
    });

    testWidgets('calculation details are collapsed for everyone and expand to the version', (tester) async {
      await pump(tester, const [attendanceView]);
      expect(find.text('Calculation details'), findsOneWidget);
      expect(find.text('Calculation version'), findsNothing);
      await tester.tap(find.text('Calculation details'));
      await tester.pumpAndSettle();
      expect(find.text('Calculation version'), findsOneWidget);
    });

    testWidgets('an employee never sees Recompute', (tester) async {
      await pump(tester, const [attendanceView]);
      expect(find.text('Recompute'), findsNothing);
    });

    testWidgets('a user with the permission does', (tester) async {
      await pump(tester, const [attendanceView, attendanceRecompute]);
      expect(find.text('Recompute'), findsOneWidget);
    });
  });

  group('day detail states (T1-08)', () {
    Future<void> pumpRow(WidgetTester tester, Map<String, dynamic> row, {List<String> permissions = const [attendanceView], List<LeaveDayProjection> projections = const []}) async {
      tester.view.physicalSize = const Size(390, 3000);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.reset);
      await tester.pumpWidget(ProviderScope(
        overrides: [attendanceRepositoryProvider.overrideWithValue(_Repo([row], projections: projections)), fakeAuth(permissions)],
        child: MaterialApp(theme: AppTheme.employee, home: AttendanceDayDetailScreen(dayId: row['id'] as String)),
      ));
      await tester.pumpAndSettle();
    }

    testWidgets('historical complete day: worked figure, first in / last out, rows with values only', (tester) async {
      await pumpRow(tester, _row('h', '2026-09-15', 'PRESENT', over: {'scheduled_start': '2026-09-15T04:00:00Z', 'scheduled_end': '2026-09-15T12:30:00Z', 'scheduled_minutes': 510, 'unpaid_break_minutes': 0}));
      expect(find.text('8h 30m'), findsWidgets);
      expect(find.textContaining('First in 9:30 am IST'), findsOneWidget);
      expect(find.text('SCHEDULE'), findsOneWidget);
      expect(find.text('Unpaid break'), findsNothing, reason: 'a zero value is left out');
      expect(find.text('OVERTIME AND PAY'), findsNothing, reason: 'a section with nothing to show is not drawn');
    });

    testWidgets('incomplete day (in, no out): no worked figure, says the punch-out is missing', (tester) async {
      await pumpRow(tester, _row('i', '2026-09-15', 'INCOMPLETE', over: {'actual_last_out': null, 'worked_minutes': 0, 'missing_punch': true}));
      expect(find.text('Incomplete'), findsOneWidget);
      expect(find.textContaining('no punch-out recorded'), findsOneWidget);
      expect(find.text('0h 0m'), findsNothing);
      expect(find.text('Missing punch'), findsOneWidget);
    });

    testWidgets('day without punches: says so, no times invented', (tester) async {
      await pumpRow(tester, _row('n', '2026-09-15', 'ABSENT', over: {'actual_first_in': null, 'actual_last_out': null}));
      expect(find.text('Absent'), findsOneWidget);
      expect(find.text('No punches recorded'), findsOneWidget);
    });

    testWidgets('today\'s placeholder row reads "Not punched in yet", never Absent', (tester) async {
      final today = businessToday(_zone);
      await pumpRow(tester, _row('t', today, 'ABSENT', over: {'actual_first_in': null, 'actual_last_out': null}));
      expect(find.text('Not punched in yet'), findsOneWidget);
      expect(find.text('Absent'), findsNothing);
    });

    testWidgets('flag chips use the status chip (labelled for screen readers); locked is shown', (tester) async {
      await pumpRow(tester, _row('f', '2026-09-15', 'PRESENT', over: {'is_late': true, 'is_overtime': true, 'is_locked': true}));
      expect(find.text('Late'), findsWidgets);
      expect(find.text('Overtime'), findsWidgets);
      expect(find.text('Locked'), findsOneWidget);
      expect(find.byWidgetPredicate((w) => w is Semantics && w.properties.label == 'Status: Late'), findsOneWidget);
    });

    testWidgets('approved leave on the date appears as its own section', (tester) async {
      await pumpRow(tester, _row('l', '2026-09-15', 'LEAVE', over: {'actual_first_in': null, 'actual_last_out': null}),
          projections: [LeaveDayProjection(leaveApplicationId: 'abcdefgh-1', fraction: '1.0', isPaid: true, status: 'APPROVED')]);
      expect(find.text('APPROVED LEAVE ON THIS DATE'), findsOneWidget);
      expect(find.text('Paid · APPROVED'), findsOneWidget);
    });

    testWidgets('calculation details keep every version and timestamp behind the tile', (tester) async {
      await pumpRow(tester, _row('c', '2026-09-15', 'PRESENT', over: {'attendance_policy_version_id': 'apv-1', 'overtime_policy_version_id': 'opv-1'}));
      await tester.drag(find.byType(ListView).first, const Offset(0, -3000));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Calculation details'));
      await tester.pumpAndSettle();
      expect(find.text('Calculation version'), findsOneWidget);
      expect(find.text('Calculated at'), findsOneWidget);
      expect(find.text('apv-1'), findsOneWidget);
    });

    testWidgets('HR gates: Keep leave only for an unresolved flagged day with the permission', (tester) async {
      final row = _row('k', '2026-09-15', 'PRESENT', over: {'work_on_leave_flagged': true, 'work_on_leave_resolution': null});
      await pumpRow(tester, row, permissions: const [attendanceView]);
      expect(find.text('Keep leave'), findsNothing);
      expect(find.text('Recompute'), findsNothing);
    });

    testWidgets('HR with the permission gets Recompute and Keep leave', (tester) async {
      final row = _row('k', '2026-09-15', 'PRESENT', over: {'work_on_leave_flagged': true, 'work_on_leave_resolution': null});
      await pumpRow(tester, row, permissions: const [attendanceView, attendanceRecompute]);
      expect(find.text('Recompute'), findsOneWidget);
      expect(find.text('Keep leave'), findsOneWidget);
    });

    for (final size in [const Size(320, 568), const Size(360, 800)]) {
      testWidgets('no overflow at ${size.width.toInt()} px and 2x text with every section populated', (tester) async {
        tester.view.physicalSize = size;
        tester.view.devicePixelRatio = 1;
        addTearDown(tester.view.reset);
        final row = _row('z', '2026-09-15', 'PRESENT', over: {
          'is_late': true, 'is_overtime': true, 'missing_punch': true, 'late_minutes': 12, 'ot_minutes_detected': 30, 'unpaid_break_minutes': 20,
          'scheduled_start': '2026-09-15T04:00:00Z', 'scheduled_end': '2026-09-15T12:30:00Z', 'scheduled_minutes': 510, 'paid_day_fraction': '1.0',
          'breaks': [{'break_start': '2026-09-15T07:00:00Z', 'break_end': '2026-09-15T07:20:00Z', 'minutes': 20, 'is_paid': false}],
        });
        await tester.pumpWidget(ProviderScope(
          overrides: [attendanceRepositoryProvider.overrideWithValue(_Repo([row])), fakeAuth(const [attendanceView, attendanceRecompute])],
          child: MaterialApp(
            theme: AppTheme.employee,
            builder: (context, child) => MediaQuery(data: MediaQuery.of(context).copyWith(textScaler: const TextScaler.linear(2.0)), child: child!),
            home: const AttendanceDayDetailScreen(dayId: 'z'),
          ),
        ));
        await tester.pumpAndSettle();
        await tester.drag(find.byType(ListView).first, const Offset(0, -4000));
        await tester.pumpAndSettle();
        expect(tester.takeException(), isNull);
      });
    }
  });
}
