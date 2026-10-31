import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:hrms_mobile/core/theme/app_theme.dart';
import 'package:hrms_mobile/features/attendance/data/attendance_repository.dart';
import 'package:hrms_mobile/features/attendance/data/location_provider.dart';
import 'package:hrms_mobile/features/attendance/domain/punch_location.dart';
import 'package:hrms_mobile/features/attendance/presentation/attendance_self_screen.dart';
import 'package:hrms_mobile/features/attendance/presentation/punch_location_flow.dart';

import 'location_capture_test.dart' show FakeGateway;
import 'support/fake_auth.dart';
import 'support/test_themes.dart';

/// T1-10: every location failure through the real Attendance screen, in the employee dialog chrome.
class _Repo implements AttendanceRepository {
  final punches = <({PunchLocation? location, LocationFailure? error})>[];

  @override
  Future<GeofencePolicyMe> getMyGeofencePolicy() async => const GeofencePolicyMe(mode: 'REQUIRED', maxAccuracyM: 50, maxAgeSeconds: 30);

  @override
  Future<FaceEnrollmentStatus> getMyFaceEnrollment() async => FaceEnrollmentStatus();

  @override
  Future<List<AttendanceDay>> listAttendanceDays({String? employeeId, required String dateFrom, required String dateTo, String? attendanceStatus}) async => [];

  @override
  Future<List<Punch>> listPunches({required String employeeId, required String dateFrom, required String dateTo}) async => [];

  @override
  Future<void> punchMe({required String direction, String? reference, String? idempotencyKey, PunchLocation? location, LocationFailure? locationError}) async {
    punches.add((location: location, error: locationError));
  }

  @override
  dynamic noSuchMethod(Invocation invocation) => super.noSuchMethod(invocation);
}

GpsFix _good() => GpsFix(latitude: 9.9, longitude: 76.2, accuracyM: 8, timestamp: DateTime.now().toUtc().subtract(const Duration(seconds: 2)));

Future<void> _pump(WidgetTester tester, _Repo repo, FakeGateway gateway, {Size size = const Size(390, 844), double scale = 1.0}) async {
  tester.view.physicalSize = size;
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
  await tester.pumpWidget(ProviderScope(
    overrides: [
      fakeAuth(['ATTENDANCE.PUNCH', 'ATTENDANCE.VIEW'], employeeId: 'e-1'),
      attendanceRepositoryProvider.overrideWithValue(repo),
      locationCaptureProvider.overrideWithValue(LocationCapture(gateway)),
    ],
    child: MaterialApp(
      theme: AppTheme.employee,
      builder: (context, child) => MediaQuery(data: MediaQuery.of(context).copyWith(textScaler: TextScaler.linear(scale)), child: child!),
      home: const AttendanceSelfScreen(),
    ),
  ));
  await tester.pumpAndSettle();
}

Future<void> _settle(WidgetTester tester) async {
  // Not pumpAndSettle: the busy spinner on the punch button animates for as long as a dialog is up.
  for (var i = 0; i < 8; i++) {
    await tester.pump(const Duration(seconds: 1));
  }
}

Future<void> _punchIn(WidgetTester tester) async {
  await tester.tap(find.text('Punch in'));
  await _settle(tester);
}

