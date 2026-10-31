import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:hrms_mobile/core/api/api_error.dart';
import 'package:hrms_mobile/features/attendance/data/attendance_repository.dart';
import 'package:hrms_mobile/features/attendance/domain/punch_location.dart';
import 'package:hrms_mobile/features/attendance/presentation/attendance_self_screen.dart';

import 'support/fake_auth.dart';

/// T1-03 characterization: pins the behaviour of the plain self-punch exactly as it was BEFORE the
/// punch logic moved out of `AttendanceSelfScreen` into a shared controller. The same file runs,
/// unchanged, after the refactor. See docs/design/employee-mobile/PUNCH_BEHAVIOUR.md.
class _Repo implements AttendanceRepository {
  final punches = <({String direction, String? key})>[];
  final answers = <Object?>[]; // per punch: null = ok, else thrown (consumed in order)
  Completer<void>? gate; // when set, the next punch waits for it
  var dayLoads = 0;
  List<AttendanceDay> days = [];

  @override
  Future<FaceEnrollmentStatus> getMyFaceEnrollment() async => FaceEnrollmentStatus();

  @override
  Future<GeofencePolicyMe> getMyGeofencePolicy() async => GeofencePolicyMe.disabled;

  @override
  Future<List<AttendanceDay>> listAttendanceDays({String? employeeId, required String dateFrom, required String dateTo, String? attendanceStatus}) async {
    dayLoads++;
    return days;
  }

  @override
  Future<void> punchMe({required String direction, String? reference, String? idempotencyKey, PunchLocation? location, LocationFailure? locationError}) async {
    punches.add((direction: direction, key: idempotencyKey));
    final g = gate;
    if (g != null) await g.future;
    final answer = answers.isEmpty ? null : answers.removeAt(0);
    if (answer != null) throw answer;
  }

  @override
  dynamic noSuchMethod(Invocation invocation) => super.noSuchMethod(invocation);
}

ApiError _offline() => ApiError(status: 0, code: 'NETWORK_ERROR', message: 'offline');

Future<void> _pump(WidgetTester tester, _Repo repo) async {
  await tester.pumpWidget(ProviderScope(
    overrides: [fakeAuth(['ATTENDANCE.PUNCH'], employeeId: 'e-1'), attendanceRepositoryProvider.overrideWithValue(repo)],
    child: const MaterialApp(home: Scaffold(body: AttendanceSelfScreen())),
  ));
  await tester.pumpAndSettle();
}

Future<void> _tap(WidgetTester tester, String label) async {
  await tester.tap(find.text(label));
  await tester.pumpAndSettle();
}

