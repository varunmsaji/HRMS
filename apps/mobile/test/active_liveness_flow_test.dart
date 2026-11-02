import 'dart:async';
import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:hrms_mobile/core/api/api_error.dart';
import 'package:hrms_mobile/core/api/envelope.dart';
import 'package:hrms_mobile/features/attendance/data/attendance_repository.dart';
import 'package:hrms_mobile/features/attendance/domain/active_liveness.dart';
import 'package:hrms_mobile/features/attendance/domain/face_liveness_capture.dart';
import 'package:hrms_mobile/features/attendance/domain/outside_shift_window.dart';
import 'package:hrms_mobile/features/attendance/domain/punch_warning.dart';
import 'package:hrms_mobile/features/attendance/domain/punch_location.dart';
import 'package:hrms_mobile/features/attendance/presentation/active_liveness_panel.dart';
import 'package:hrms_mobile/features/attendance/presentation/punch_location_flow.dart';
import 'package:hrms_mobile/features/attendance/state/active_liveness_config.dart';
import 'package:hrms_mobile/features/attendance/state/punch_controller.dart';

class _Ui implements PunchUi {
  _Ui(this.outcome);
  final FaceCaptureOutcome Function() outcome;
  @override
  bool active = true;
  final messages = <String>[];
  final shiftWindows = <OutsideShiftWindow>[];
  final geofenceCodes = <String>[];
  var punched = 0;
  var captures = 0;

  @override
  Future<PunchLocationPlan> planLocation() async => const PunchLocationPlan.skip();
  @override
  Future<PunchLocationPlan> captureLocation(GeofencePolicyMe policy) async => const PunchLocationPlan.skip();
  @override
  Future<bool> showLocationProblem(LocationFailure failure, LocationCapture capture) async => false;
  @override
  Future<bool> showGeofenceRejected(String code, String message) async {
    geofenceCodes.add(code);
    return false;
  }
  @override
  Future<void> showOutsideShiftWindow(OutsideShiftWindow window) async => shiftWindows.add(window);
  @override
  Future<void> showPunchWarning(PunchWarning warning) async {}
  @override
  Future<FaceCaptureOutcome> captureFace(FaceLivenessSession session) async {
    captures++;
    return outcome();
  }

  @override
  void message(String text) => messages.add(text);
  @override
  void onPunched() => punched++;
  @override
  void onFaceNotEnrolled() {}
}

class _Repo implements AttendanceRepository {
  final submitted = <String>[]; // idempotency keys of face punch requests
  var sessions = 0;
  Object? error;
  Completer<void>? sessionGate;

  @override
  Future<GeofencePolicyMe> getMyGeofencePolicy() async => GeofencePolicyMe.disabled;

  @override
  Future<FaceLivenessSession> startFaceLivenessSession(String direction) async {
    await sessionGate?.future;
    sessions++;
    return FaceLivenessSession(sessionId: 's$sessions', direction: direction, expiresAt: DateTime.now().add(const Duration(minutes: 2)), framesRequired: 3);
  }

  @override
  Future<FacePunchResult> facePunchMe({
    required String direction,
    required String livenessSessionId,
    required List<List<int>> frames,
    required String idempotencyKey,
    PunchLocation? location,
    LocationFailure? locationError,
  }) async {
    submitted.add(idempotencyKey);
    if (error != null) throw error!;
    return FacePunchResult(punchId: 'p', direction: direction, punchTime: '2026-10-31T09:00:00Z', similarity: 0.97);
  }

  @override
  dynamic noSuchMethod(Invocation invocation) => super.noSuchMethod(invocation);
}

List<Uint8List> _frames() => [Uint8List.fromList([1]), Uint8List.fromList([2]), Uint8List.fromList([3])];

({ProviderContainer c, _Repo repo, PunchController ctl}) _setup({required bool enabled}) {
  final repo = _Repo();
  final c = ProviderContainer(overrides: [
    attendanceRepositoryProvider.overrideWithValue(repo),
    activeLivenessConfigProvider.overrideWithValue(ActiveLivenessConfig(enabled: enabled)),
  ]);
  c.listen(punchControllerProvider, (_, __) {});
  addTearDown(c.dispose);
  return (c: c, repo: repo, ctl: c.read(punchControllerProvider.notifier));
}