void main() {
  setUpAll(primeThemes);

  testWidgets('permission denied at the prompt: dialog explains, Try again asks again and then punches', (tester) async {
    final gateway = FakeGateway(perm: GatewayPermission.denied, afterRequest: GatewayPermission.denied, fix: _good());
    final repo = _Repo();
    await _pump(tester, repo, gateway);
    await _punchIn(tester);
    expect(find.text('Location needed'), findsOneWidget);
    expect(repo.punches, isEmpty);

    gateway.afterRequest = GatewayPermission.granted;
    await tester.tap(find.text('Try again'));
    await _settle(tester);
    expect(repo.punches, hasLength(1));
    expect(repo.punches.single.location, isNotNull);
    expect(find.text('Location needed'), findsNothing);
  });

  testWidgets('location services disabled: Open settings goes to the location settings; Cancel sends nothing', (tester) async {
    final gateway = FakeGateway(enabled: false);
    final repo = _Repo();
    await _pump(tester, repo, gateway);
    await _punchIn(tester);
    await tester.tap(find.text('Open settings'));
    await tester.pump();
    expect(gateway.locationSettingsOpened, 1);
    expect(gateway.appSettingsOpened, 0);
    await tester.tap(find.text('Cancel'));
    await _settle(tester);
    expect(repo.punches, isEmpty);
  });

  testWidgets('poor GPS accuracy then a good fix on retry', (tester) async {
    final gateway = FakeGateway(fix: GpsFix(latitude: 9.9, longitude: 76.2, accuracyM: 300, timestamp: DateTime.now().toUtc()));
    final repo = _Repo();
    await _pump(tester, repo, gateway);
    await _punchIn(tester);
    expect(find.textContaining('GPS signal is too weak'), findsOneWidget);
    gateway.fix = _good();
    await tester.tap(find.text('Try again'));
    await _settle(tester);
    expect(repo.punches.single.location!.accuracyM, 8);
  });

  testWidgets('location unavailable (platform error): reported, no settings button, retry works', (tester) async {
    final gateway = FakeGateway(fixError: Exception('boom'));
    final repo = _Repo();
    await _pump(tester, repo, gateway);
    await _punchIn(tester);
    expect(find.text('Location needed'), findsOneWidget);
    expect(find.text('Open settings'), findsNothing);
    gateway
      ..fixError = null
      ..fix = _good();
    await tester.tap(find.text('Try again'));
    await _settle(tester);
    expect(repo.punches, hasLength(1));
  });

  testWidgets('successful acquisition punches once with the fix and no dialog', (tester) async {
    final repo = _Repo();
    await _pump(tester, repo, FakeGateway(fix: _good()));
    await _punchIn(tester);
    expect(repo.punches, hasLength(1));
    expect(find.text('Location needed'), findsNothing);
  });

  testWidgets('cancelling leaves no punch and the buttons usable again', (tester) async {
    final gateway = FakeGateway(perm: GatewayPermission.deniedForever);
    final repo = _Repo();
    await _pump(tester, repo, gateway);
    await _punchIn(tester);
    await tester.tap(find.text('Cancel'));
    await _settle(tester);
    expect(repo.punches, isEmpty);
    expect(tester.widget<FilledButton>(find.ancestor(of: find.text('Punch in'), matching: find.byWidgetPredicate((w) => w is FilledButton)).first).onPressed, isNotNull);
  });

  testWidgets('background and foreground: the dialog survives, says to try again, and never retries or punches by itself', (tester) async {
    final gateway = FakeGateway(perm: GatewayPermission.deniedForever);
    final repo = _Repo();
    await _pump(tester, repo, gateway);
    await _punchIn(tester);
    final fixesBefore = gateway.fixCalls;
    expect(find.text('Back from Settings? Tap Try again.'), findsNothing);

    await tester.tap(find.text('Open settings'));
    await tester.pump();
    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.inactive);
    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.paused);
    await tester.pump();
    expect(find.text('Location needed'), findsOneWidget, reason: 'backgrounding does not dismiss it');
    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.inactive);
    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.resumed);
    await tester.pump();

    expect(find.text('Back from Settings? Tap Try again.'), findsOneWidget);
    expect(gateway.fixCalls, fixesBefore, reason: 'no automatic retry');
    expect(repo.punches, isEmpty);

    gateway
      ..perm = GatewayPermission.granted
      ..fix = _good();
    await tester.tap(find.text('Try again'));
    await _settle(tester);
    expect(repo.punches, hasLength(1));
  });

  testWidgets('backgrounding without visiting Settings adds no hint', (tester) async {
    final gateway = FakeGateway(perm: GatewayPermission.deniedForever);
    await _pump(tester, _Repo(), gateway);
    await _punchIn(tester);
    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.paused);
    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.resumed);
    await tester.pump();
    expect(find.text('Back from Settings? Tap Try again.'), findsNothing);
  });

  testWidgets('dialog chrome: rounded 16, at most 400 wide, 24 from the edges, no overflow at 320 px and 2x text', (tester) async {
    final gateway = FakeGateway(perm: GatewayPermission.deniedForever);
    await _pump(tester, _Repo(), gateway, size: const Size(320, 568), scale: 2.0);
    await _punchIn(tester);
    final dialog = tester.widget<AlertDialog>(find.byType(AlertDialog));
    expect((dialog.shape! as RoundedRectangleBorder).borderRadius, BorderRadius.circular(16));
    expect(dialog.insetPadding, const EdgeInsets.all(24));
    final rect = tester.getRect(find.descendant(of: find.byType(Dialog), matching: find.byType(Material)).first);
    expect(rect.width, lessThanOrEqualTo(400));
    expect(rect.left, greaterThanOrEqualTo(24));
    expect(rect.right, lessThanOrEqualTo(320 - 24));
    expect(tester.takeException(), isNull);
  });

  testWidgets('dialog chrome is also applied to the server geofence refusal', (tester) async {
    final host = GlobalKey();
    await tester.pumpWidget(MaterialApp(theme: AppTheme.employee, home: Scaffold(body: SizedBox(key: host))));
    unawaited(showGeofenceRejectedDialog(host.currentContext!, 'PUNCH_OUTSIDE_GEOFENCE', 'You appear to be outside an approved workplace.'));
    await tester.pumpAndSettle();
    final dialog = tester.widget<AlertDialog>(find.byType(AlertDialog));
    expect((dialog.shape! as RoundedRectangleBorder).borderRadius, BorderRadius.circular(16));
  });
}
