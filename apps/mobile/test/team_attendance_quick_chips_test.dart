import 'dart:convert';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:hrms_mobile/core/auth/permissions.dart';
import 'package:hrms_mobile/core/providers.dart';
import 'package:hrms_mobile/features/attendance/data/attendance_repository.dart';
import 'package:hrms_mobile/features/attendance/presentation/team_attendance_screen.dart';

import 'support/fake_api_client.dart';
import 'support/fake_auth.dart';

Map<String, dynamic> _day(Map<String, dynamic> over) {
  final base = jsonDecode(File('test/fixtures/contract/attendance.AttendanceDayRead.sparse.json').readAsStringSync()) as Map<String, dynamic>;
  return {
    ...base,
    'id': 'day',
    'employee_id': 'e1',
    'attendance_date': '2026-11-13',
    'timezone': 'Asia/Kolkata',
    'attendance_status': 'PRESENT',
    'actual_first_in': '2026-11-13T04:00:00Z',
    'actual_last_out': '2026-11-13T12:30:00Z',
    'worked_minutes': 510,
    'late_minutes': 0,
    'is_locked': false,
    'breaks': <dynamic>[],
    'is_late': false,
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

  @override
  Future<List<AttendanceDay>> listAttendanceDays({String? employeeId, required String dateFrom, required String dateTo, String? attendanceStatus}) async => days.map(AttendanceDay.fromJson).toList();

  @override
  dynamic noSuchMethod(Invocation invocation) => super.noSuchMethod(invocation);
}

final _employees = [
  {'id': 'e1', 'first_name': 'Asha', 'last_name': 'Rao', 'employee_code': 'E-1'},
  {'id': 'e2', 'first_name': 'Ravi', 'last_name': 'Iyer', 'employee_code': 'E-2'},
  {'id': 'e3', 'first_name': 'Meena', 'last_name': 'Das', 'employee_code': 'E-3'},
  {'id': 'e4', 'first_name': 'Kiran', 'last_name': 'Nair', 'employee_code': 'E-4'},
];

// Asha is late, Ravi has not checked in, Meena forgot to punch out, Kiran is fine.
final _late = _day({'id': 'a', 'employee_id': 'e1', 'late_minutes': 20, 'is_late': true});
final _notIn = _day({'id': 'b', 'employee_id': 'e2', 'attendance_status': 'ABSENT', 'actual_first_in': null, 'actual_last_out': null, 'worked_minutes': 0});
final _missing = _day({'id': 'c', 'employee_id': 'e3', 'attendance_status': 'INCOMPLETE', 'missing_punch': true, 'actual_last_out': null});
final _fine = _day({'id': 'd', 'employee_id': 'e4'});

Future<void> _pump(WidgetTester tester, List<Map<String, dynamic>> days, {String? date}) async {
  tester.view.physicalSize = const Size(800, 3000);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
  final api = FakeApiClient(lists: {'/employees': _employees, '/regularizations': const []}, objects: {});
  await tester.pumpWidget(
    ProviderScope(
      overrides: [attendanceRepositoryProvider.overrideWithValue(_Repo(days)), apiClientProvider.overrideWithValue(api), fakeAuth(const [attendancePunchOnBehalf])],
      child: MaterialApp(home: TeamAttendanceScreen(date: date)),
    ),
  );
  await tester.pumpAndSettle();
}

Finder _person(String label) => find.textContaining(label);
Finder _chip(String key) => find.byKey(ValueKey('quick_$key'));

void main() {
  final all = [_late, _notIn, _missing, _fine];

  testWidgets('today shows Not in yet, Late and Missing punch, each with its count', (tester) async {
    await _pump(tester, all);
    expect(find.descendant(of: _chip('not_checked_in'), matching: find.text('Not in yet 1')), findsOneWidget);
    expect(find.descendant(of: _chip('late'), matching: find.text('Late 1')), findsOneWidget);
    expect(find.descendant(of: _chip('missing_punch'), matching: find.text('Missing punch 1')), findsOneWidget);
  });

  testWidgets('Late narrows the list to the late people, and tapping it again shows everyone', (tester) async {
    await _pump(tester, all);
    await tester.tap(_chip('late'));
    await tester.pumpAndSettle();
    expect(_person('Asha Rao'), findsOneWidget);
    expect(_person('Ravi Iyer'), findsNothing);
    expect(_person('Kiran Nair'), findsNothing);
    // The chip itself says what is on; no second "Showing" tag.
    expect(find.textContaining('Showing:'), findsNothing);
    await tester.tap(_chip('late'));
    await tester.pumpAndSettle();
    expect(_person('Kiran Nair'), findsOneWidget);
    expect(_person('Ravi Iyer'), findsOneWidget);
  });

  testWidgets('Not in yet and Late switch between each other', (tester) async {
    await _pump(tester, all);
    await tester.tap(_chip('not_checked_in'));
    await tester.pumpAndSettle();
    expect(_person('Ravi Iyer'), findsOneWidget);
    expect(_person('Asha Rao'), findsNothing);
    await tester.tap(_chip('late'));
    await tester.pumpAndSettle();
    expect(_person('Asha Rao'), findsOneWidget);
    expect(_person('Ravi Iyer'), findsNothing);
  });

  testWidgets('Missing punch narrows the list and counts as an active filter', (tester) async {
    await _pump(tester, all);
    expect(find.text('Filter'), findsOneWidget);
    await tester.tap(_chip('missing_punch'));
    await tester.pumpAndSettle();
    expect(_person('Meena Das'), findsOneWidget);
    expect(_person('Kiran Nair'), findsNothing);
    expect(find.text('Filter (1)'), findsOneWidget);
    await tester.tap(_chip('missing_punch'));
    await tester.pumpAndSettle();
    expect(_person('Kiran Nair'), findsOneWidget);
    expect(find.text('Filter'), findsOneWidget);
  });

  testWidgets('a past day has no Not in yet chip, but keeps Late and Missing punch', (tester) async {
    await _pump(tester, all, date: '2026-11-13');
    expect(_chip('not_checked_in'), findsNothing);
    expect(_chip('late'), findsOneWidget);
    expect(_chip('missing_punch'), findsOneWidget);
  });

  testWidgets('no chips on a day with nothing to show', (tester) async {
    await _pump(tester, const []);
    expect(_chip('late'), findsNothing);
    expect(_chip('missing_punch'), findsNothing);
  });

  testWidgets('a drill-down flag with no chip still shows its "Showing" tag', (tester) async {
    tester.view.physicalSize = const Size(800, 3000);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.reset);
    final api = FakeApiClient(lists: {'/employees': _employees, '/regularizations': const []}, objects: {});
    await tester.pumpWidget(
      ProviderScope(
        overrides: [attendanceRepositoryProvider.overrideWithValue(_Repo(all)), apiClientProvider.overrideWithValue(api), fakeAuth(const [attendancePunchOnBehalf])],
        child: const MaterialApp(home: TeamAttendanceScreen(flag: 'overtime')),
      ),
    );
    await tester.pumpAndSettle();
    expect(find.textContaining('Showing: Overtime'), findsOneWidget);
  });
}
