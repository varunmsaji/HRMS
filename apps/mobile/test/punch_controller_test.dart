import 'dart:async';

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:hrms_mobile/core/api/api_error.dart';
import 'package:hrms_mobile/core/api/envelope.dart';
import 'package:hrms_mobile/features/attendance/data/attendance_repository.dart';
import 'package:hrms_mobile/features/attendance/domain/face_liveness_capture.dart';
import 'package:hrms_mobile/features/attendance/domain/outside_shift_window.dart';
import 'package:hrms_mobile/features/attendance/domain/punch_warning.dart';
import 'package:hrms_mobile/features/attendance/domain/punch_location.dart';
import 'package:hrms_mobile/features/attendance/presentation/punch_location_flow.dart';
import 'package:hrms_mobile/features/attendance/state/punch_controller.dart';

/// T1-03: the controller on its own, as Attendance and Home will both use it.
class _Ui implements PunchUi {
  _Ui(this.name);
  final String name;
  @override
  bool active = true;
  final messages = <String>[];
  final shiftWindows = <OutsideShiftWindow>[];
  var punched = 0;
  var notEnrolled = 0;

  @override
  Future<PunchLocationPlan> planLocation() async => const PunchLocationPlan.skip();
  @override
  Future<PunchLocationPlan> captureLocation(GeofencePolicyMe policy) async => const PunchLocationPlan.skip();
  @override
  Future<bool> showLocationProblem(LocationFailure failure, LocationCapture capture) async => false;
  @override
  Future<bool> showGeofenceRejected(String code, String message) async => false;
  @override
  Future<void> showOutsideShiftWindow(OutsideShiftWindow window) async => shiftWindows.add(window);
  @override
  Future<void> showPunchWarning(PunchWarning warning) async {}
  @override
  Future<FaceCaptureOutcome> captureFace(FaceLivenessSession session) async => const FaceCaptureCancelled();
  @override
  void message(String text) => messages.add(text);
  @override
  void onPunched() => punched++;
  @override
  void onFaceNotEnrolled() => notEnrolled++;
}

class _Repo implements AttendanceRepository {
  final keys = <String?>[];
  final directions = <String>[];
  final answers = <Object?>[];
  Completer<void>? gate;
  final challenges = <String>[];
  Object? challengeError;

  @override
  Future<GeofencePolicyMe> getMyGeofencePolicy() async => GeofencePolicyMe.disabled;

  @override
  Future<void> punchMe({required String direction, String? reference, String? idempotencyKey, PunchLocation? location, LocationFailure? locationError}) async {
    directions.add(direction);
    keys.add(idempotencyKey);
    final g = gate;
    if (g != null) await g.future;
    final a = answers.isEmpty ? null : answers.removeAt(0);
    if (a != null) throw a;
  }

  @override
  Future<FaceLivenessSession> startFaceLivenessSession(String direction) async {
    challenges.add(direction);
    if (challengeError != null) throw challengeError!;
    throw StateError('not reached');
  }

  @override
  dynamic noSuchMethod(Invocation invocation) => super.noSuchMethod(invocation);
}

ApiError outsideShiftWindowError() => ApiError(
      status: 422,
      code: 'OUTSIDE_SHIFT_WINDOW',
      message: 'It is too early to punch in for your shift.',
      details: [
        ErrorDetail(field: 'punch_time', code: 'OUTSIDE_SHIFT_WINDOW', message: 'early', context: {
          'shift_start': '2026-10-30T09:30:00+00:00',
          'shift_end': '2026-10-30T18:30:00+00:00',
          'grace_in_minutes': 10,
          'grace_out_minutes': 15,
          'early_in_allowance_minutes': 60,
          'earliest_punch_in': '2026-10-30T08:30:00+00:00',
        }),
      ],
    );

ApiError _offline() => ApiError(status: 0, code: 'NETWORK_ERROR', message: 'offline');

({ProviderContainer container, ProviderSubscription<PunchState> keep, _Repo repo, PunchController ctl}) _setup() {
  final repo = _Repo();
  final container = ProviderContainer(overrides: [attendanceRepositoryProvider.overrideWithValue(repo)]);
  final keep = container.listen(punchControllerProvider, (_, __) {});
  addTearDown(container.dispose);
  return (container: container, keep: keep, repo: repo, ctl: container.read(punchControllerProvider.notifier));
}