void main() {
  testWidgets('duplicate taps while a punch is in flight send exactly one request', (tester) async {
    final repo = _Repo()..gate = Completer<void>();
    await _pump(tester, repo);
    await tester.tap(find.text('Punch in'));
    await tester.pump();
    await tester.tap(find.text('Punch in'), warnIfMissed: false);
    await tester.tap(find.text('Punch in'), warnIfMissed: false);
    await tester.pump();
    expect(repo.punches, hasLength(1));
    repo.gate!.complete();
    await tester.pumpAndSettle();
    expect(repo.punches, hasLength(1));
  });

  testWidgets('a punch in the other direction while one is in flight is ignored (single lock)', (tester) async {
    final repo = _Repo()..gate = Completer<void>();
    await _pump(tester, repo);
    await tester.tap(find.text('Punch in'));
    await tester.pump();
    await tester.tap(find.text('Punch out'), warnIfMissed: false);
    await tester.pump();
    expect(repo.punches.map((p) => p.direction), ['IN']);
    repo.gate!.complete();
    await tester.pumpAndSettle();
    // and once settled, both are usable again
    repo.gate = null;
    await _tap(tester, 'Punch out');
    expect(repo.punches.map((p) => p.direction), ['IN', 'OUT']);
  });

  testWidgets('network failure: same direction reuses the key; a real answer clears it; the next punch is new', (tester) async {
    final repo = _Repo()..answers.addAll([_offline(), null]);
    await _pump(tester, repo);
    await _tap(tester, 'Punch in');
    await tester.pump(const Duration(seconds: 5));
    await _tap(tester, 'Punch in'); // retry, succeeds
    await _tap(tester, 'Punch in'); // a genuinely new punch
    expect(repo.punches, hasLength(3));
    expect(repo.punches[1].key, repo.punches[0].key);
    expect(repo.punches[2].key, isNot(repo.punches[0].key));
  });

  testWidgets('network failure then the OTHER direction: new key, and the first key is forgotten', (tester) async {
    final repo = _Repo()..answers.addAll([_offline(), null, null]);
    await _pump(tester, repo);
    await _tap(tester, 'Punch in'); // unknown outcome, key k1 kept
    await tester.pump(const Duration(seconds: 5));
    await _tap(tester, 'Punch out'); // different direction -> new key, success clears pending
    await _tap(tester, 'Punch in'); // k1 is gone: a fresh key
    expect(repo.punches.map((p) => p.direction), ['IN', 'OUT', 'IN']);
    expect(repo.punches[1].key, isNot(repo.punches[0].key));
    expect(repo.punches[2].key, isNot(repo.punches[0].key));
  });

  testWidgets('a second unknown outcome in the other direction replaces the kept key', (tester) async {
    final repo = _Repo()..answers.addAll([_offline(), _offline(), null]);
    await _pump(tester, repo);
    await _tap(tester, 'Punch in'); // pending (IN,k1)
    await tester.pump(const Duration(seconds: 5));
    await _tap(tester, 'Punch out'); // pending becomes (OUT,k2)
    await tester.pump(const Duration(seconds: 5));
    await _tap(tester, 'Punch out'); // reuses k2
    expect(repo.punches[2].key, repo.punches[1].key);
    expect(repo.punches[1].key, isNot(repo.punches[0].key));
  });

  testWidgets('a server error after a network failure is a real answer: the key is dropped', (tester) async {
    final repo = _Repo()..answers.addAll([_offline(), ApiError(status: 500, code: 'SERVER_ERROR', message: 'Server error.'), null]);
    await _pump(tester, repo);
    await _tap(tester, 'Punch in');
    await tester.pump(const Duration(seconds: 5));
    await _tap(tester, 'Punch in'); // reuses k1, answered 500 -> pending cleared
    expect(find.text('Server error.'), findsOneWidget);
    await tester.pump(const Duration(seconds: 5));
    await _tap(tester, 'Punch in');
    expect(repo.punches[1].key, repo.punches[0].key);
    expect(repo.punches[2].key, isNot(repo.punches[0].key));
  });

  testWidgets('session expiry (401) shows the server message, keeps no key, and does not crash', (tester) async {
    final repo = _Repo()..answers.add(ApiError(status: 401, code: 'UNAUTHORIZED', message: 'Your session has expired.'));
    await _pump(tester, repo);
    await _tap(tester, 'Punch in');
    expect(find.text('Your session has expired.'), findsOneWidget);
    await tester.pump(const Duration(seconds: 5));
    await _tap(tester, 'Punch in');
    expect(repo.punches[1].key, isNot(repo.punches[0].key));
    expect(tester.takeException(), isNull);
  });

  testWidgets('a non-API error shows the generic message and keeps no key', (tester) async {
    final repo = _Repo()..answers.addAll([StateError('boom'), null]);
    await _pump(tester, repo);
    await _tap(tester, 'Punch out');
    expect(find.text('Something went wrong. Please try again.'), findsOneWidget);
    await tester.pump(const Duration(seconds: 5));
    await _tap(tester, 'Punch out');
    expect(repo.punches[1].key, isNot(repo.punches[0].key));
  });

  testWidgets('server-confirmed: success says so and reloads the day list from the server', (tester) async {
    final repo = _Repo();
    await _pump(tester, repo);
    final before = repo.dayLoads;
    await _tap(tester, 'Punch in');
    expect(find.text('Punched in.'), findsOneWidget);
    expect(repo.dayLoads, before + 1);
    await tester.pump(const Duration(seconds: 5));
    await _tap(tester, 'Punch out');
    expect(find.text('Punched out.'), findsOneWidget);
  });

  testWidgets('a failed punch does not claim success and does not reload', (tester) async {
    final repo = _Repo()..answers.add(ApiError(status: 422, code: 'X', message: 'Nope.'));
    await _pump(tester, repo);
    final before = repo.dayLoads;
    await _tap(tester, 'Punch in');
    expect(find.text('Punched in.'), findsNothing);
    expect(find.text('Nope.'), findsOneWidget);
    expect(repo.dayLoads, before);
  });

  testWidgets('leaving the screen mid-request (logout/session loss) completes quietly', (tester) async {
    final repo = _Repo()..gate = Completer<void>();
    await _pump(tester, repo);
    await tester.tap(find.text('Punch in'));
    await tester.pump();
    await tester.pumpWidget(const MaterialApp(home: Scaffold(body: Text('login'))));
    repo.answers.add(ApiError(status: 401, code: 'UNAUTHORIZED', message: 'Your session has expired.'));
    repo.gate!.complete();
    await tester.pumpAndSettle();
    expect(tester.takeException(), isNull);
    expect(find.text('login'), findsOneWidget);
  });
}
