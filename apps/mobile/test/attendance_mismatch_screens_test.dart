import 'dart:convert';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:hrms_mobile/core/auth/permissions.dart';
import 'package:hrms_mobile/core/providers.dart';
import 'package:hrms_mobile/features/attendance/data/attendance_repository.dart';
import 'package:hrms_mobile/features/attendance/domain/attendance_insights.dart';
import 'package:hrms_mobile/features/attendance/presentation/attendance_mismatches_screen.dart';
import 'package:hrms_mobile/features/attendance/presentation/team_attendance_screen.dart';

import 'support/fake_api_client.dart';
import 'support/fake_auth.dart';

Map<String, dynamic> _dayJson(Map<String, dynamic> over) {
  final base = jsonDecode(File('test/fixtures/contract/attendance.AttendanceDayRead.sparse.json').readAsStringSync()) as Map<String, dynamic>;
  return {
    ...base,
    'id': 'day-1',
    'employee_id': 'e1',
    'attendance_date': '2026-11-13',
    'timezone': 'Asia/Kolkata',
    'attendance_status': 'PRESENT',
    'actual_first_in': '2026-11-13T04:00:00Z',
    'actual_last_out': '2026-11-13T12:30:00Z',
    'scheduled_start': '2026-11-13T04:00:00Z',
    'scheduled_end': '2026-11-13T12:30:00Z',
    'worked_minutes': 510,
    'late_minutes': 0,
    'is_locked': false,
    'breaks': <dynamic>[],
    'is_late': false,
    'is_early_out': false,
    'is_overtime': false,
    'missing_punch': false,
    'work_on_leave_flagged': false,
    'work_on_leave_resolution': null,
    'is_pending_approval': false,
    ...over,
  };
}

class _Repo implements AttendanceRepository {
  _Repo(this.days);
  final List<Map<String, dynamic>> days;
  final calls = <String>[];

  @override
  Future<List<AttendanceDay>> listAttendanceDays({String? employeeId, required String dateFrom, required String dateTo, String? attendanceStatus}) async {
    calls.add('days:$dateFrom:$dateTo');
    return days.map(AttendanceDay.fromJson).toList();
  }

  @override
  Future<AttendanceDay> keepLeaveOverPunches(String id, {required String reason}) async {
    calls.add('keep-leave:$id:$reason');
    return AttendanceDay.fromJson(days.firstWhere((d) => d['id'] == id));
  }

  @override
  dynamic noSuchMethod(Invocation invocation) => super.noSuchMethod(invocation);
}

final _employees = [
  {'id': 'e1', 'first_name': 'Asha', 'last_name': 'Rao', 'employee_code': 'E-1'},
  {'id': 'e2', 'first_name': 'Ravi', 'last_name': 'Iyer', 'employee_code': 'E-2'},
];

Future<(_Repo, FakeApiClient)> _pump(
  WidgetTester tester,
  Widget screen,
  List<Map<String, dynamic>> days, {
  List<String> permissions = const [attendancePunchOnBehalf, attendanceRecompute, attendanceRegularizationApprove],
  List<Map<String, dynamic>> pending = const [],
}) async {
  tester.view.physicalSize = const Size(800, 3000);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
  final repo = _Repo(days);
  final api = FakeApiClient(lists: {'/employees': _employees, '/regularizations': pending});
  await tester.pumpWidget(
    ProviderScope(overrides: [attendanceRepositoryProvider.overrideWithValue(repo), apiClientProvider.overrideWithValue(api), fakeAuth(permissions)], child: MaterialApp(home: screen)),
  );
  await tester.pumpAndSettle();
  return (repo, api);
}