void main() {
  group('attendance integration: liveness gate in the punch flow', () {
    test('liveness passed -> existing verification request is sent', () async {
      final s = _setup(enabled: true);
      final ui = _Ui(() => FaceCaptureFrames(_frames(), activeLivenessPassed: true));
      await s.ctl.punchFace('IN', ui);
      expect(s.repo.submitted, hasLength(1));
      expect(ui.punched, 1);
    });

    test('liveness incomplete -> NO attendance request is sent', () async {
      final s = _setup(enabled: true);
      final ui = _Ui(() => FaceCaptureFrames(_frames())); // frames without a completed challenge
      await s.ctl.punchFace('IN', ui);
      expect(s.repo.submitted, isEmpty);
      expect(ui.punched, 0);
      expect(ui.messages, ['Face verification could not be completed. Please try again.']);
      expect(s.c.read(punchControllerProvider).facePhase, FacePhase.idle);
    });

    test('flag off -> behaviour is exactly as before (frames alone are enough)', () async {
      final s = _setup(enabled: false);
      final ui = _Ui(() => FaceCaptureFrames(_frames()));
      await s.ctl.punchFace('IN', ui);
      expect(s.repo.submitted, hasLength(1));
    });

    test('cancelled / failed capture sends nothing', () async {
      final s = _setup(enabled: true);
      for (final outcome in <FaceCaptureOutcome>[
        const FaceCaptureCancelled(),
        const FaceCaptureFailed('Liveness verification could not be completed. Please try again later.'),
        const FaceCaptureExpired(),
      ]) {
        await s.ctl.punchFace('IN', _Ui(() => outcome));
      }
      expect(s.repo.submitted, isEmpty);
    });

    test('duplicate taps while a punch is in flight start only one capture', () async {
      final s = _setup(enabled: true);
      s.repo.sessionGate = Completer<void>();
      final ui = _Ui(() => FaceCaptureFrames(_frames(), activeLivenessPassed: true));
      final first = s.ctl.punchFace('IN', ui);
      await Future<void>.delayed(Duration.zero);
      await s.ctl.punchFace('IN', ui);
      await s.ctl.punchFace('OUT', ui);
      s.repo.sessionGate!.complete();
      await first;
      expect(ui.captures, 1);
      expect(s.repo.submitted, hasLength(1));
    });

    test('network failure after liveness does not claim success and keeps the idempotency key', () async {
      final s = _setup(enabled: true);
      s.repo.error = ApiError(status: 0, code: 'NETWORK_ERROR', message: 'offline');
      final ui = _Ui(() => FaceCaptureFrames(_frames(), activeLivenessPassed: true));
      await s.ctl.punchFace('IN', ui);
      expect(ui.punched, 0);
      expect(ui.messages.single, contains('may have been recorded'));
      s.repo.error = null;
      await s.ctl.punchFace('IN', _Ui(() => FaceCaptureFrames(_frames(), activeLivenessPassed: true)));
      expect(s.repo.submitted, hasLength(2));
      expect(s.repo.submitted[1], s.repo.submitted[0]);
    });

    test('a UI that went away mid-capture (late callback) submits nothing', () async {
      final s = _setup(enabled: true);
      late _Ui ui;
      ui = _Ui(() {
        ui.active = false; // screen disposed while the capture was returning
        return FaceCaptureFrames(_frames(), activeLivenessPassed: true);
      });
      await s.ctl.punchFace('IN', ui);
      expect(s.repo.submitted, isEmpty);
    });

    test('a shift-window rejection after a passed capture records nothing and starts a fresh attempt later', () async {
      final s = _setup(enabled: true);
      s.repo.error = ApiError(
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
      final ui = _Ui(() => FaceCaptureFrames(_frames(), activeLivenessPassed: true));
      await s.ctl.punchFace('IN', ui);

      expect(ui.punched, 0);
      expect(ui.shiftWindows, hasLength(1));
      expect(ui.messages, isEmpty);
      expect(s.repo.submitted, hasLength(1));
      expect(s.repo.sessions, 1);

      s.repo.error = null;
      await s.ctl.punchFace('IN', _Ui(() => FaceCaptureFrames(_frames(), activeLivenessPassed: true)));
      expect(s.repo.sessions, 2);
      expect(s.repo.submitted, hasLength(2));
      expect(s.repo.submitted[1], isNot(s.repo.submitted[0]));
    });

    test('a geofence rejection after a passed capture records nothing', () async {
      final s = _setup(enabled: true);
      s.repo.error = ApiError(status: 422, code: 'PUNCH_OUTSIDE_GEOFENCE', message: 'You are outside the workplace.');
      final ui = _Ui(() => FaceCaptureFrames(_frames(), activeLivenessPassed: true));
      await s.ctl.punchFace('IN', ui);
      expect(ui.punched, 0);
      expect(ui.geofenceCodes, ['PUNCH_OUTSIDE_GEOFENCE']);
      expect(ui.messages, isEmpty);
      expect(s.repo.submitted, hasLength(1));
    });

    test('a failed face match after a passed capture records nothing', () async {
      final s = _setup(enabled: true);
      s.repo.error = ApiError(status: 422, code: 'FACE_NOT_MATCHED', message: 'Face did not match.');
      final ui = _Ui(() => FaceCaptureFrames(_frames(), activeLivenessPassed: true));
      await s.ctl.punchFace('IN', ui);
      expect(ui.punched, 0);
      expect(ui.messages, ['Face did not match.']);
      expect(s.repo.submitted, hasLength(1));
    });

    test('rollout default: active liveness is OFF unless explicitly enabled', () {
      final c = ProviderContainer();
      addTearDown(c.dispose);
      expect(c.read(activeLivenessConfigProvider).enabled, isFalse);
    });
  });

  group('ActiveLivenessPanel', () {
    Future<void> pump(
      WidgetTester tester, {
      LivenessState state = LivenessState.challengeActive,
      LivenessHint hint = LivenessHint.doChallenge,
      LivenessChallenge? challenge = LivenessChallenge.blinkTwice,
      int index = 0,
      int count = 2,
      bool exhausted = false,
      VoidCallback? onRetry,
      VoidCallback? onClose,
      double textScale = 1,
      Size size = const Size(390, 800),
    }) async {
      tester.view.physicalSize = size;
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.reset);
      await tester.pumpWidget(MaterialApp(
        home: MediaQuery(
          data: MediaQueryData(size: size, textScaler: TextScaler.linear(textScale)),
          child: Scaffold(
            body: SingleChildScrollView(
              child: ActiveLivenessPanel(
                state: state,
                hint: hint,
                challenge: challenge,
                challengeIndex: index,
                challengeCount: count,
                attemptsExhausted: exhausted,
                onRetry: onRetry ?? () {},
                onClose: onClose ?? () {},
              ),
            ),
          ),
        ),
      ));
    }

    testWidgets('waiting for a face', (tester) async {
      await pump(tester, state: LivenessState.waitingForFace, hint: LivenessHint.none, challenge: null);
      expect(find.text('Look at the camera and hold still.'), findsOneWidget);
    });

    testWidgets('shows the instruction and progress for the current challenge', (tester) async {
      await pump(tester, index: 1, challenge: LivenessChallenge.turnLeft);
      expect(find.text('Turn your head left'), findsOneWidget);
      expect(find.text('Step 2 of 2'), findsOneWidget);
      expect(find.byIcon(Icons.check_circle), findsOneWidget);
      expect(find.byIcon(Icons.circle_outlined), findsOneWidget);
    });

    testWidgets('no face and multiple faces use the specified wording', (tester) async {
      await pump(tester, state: LivenessState.noFaceDetected, challenge: null);
      expect(find.text('Position your face inside the camera frame.'), findsOneWidget);
      await pump(tester, state: LivenessState.multipleFacesDetected, challenge: null);
      expect(find.text('Only one person should be visible.'), findsOneWidget);
    });

    testWidgets('timeout explains itself and offers manual retry and cancel', (tester) async {
      var retried = 0, closed = 0;
      await pump(tester, state: LivenessState.challengeTimeout, challenge: null, onRetry: () => retried++, onClose: () => closed++);
      expect(find.text("We couldn't verify the movement. Please try again."), findsOneWidget);
      await tester.tap(find.text('Try again'));
      await tester.tap(find.text('Cancel'));
      expect((retried, closed), (1, 1));
    });

    testWidgets('attempts exhausted: no retry, only Close', (tester) async {
      await pump(tester, state: LivenessState.challengeTimeout, challenge: null, exhausted: true);
      expect(find.text('Liveness verification could not be completed. Please try again later.'), findsOneWidget);
      expect(find.text('Try again'), findsNothing);
      expect(find.text('Close'), findsOneWidget);
    });

    testWidgets('camera failure wording', (tester) async {
      await pump(tester, state: LivenessState.cameraError, challenge: null);
      expect(find.text('Camera could not be started. Please try again.'), findsOneWidget);
    });

    testWidgets('large text on a small screen does not overflow', (tester) async {
      await pump(tester, state: LivenessState.challengeTimeout, challenge: null, textScale: 2.5, size: const Size(320, 480));
      expect(tester.takeException(), isNull);
      await pump(tester, textScale: 2.5, size: const Size(320, 480));
      expect(tester.takeException(), isNull);
    });

    testWidgets('no technical wording ever reaches the user', (tester) async {
      for (final state in LivenessState.values) {
        for (final hint in LivenessHint.values) {
          final text = livenessMessage(state, hint, challenge: LivenessChallenge.blinkTwice);
          expect(text.toLowerCase(), isNot(anyOf(contains('threshold'), contains('landmark'), contains('ear '), contains('confidence'))));
        }
      }
    });
  });
}
