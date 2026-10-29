import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:hrms_mobile/core/api/api_error.dart';
import 'package:hrms_mobile/features/attendance/data/attendance_repository.dart';
import 'package:hrms_mobile/features/attendance/data/location_provider.dart';
import 'package:hrms_mobile/features/attendance/domain/punch_location.dart';
import 'package:hrms_mobile/features/attendance/presentation/attendance_self_screen.dart';
import 'package:hrms_mobile/features/attendance/presentation/punch_location_flow.dart';

import 'location_capture_test.dart' show FakeGateway;
import 'support/fake_auth.dart';

/// Records what the screen sends and lets a test script the server's answers.
class _Repo implements AttendanceRepository {
  _Repo({this.policy = const GeofencePolicyMe(mode: 'REQUIRED', maxAccuracyM: 50, maxAgeSeconds: 30)});

  GeofencePolicyMe policy;
  Object? policyError;
  final List<Object?> answers = []; // per punch: null = ok, else thrown
  final punches = <({String direction, String? key, PunchLocation? location, LocationFailure? error})>[];

  @override
  Future<GeofencePolicyMe> getMyGeofencePolicy() async {
    if (policyError != null) throw policyError!;
    return policy;
  }

  @override
  Future<FaceEnrollmentStatus> getMyFaceEnrollment() async => FaceEnrollmentStatus();

  @override
  Future<List<AttendanceDay>> listAttendanceDays({String? employeeId, required String dateFrom, required String dateTo, String? attendanceStatus}) async => [];

  @override
  Future<void> punchMe({
    required String direction,
    String? reference,
    String? idempotencyKey,
    PunchLocation? location,
    LocationFailure? locationError,
  }) async {
    punches.add((direction: direction, key: idempotencyKey, location: location, error: locationError));
    final answer = answers.isEmpty ? null : answers.removeAt(0);
    if (answer != null) throw answer;
  }

  @override
  dynamic noSuchMethod(Invocation invocation) => super.noSuchMethod(invocation);
}

GpsFix _goodFix() => GpsFix(
      latitude: 9.9312,
      longitude: 76.2673,
      accuracyM: 8,
      timestamp: DateTime.now().toUtc().subtract(const Duration(seconds: 2)),
    );

Future<void> _pump(WidgetTester tester, _Repo repo, FakeGateway gateway) async {
  await tester.pumpWidget(ProviderScope(
    overrides: [
      fakeAuth(['ATTENDANCE.PUNCH'], employeeId: 'e-1'),
      attendanceRepositoryProvider.overrideWithValue(repo),
      locationCaptureProvider.overrideWithValue(LocationCapture(gateway)),
    ],
    child: const MaterialApp(home: Scaffold(body: AttendanceSelfScreen())),
  ));
  await tester.pumpAndSettle();
}

Future<void> _tapPunchIn(WidgetTester tester) async {
  await tester.tap(find.text('Punch in'));
  await tester.pumpAndSettle();
}

ApiError _refusal(String outcome, String message) => ApiError(status: 422, code: 'PUNCH_$outcome', message: message);

