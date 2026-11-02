import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:hrms_mobile/core/auth/permissions.dart';
import 'package:hrms_mobile/core/theme/app_theme.dart';
import 'package:hrms_mobile/features/attendance/data/attendance_repository.dart';
import 'package:hrms_mobile/features/attendance/domain/punch_location.dart';
import 'package:hrms_mobile/features/attendance/presentation/attendance_self_screen.dart';

import 'support/fake_auth.dart';
import 'support/test_themes.dart';

class _Repo implements AttendanceRepository {
  List<Punch> punches = [];
  Completer<void>? faceGate;
  var punchReads = 0;
  final punched = <String>[];

  @override
  Future<FaceEnrollmentStatus> getMyFaceEnrollment() async {
    await faceGate?.future;
    return FaceEnrollmentStatus();
  }

  @override
  Future<GeofencePolicyMe> getMyGeofencePolicy() async => GeofencePolicyMe.disabled;

  @override
  Future<List<AttendanceDay>> listAttendanceDays({String? employeeId, required String dateFrom, required String dateTo, String? attendanceStatus}) async => [];

  @override
  Future<List<Punch>> listPunches({required String employeeId, required String dateFrom, required String dateTo}) async {
    punchReads++;
    return punches;
  }

  @override
  Future<void> punchMe({required String direction, String? reference, String? idempotencyKey, PunchLocation? location, LocationFailure? locationError}) async {
    punched.add(direction);
  }

  @override
  dynamic noSuchMethod(Invocation invocation) => super.noSuchMethod(invocation);
}

Future<void> _pump(WidgetTester tester, _Repo repo, {List<String> permissions = const [attendancePunch, attendanceView]}) async {
  await tester.pumpWidget(ProviderScope(
    overrides: [fakeAuth(permissions, employeeId: 'e-1'), attendanceRepositoryProvider.overrideWithValue(repo)],
    child: MaterialApp(theme: AppTheme.employee, home: const AttendanceSelfScreen()),
  ));
  await tester.pumpAndSettle();
}

void main() {
  setUpAll(primeThemes);

  testWidgets('today status sits above the month, and the punch bar is pinned below the list', (tester) async {
    await _pump(tester, _Repo());
    expect(find.text('No attendance recorded yet today.'), findsOneWidget);
    final panelTop = tester.getTopLeft(find.text('No attendance recorded yet today.')).dy;
    final monthTop = tester.getTopLeft(find.text('This month')).dy;
    final barTop = tester.getTopLeft(find.text('Punch in')).dy;
    expect(panelTop, lessThan(monthTop));
    expect(barTop, greaterThan(monthTop));
  });

  testWidgets('after an IN the likely action is Punch out, with Punch in still reachable', (tester) async {
    final repo = _Repo()..punches = [Punch.fromJson({'id': 'p', 'employee_id': 'e-1', 'punch_time': DateTime.now().toUtc().toIso8601String(), 'direction': 'IN', 'source': 'MOBILE'})];
    await _pump(tester, repo);
    expect(find.text('Punch in instead'), findsOneWidget);
    await tester.tap(find.text('Punch in instead'));
    await tester.pumpAndSettle();
    expect(repo.punched, ['IN']);
  });

  testWidgets('the bar waits for the face status so a plain punch is never offered and then refused', (tester) async {
    final repo = _Repo()..faceGate = Completer<void>();
    await _pump(tester, repo);
    expect(find.text('Checking your punch options…'), findsOneWidget);
    await tester.tap(find.text('Punch in'), warnIfMissed: false);
    await tester.pump();
    expect(repo.punched, isEmpty);
    repo.faceGate!.complete();
    await tester.pumpAndSettle();
    expect(find.text('Checking your punch options…'), findsNothing);
    await tester.tap(find.text('Punch in'));
    await tester.pumpAndSettle();
    expect(repo.punched, ['IN']);
  });

  testWidgets('a confirmed punch re-reads the punch state (the panel follows the server)', (tester) async {
    final repo = _Repo();
    await _pump(tester, repo);
    final before = repo.punchReads;
    await tester.tap(find.text('Punch in'));
    await tester.pumpAndSettle();
    expect(find.text('Punched in.'), findsOneWidget);
    expect(repo.punchReads, greaterThan(before));
  });

  testWidgets('the More icon is gone on the employee surface', (tester) async {
    await _pump(tester, _Repo());
    expect(find.byTooltip('Settings & more'), findsNothing);
  });

  testWidgets('...and stays for an administrator', (tester) async {
    await _pump(tester, _Repo(), permissions: const [dashboardCompanyView, attendancePunch, attendanceView]);
    expect(find.byTooltip('Settings & more'), findsOneWidget);
  });

  testWidgets('at 320 px and 2x text the punch labels are not clipped (the buttons grow)', (tester) async {
    tester.view.physicalSize = const Size(320, 640);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.reset);
    await tester.pumpWidget(ProviderScope(
      overrides: [fakeAuth(const [attendancePunch, attendanceView], employeeId: 'e-1'), attendanceRepositoryProvider.overrideWithValue(_Repo())],
      child: MaterialApp(
        theme: AppTheme.employee,
        builder: (context, child) => MediaQuery(data: MediaQuery.of(context).copyWith(textScaler: const TextScaler.linear(2.0)), child: child!),
        home: const AttendanceSelfScreen(),
      ),
    ));
    await tester.pumpAndSettle();
    expect(tester.takeException(), isNull);
    final label = tester.getSize(find.text('Punch in'));
    final button = tester.getSize(find.ancestor(of: find.text('Punch in'), matching: find.byWidgetPredicate((w) => w is FilledButton)).first);
    expect(button.height, greaterThanOrEqualTo(label.height + 16), reason: 'the label fits inside the button');
  });
}