void main() {
  test('Home and Attendance share one in-flight guard: a second screen cannot start a duplicate punch', () async {
    final s = _setup();
    final attendance = _Ui('attendance'), home = _Ui('home');
    s.repo.gate = Completer<void>();
    final first = s.ctl.punchPlain('IN', attendance);
    await Future<void>.delayed(Duration.zero);
    expect(s.container.read(punchControllerProvider).plainBusy, isTrue);

    await s.ctl.punchPlain('IN', home); // returns immediately: ignored
    await s.ctl.punchPlain('OUT', home);
    expect(s.repo.directions, ['IN']);

    s.repo.gate!.complete();
    await first;
    expect(s.container.read(punchControllerProvider).plainBusy, isFalse);
    expect(attendance.messages, ['Punched in.']);
    expect(attendance.punched, 1);
    expect(home.messages, isEmpty);
  });

  test('an unknown outcome started on one screen is retried safely from the other (same key)', () async {
    final s = _setup();
    final a = _Ui('attendance'), h = _Ui('home');
    s.repo.answers.addAll([_offline(), null]);
    await s.ctl.punchPlain('IN', a);
    await s.ctl.punchPlain('IN', h);
    expect(s.repo.keys[1], s.repo.keys[0]);
    expect(h.messages, ['Punched in.']);
  });

  test('the pending key dies with the controller: sign-out then sign-in never replays an old punch', () async {
    final s = _setup();
    s.repo.answers.add(_offline());
    await s.ctl.punchPlain('IN', _Ui('a'));
    s.keep.close(); // last screen gone (logout) -> autoDispose
    await Future<void>.delayed(Duration.zero);

    final keep2 = s.container.listen(punchControllerProvider, (_, __) {});
    addTearDown(keep2.close);
    await s.container.read(punchControllerProvider.notifier).punchPlain('IN', _Ui('b'));
    expect(s.repo.keys[1], isNot(s.repo.keys[0]));
  });

  test('the screen going away mid-request: no message, no refresh, no exception, state stays valid', () async {
    final s = _setup();
    final ui = _Ui('a');
    s.repo.gate = Completer<void>();
    final f = s.ctl.punchPlain('IN', ui);
    await Future<void>.delayed(Duration.zero);
    ui.active = false;
    s.repo.gate!.complete();
    await f;
    expect(ui.messages, isEmpty);
    expect(ui.punched, 0);
    expect(s.container.read(punchControllerProvider).plainBusy, isFalse);
  });

  test('the controller disposed mid-request completes without touching state', () async {
    final s = _setup();
    s.repo.gate = Completer<void>();
    final f = s.ctl.punchPlain('IN', _Ui('a'));
    await Future<void>.delayed(Duration.zero);
    s.keep.close();
    await Future<void>.delayed(Duration.zero);
    s.repo.gate!.complete();
    await f; // must not throw
  });

  test('FACE_VERIFICATION_REQUIRED switches the flag on and keeps no key', () async {
    final s = _setup();
    s.repo.answers.addAll([ApiError(status: 403, code: 'FACE_VERIFICATION_REQUIRED', message: 'Face verification is required to punch.'), null]);
    final ui = _Ui('a');
    await s.ctl.punchPlain('IN', ui);
    expect(s.container.read(punchControllerProvider).faceRequired, isTrue);
    expect(ui.messages, ['Face verification is required to punch.']);
    await s.ctl.punchPlain('IN', ui);
    expect(s.repo.keys[1], isNot(s.repo.keys[0]));
  });

  test('setFaceRequired follows the enrollment status', () {
    final s = _setup();
    s.ctl.setFaceRequired(true);
    expect(s.container.read(punchControllerProvider).faceRequired, isTrue);
    s.ctl.setFaceRequired(false);
    expect(s.container.read(punchControllerProvider).faceRequired, isFalse);
  });

  test('a refused challenge never reaches the camera, reports the reason, and re-reads enrollment when not enrolled', () async {
    final s = _setup();
    s.repo.challengeError = ApiError(status: 409, code: 'FACE_NOT_ENROLLED', message: 'No face is enrolled.');
    final ui = _Ui('a');
    await s.ctl.punchFace('OUT', ui);
    expect(s.repo.challenges, ['OUT']);
    expect(ui.messages, ['No face is enrolled.']);
    expect(ui.notEnrolled, 1);
    expect(s.container.read(punchControllerProvider).facePhase, FacePhase.idle);
  });

  test('plain and face have separate guards, exactly as before the refactor', () async {
    final s = _setup();
    s.repo.gate = Completer<void>();
    s.repo.challengeError = ApiError(status: 409, code: 'X', message: 'no');
    final plain = s.ctl.punchPlain('IN', _Ui('a'));
    await Future<void>.delayed(Duration.zero);
    await s.ctl.punchFace('IN', _Ui('b')); // not blocked by the plain guard
    expect(s.repo.challenges, ['IN']);
    s.repo.gate!.complete();
    await plain;
  });

  test('a punch-in refused as too early shows the shift-window warning, records nothing and is not retried', () async {
    final s = _setup();
    final ui = _Ui('a');
    s.repo.answers.add(outsideShiftWindowError());
    await s.ctl.punchPlain('IN', ui);

    expect(ui.shiftWindows, hasLength(1));
    expect(ui.shiftWindows.single.earlyInAllowanceMinutes, 60);
    expect(ui.messages, isEmpty); // no "Punched in." and no raw error text
    expect(ui.punched, 0);
    expect(s.repo.directions, ['IN']); // exactly one request: the dialog has no retry
    expect(s.container.read(punchControllerProvider).plainBusy, isFalse);

    // The refusal was a real answer, so a later punch starts a new attempt with a new key.
    await s.ctl.punchPlain('IN', ui);
    expect(s.repo.keys[1], isNot(s.repo.keys[0]));
  });

  test('another 422 is still reported as a plain message, not as a shift-window warning', () async {
    final s = _setup();
    final ui = _Ui('a');
    s.repo.answers.add(ApiError(status: 422, code: 'SOMETHING_ELSE', message: 'Nope.'));
    await s.ctl.punchPlain('IN', ui);
    expect(ui.shiftWindows, isEmpty);
    expect(ui.messages, ['Nope.']);
  });
}