void main() {
  group('team attendance: mismatches', () {
    final missingOut = _dayJson({'id': 'a', 'employee_id': 'e1', 'attendance_status': 'INCOMPLETE', 'missing_punch': true, 'actual_last_out': null});
    final fine = _dayJson({'id': 'b', 'employee_id': 'e2'});

    testWidgets('says what is wrong on the day and puts it ahead of the fine ones', (tester) async {
      await _pump(tester, const TeamAttendanceScreen(), [fine, missingOut]);
      expect(find.text('Checked in but never checked out.'), findsOneWidget);
      expect(find.widgetWithText(FilledButton, 'Add punch-out'), findsOneWidget);
      expect(find.widgetWithText(OutlinedButton, 'Open day'), findsOneWidget);
      // Asha has the problem, so she is listed before Ravi although the server sent Ravi first.
      final asha = tester.getTopLeft(find.textContaining('Asha Rao (E-1)')).dy;
      final ravi = tester.getTopLeft(find.textContaining('Ravi Iyer (E-2)')).dy;
      expect(asha, lessThan(ravi));
    });

    testWidgets('counts the days that need fixing and can narrow the list to them', (tester) async {
      await _pump(tester, const TeamAttendanceScreen(), [fine, missingOut]);
      expect(find.text("1 day doesn't add up and needs fixing."), findsOneWidget);
      await tester.tap(find.text('Show only these'));
      await tester.pumpAndSettle();
      expect(find.textContaining('Ravi Iyer (E-2)'), findsNothing);
      expect(find.textContaining('Asha Rao (E-1)'), findsOneWidget);
      await tester.tap(find.text('Show everyone'));
      await tester.pumpAndSettle();
      expect(find.textContaining('Ravi Iyer (E-2)'), findsOneWidget);
    });

    testWidgets('Add punch-out opens the punch form on Out, with the shift end as the time', (tester) async {
      await _pump(tester, const TeamAttendanceScreen(), [missingOut]);
      await tester.tap(find.widgetWithText(FilledButton, 'Add punch-out'));
      await tester.pumpAndSettle();
      expect(find.text('Record punch'), findsWidgets);
      expect(find.text('Out'), findsOneWidget); // the direction, already set
      // The time starts at the shift's own end (12:30Z = 6:00 pm IST on the day), not "now".
      final fields = tester.widgetList<EditableText>(find.byType(EditableText)).map((t) => t.controller.text);
      expect(fields, contains('Fri, 13 Nov · 18:00'));
    });

    testWidgets("offers the employee's own correction request first instead of a second fix", (tester) async {
      await _pump(
        tester,
        const TeamAttendanceScreen(),
        [missingOut],
        pending: [
          {'id': 'reg-9', 'employee_id': 'e1', 'attendance_date': '2026-11-13'},
        ],
      );
      expect(find.widgetWithText(FilledButton, 'Review correction request'), findsOneWidget);
      expect(find.text('Add punch-out'), findsNothing);
    });

    testWidgets('nothing punched on a working day offers Mark present, not a single punch', (tester) async {
      final none = _dayJson({'id': 'n', 'employee_id': 'e1', 'attendance_status': 'INCOMPLETE', 'missing_punch': true, 'actual_first_in': null, 'actual_last_out': null});
      await _pump(tester, const TeamAttendanceScreen(), [none]);
      expect(find.text('Nothing was punched on a working day.'), findsOneWidget);
      expect(find.text('Add punch-in'), findsNothing);
      await tester.tap(find.widgetWithText(FilledButton, 'Mark present'));
      await tester.pumpAndSettle();
      expect(find.text('Mark attendance'), findsWidgets);
    });

    testWidgets('keep leave asks for a reason, then keeps the leave', (tester) async {
      final onLeave = _dayJson({'id': 'l', 'employee_id': 'e1', 'work_on_leave_flagged': true});
      final (repo, _) = await _pump(tester, const TeamAttendanceScreen(), [onLeave]);
      expect(find.text('Punched in on a day of approved leave.'), findsOneWidget);
      expect(find.widgetWithText(OutlinedButton, 'Cancel leave'), findsOneWidget);
      await tester.tap(find.widgetWithText(FilledButton, 'Keep leave'));
      await tester.pumpAndSettle();
      await tester.tap(find.widgetWithText(FilledButton, 'Keep leave').last);
      await tester.pumpAndSettle();
      expect(find.text('A reason is required.'), findsOneWidget);
      await tester.enterText(find.byType(TextField).last, 'Approved earlier');
      await tester.tap(find.widgetWithText(FilledButton, 'Keep leave').last);
      await tester.pumpAndSettle();
      expect(repo.calls.where((c) => c.startsWith('keep-leave')), ['keep-leave:l:Approved earlier']);
    });

    testWidgets('without the permissions it still says what is wrong, but offers only Open day', (tester) async {
      await _pump(tester, const TeamAttendanceScreen(), [missingOut], permissions: const []);
      expect(find.text('Checked in but never checked out.'), findsOneWidget);
      expect(find.text('Add punch-out'), findsNothing);
      expect(find.widgetWithText(FilledButton, 'Open day'), findsOneWidget);
    });

    testWidgets('a fine day shows no banner and no fix controls', (tester) async {
      await _pump(tester, const TeamAttendanceScreen(), [fine]);
      expect(find.textContaining('need fixing'), findsNothing);
      expect(find.text('Open day'), findsNothing);
    });
  });

  group('days that need fixing (range)', () {
    testWidgets('lists only the days that do not add up across the range, newest first, with fixes', (tester) async {
      final older = _dayJson({'id': 'old', 'employee_id': 'e2', 'attendance_date': '2026-11-06', 'attendance_status': 'INCOMPLETE', 'missing_punch': true, 'actual_last_out': null});
      final newer = _dayJson({
        'id': 'new',
        'employee_id': 'e1',
        'attendance_date': '2026-11-13',
        'attendance_status': 'INCOMPLETE',
        'missing_punch': true,
        'actual_first_in': null,
        'actual_last_out': null,
      });
      final fine = _dayJson({'id': 'ok', 'employee_id': 'e1', 'attendance_date': '2026-11-10'});
      final (repo, _) = await _pump(tester, const AttendanceMismatchesScreen(from: '2026-11-01', to: '2026-11-18'), [older, fine, newer]);
      expect(repo.calls, ['days:2026-11-01:2026-11-18']);
      expect(find.text('01 Nov – 18 Nov · 2 days'), findsOneWidget);
      expect(find.text('Nothing was punched on a working day.'), findsOneWidget);
      expect(find.text('Checked in but never checked out.'), findsOneWidget);
      expect(find.textContaining('Asha Rao (E-1)'), findsOneWidget); // the fine day is not listed
      final newOne = tester.getTopLeft(find.text('Nothing was punched on a working day.')).dy;
      final oldOne = tester.getTopLeft(find.text('Checked in but never checked out.')).dy;
      expect(newOne, lessThan(oldOne));
    });

    testWidgets('says so when every day adds up', (tester) async {
      await _pump(tester, const AttendanceMismatchesScreen(from: '2026-11-01', to: '2026-11-18'), [
        _dayJson({'id': 'ok'}),
      ]);
      expect(find.text('Nothing needs fixing'), findsOneWidget);
    });
  });

  group('needs attention', () {
    test('marks the items whose days can be fixed, and not late or early-out', () {
      final rows = [
        AttendanceDay.fromJson(_dayJson({'id': '1', 'attendance_status': 'INCOMPLETE', 'missing_punch': true, 'actual_last_out': null})),
        AttendanceDay.fromJson(_dayJson({'id': '2', 'is_late': true, 'late_minutes': 9, 'is_early_out': true})),
      ];
      final items = buildAttentionItems(rows: rows, pendingRegularizations: 3, pendingOvertime: 0, blockedPeriods: 0);
      bool fixable(String label) => items.firstWhere((i) => i.label == label).fixable;
      expect(fixable('Missing punches'), isTrue);
      expect(fixable('Incomplete attendance'), isTrue);
      expect(fixable('Late arrivals'), isFalse);
      expect(fixable('Early departures'), isFalse);
      expect(fixable('Corrections pending'), isFalse); // has its own route
    });
  });
}