void main() {
  testWidgets('geofencing off: no location is requested, captured or sent', (tester) async {
    final repo = _Repo(policy: GeofencePolicyMe.disabled);
    final gateway = FakeGateway(fix: _goodFix());
    await _pump(tester, repo, gateway);

    await _tapPunchIn(tester);

    expect(repo.punches.single.location, isNull);
    expect(repo.punches.single.error, isNull);
    expect((gateway.requestCalls, gateway.fixCalls), (0, 0));
  });

  testWidgets('policy lookup fails offline: the punch is still attempted, server stays the authority', (tester) async {
    final repo = _Repo()..policyError = ApiError(status: 0, code: 'NETWORK_ERROR', message: 'offline');
    final gateway = FakeGateway(fix: _goodFix());
    await _pump(tester, repo, gateway);

    await _tapPunchIn(tester);

    expect(repo.punches, hasLength(1));
    expect(repo.punches.single.location, isNull);
    expect(gateway.fixCalls, 0);
  });

  testWidgets('required + permission granted: a fresh fix is sent with the punch', (tester) async {
    final repo = _Repo();
    final gateway = FakeGateway(fix: _goodFix());
    await _pump(tester, repo, gateway);

    await _tapPunchIn(tester);

    final sent = repo.punches.single;
    expect(sent.direction, 'IN');
    expect(sent.location, isNotNull);
    expect(sent.location!.accuracyM, 8);
    expect(gateway.fixCalls, 1);
    expect(find.text('Punched in.'), findsOneWidget);
  });

  testWidgets('required + services off: explains how to fix it, sends nothing, cancel leaves no punch', (tester) async {
    final repo = _Repo();
    final gateway = FakeGateway(enabled: false);
    await _pump(tester, repo, gateway);

    await _tapPunchIn(tester);

    expect(find.text('Location needed'), findsOneWidget);
    expect(find.textContaining('Location services are turned off'), findsOneWidget);
    expect(find.text('Open settings'), findsOneWidget);
    await tester.tap(find.text('Open settings'));
    await tester.pump();
    expect(gateway.locationSettingsOpened, 1);

    await tester.tap(find.text('Cancel'));
    await tester.pumpAndSettle();
    expect(repo.punches, isEmpty);
    expect(find.text('Location needed'), findsNothing);
  });

  testWidgets('required + permanently denied: opens the app settings, not the prompt', (tester) async {
    final repo = _Repo();
    final gateway = FakeGateway(perm: GatewayPermission.deniedForever);
    await _pump(tester, repo, gateway);

    await _tapPunchIn(tester);
    await tester.tap(find.text('Open settings'));
    await tester.pump();

    expect(gateway.appSettingsOpened, 1);
    expect(gateway.requestCalls, 0);
    expect(repo.punches, isEmpty);
  });

  testWidgets('required + poor accuracy: tells how to improve GPS; Try again takes a new fix and then punches', (tester) async {
    final repo = _Repo();
    final gateway = FakeGateway(
      fix: GpsFix(latitude: 9.9, longitude: 76.2, accuracyM: 200, timestamp: DateTime.now().toUtc()),
    );
    await _pump(tester, repo, gateway);

    await _tapPunchIn(tester);
    expect(find.textContaining('GPS signal is too weak'), findsOneWidget);
    expect(repo.punches, isEmpty);

    gateway.fix = _goodFix();
    await tester.tap(find.text('Try again'));
    await tester.pumpAndSettle();

    expect(repo.punches, hasLength(1));
    expect(repo.punches.single.location!.accuracyM, 8);
    expect(gateway.fixCalls, 2, reason: 'a new fix per attempt, never a cached one');
  });

  testWidgets('required + GPS timeout is reported, not silently punched', (tester) async {
    final repo = _Repo();
    final gateway = FakeGateway(fixError: TimeoutException('gps'));
    await _pump(tester, repo, gateway);

    await _tapPunchIn(tester);

    expect(find.text('Location needed'), findsOneWidget);
    expect(find.textContaining('Could not get your location in time'), findsOneWidget);
    expect(repo.punches, isEmpty);
  });

  testWidgets('optional + capture failure: the punch goes ahead and the failure is reported', (tester) async {
    final repo = _Repo(policy: const GeofencePolicyMe(mode: 'OPTIONAL', maxAccuracyM: 50, maxAgeSeconds: 30));
    final gateway = FakeGateway(perm: GatewayPermission.denied, afterRequest: GatewayPermission.denied);
    await _pump(tester, repo, gateway);

    await _tapPunchIn(tester);

    expect(find.text('Location needed'), findsNothing);
    final sent = repo.punches.single;
    expect(sent.location, isNull);
    expect(sent.error, LocationFailure.permissionDenied);
  });

  testWidgets('server says outside the geofence: shows the server message, offers retry, never claims success', (tester) async {
    final repo = _Repo()..answers.add(_refusal('OUTSIDE_GEOFENCE', 'You appear to be outside an approved workplace.'));
    final gateway = FakeGateway(fix: _goodFix());
    await _pump(tester, repo, gateway);

    await _tapPunchIn(tester);

    expect(find.text('Punch not recorded'), findsOneWidget);
    expect(find.textContaining('outside an approved workplace'), findsOneWidget);
    expect(find.textContaining('ask HR to correct your attendance'), findsOneWidget);
    expect(find.text('Punched in.'), findsNothing);

    // Try again: a fresh fix, and now the server accepts.
    await tester.tap(find.text('Try again'));
    await tester.pumpAndSettle();
    expect(repo.punches, hasLength(2));
    expect(gateway.fixCalls, 2);
    expect(find.text('Punched in.'), findsOneWidget);
  });

  testWidgets('no workplace configured: only HR can fix it, so no retry is offered', (tester) async {
    final repo = _Repo()..answers.add(_refusal('NO_APPLICABLE_WORKPLACE', 'No approved workplace is configured for you.'));
    await _pump(tester, repo, FakeGateway(fix: _goodFix()));

    await _tapPunchIn(tester);

    expect(find.textContaining('No approved workplace'), findsOneWidget);
    expect(find.text('Try again'), findsNothing);
    await tester.tap(find.text('OK'));
    await tester.pumpAndSettle();
    expect(repo.punches, hasLength(1));
  });

  testWidgets('network failure keeps the idempotency key so the retry cannot double-punch', (tester) async {
    final repo = _Repo()..answers.add(ApiError(status: 0, code: 'NETWORK_ERROR', message: 'offline'));
    await _pump(tester, repo, FakeGateway(fix: _goodFix()));

    await _tapPunchIn(tester);
    expect(find.text('offline'), findsOneWidget);
    await tester.pump(const Duration(seconds: 5));
    await _tapPunchIn(tester);

    expect(repo.punches, hasLength(2));
    expect(repo.punches[0].key, isNotNull);
    expect(repo.punches[1].key, repo.punches[0].key);
  });

  testWidgets('a refused location is a real answer: the retry uses a new key', (tester) async {
    final repo = _Repo()..answers.add(_refusal('LOCATION_STALE', 'The location reading is too old.'));
    await _pump(tester, repo, FakeGateway(fix: _goodFix()));

    await _tapPunchIn(tester);
    await tester.tap(find.text('Try again'));
    await tester.pumpAndSettle();

    expect(repo.punches, hasLength(2));
    expect(repo.punches[1].key, isNot(repo.punches[0].key));
  });

  testWidgets('the buttons are disabled while the location capture is in flight, and a second tap cannot double-punch', (tester) async {
    final repo = _Repo();
    final gateway = _SlowGateway(_goodFix());
    await _pump(tester, repo, gateway);

    await tester.tap(find.text('Punch in'));
    await tester.pump();
    FilledButton punchIn() => tester.widget<FilledButton>(find.ancestor(
          of: find.text('Punch in'),
          matching: find.byWidgetPredicate((w) => w is FilledButton),
        ));
    expect(punchIn().onPressed, isNull);

    gateway.release();
    await tester.pumpAndSettle();
    expect(repo.punches, hasLength(1));
    expect(punchIn().onPressed, isNotNull);
  });

  testWidgets('the location dialogs do not overflow at 2x text on a narrow phone', (tester) async {
    tester.view.physicalSize = const Size(360, 640);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.reset);
    final capture = LocationCapture(FakeGateway());

    late BuildContext hostContext;
    await tester.pumpWidget(MaterialApp(
      builder: (context, child) => MediaQuery(
        data: MediaQuery.of(context).copyWith(textScaler: const TextScaler.linear(2.0)),
        child: child!,
      ),
      home: Builder(builder: (context) {
        hostContext = context;
        return const Scaffold(body: SizedBox());
      }),
    ));

    unawaited(showLocationProblemDialog(hostContext, LocationFailure.permissionDeniedForever, capture));
    await tester.pumpAndSettle();
    expect(find.text('Location needed'), findsOneWidget);
    expect(find.text('Open settings'), findsOneWidget);
    expect(find.text('Try again'), findsOneWidget);
    expect(tester.takeException(), isNull);
    await tester.tap(find.text('Cancel'));
    await tester.pumpAndSettle();

    unawaited(showGeofenceRejectedDialog(hostContext, 'PUNCH_OUTSIDE_GEOFENCE',
        'You appear to be outside an approved workplace, so this punch was not recorded.'));
    await tester.pumpAndSettle();
    expect(find.text('Punch not recorded'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });
}

/// A gateway whose fix stays pending until [release] — models a slow GPS acquisition.
class _SlowGateway extends FakeGateway {
  _SlowGateway(GpsFix fix) : super(fix: fix);
  final _gate = Completer<void>();

  void release() => _gate.complete();

  @override
  Future<GpsFix> currentFix({required Duration timeout}) async {
    fixCalls++;
    await _gate.future;
    return fix!;
  }
}
