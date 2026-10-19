import 'dart:async';
import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:hrms_mobile/core/api/api_error.dart';
import 'package:hrms_mobile/features/attendance/data/attendance_repository.dart';
import 'package:hrms_mobile/features/attendance/domain/face_liveness_capture.dart';
import 'package:hrms_mobile/features/attendance/presentation/face_punch_card.dart';

FaceEnrollmentStatus _enrolled() => FaceEnrollmentStatus(profileStatus: 'ENROLLED');

List<Uint8List> _frames() => [
      for (var i = 0; i < 3; i++) Uint8List.fromList([0xff, 0xd8, 0xff, 0xe0, i]),
    ];

class _Punch {
  _Punch(this.direction, this.sessionId, this.frames, this.key);
  final String direction;
  final String sessionId;
  final List<List<int>> frames;
  final String key;
}

class _FakeRepository implements AttendanceRepository {
  _FakeRepository(this.respond, {FaceEnrollmentStatus? status, this.challengeError}) : status = status ?? _enrolled();

  final Future<FacePunchResult> Function() respond;
  final FaceEnrollmentStatus status;
  final Object? challengeError;
  final challenges = <String>[];
  final punches = <_Punch>[];
  var _sessionSeq = 0;

  List<String> get keys => [for (final p in punches) p.key];

  @override
  Future<FaceEnrollmentStatus> getMyFaceEnrollment() async => status;

  @override
  Future<FaceLivenessSession> startFaceLivenessSession(String direction) async {
    challenges.add(direction);
    if (challengeError != null) throw challengeError!;
    return FaceLivenessSession(
      sessionId: 'session-${++_sessionSeq}',
      direction: direction,
      expiresAt: DateTime.now().add(const Duration(minutes: 2)),
      framesRequired: 3,
    );
  }

  @override
  Future<FacePunchResult> facePunchMe({
    required String direction,
    required String livenessSessionId,
    required List<List<int>> frames,
    required String idempotencyKey,
  }) {
    punches.add(_Punch(direction, livenessSessionId, frames, idempotencyKey));
    return respond();
  }

  @override
  dynamic noSuchMethod(Invocation invocation) => super.noSuchMethod(invocation);
}

FacePunchResult _result(String direction) => FacePunchResult(
      punchId: 'p-1',
      direction: direction,
      punchTime: '2026-10-01T03:30:00Z',
      similarity: 0.97,
      livenessScore: 0.95,
    );

/// A capture stand-in: records the challenge it was given, answers with [outcome].
class _FakeCapture {
  _FakeCapture([FaceCaptureOutcome Function()? outcome]) : outcome = outcome ?? (() => FaceCaptureFrames(_frames()));
  final FaceCaptureOutcome Function() outcome;
  final sessions = <FaceLivenessSession>[];

  Future<FaceCaptureOutcome> call(BuildContext context, FaceLivenessSession session) async {
    sessions.add(session);
    return outcome();
  }
}

Future<void> _pump(
  WidgetTester tester, {
  required _FakeRepository repository,
  _FakeCapture? capture,
  VoidCallback? onPunched,
}) {
  final fake = capture ?? _FakeCapture();
  return tester.pumpWidget(ProviderScope(
    overrides: [
      attendanceRepositoryProvider.overrideWithValue(repository),
      faceLivenessCaptureProvider.overrideWithValue(fake.call),
    ],
    child: MaterialApp(home: Scaffold(body: FacePunchCard(onPunched: onPunched))),
  )).then((_) => tester.pumpAndSettle());
}

Future<void> _pumpStatus(WidgetTester tester, FaceEnrollmentStatus status) =>
    _pump(tester, repository: _FakeRepository(() async => _result('IN'), status: status));

Future<void> _tap(WidgetTester tester, String label) async {
  await tester.tap(find.text(label));
  await tester.pumpAndSettle();
}

void main() {
  testWidgets('challenge -> capture -> punch with the challenge and its frames', (tester) async {
    final repository = _FakeRepository(() async => _result('IN'));
    final capture = _FakeCapture();
    var refreshed = 0;
    await _pump(tester, repository: repository, capture: capture, onPunched: () => refreshed++);

    await _tap(tester, 'Face punch in');

    expect(repository.challenges, ['IN']);
    expect(capture.sessions.single.sessionId, 'session-1');
    final punch = repository.punches.single;
    expect(punch.direction, 'IN');
    expect(punch.sessionId, 'session-1', reason: 'frames are bound to the challenge they were captured for');
    expect(punch.key, isNotEmpty);
    expect(find.text('Punched in · face verified (97% match)'), findsOneWidget);
    expect(refreshed, 1);
  });

  testWidgets('drops the face frames once the attempt is over', (tester) async {
    final repository = _FakeRepository(() async => _result('IN'));
    await _pump(tester, repository: repository);

    await _tap(tester, 'Face punch in');

    expect(repository.punches.single.frames, isEmpty);
  });

  testWidgets('a retry after an unknown outcome gets a new challenge but keeps the key', (tester) async {
    final outcomes = <Future<FacePunchResult> Function()>[
      () async => throw NetworkError.timeout(isWrite: true),
      () async => throw NetworkError(),
      () async => throw ApiError(status: 504, code: 'SERVICE_UNAVAILABLE', message: 'gateway'),
      () async => throw ApiError(status: 422, code: 'FACE_NOT_MATCHED', message: 'no match'),
      () async => _result('IN'),
    ];
    final repository = _FakeRepository(() => outcomes.removeAt(0)());
    await _pump(tester, repository: repository);

    for (var i = 0; i < 5; i++) {
      await _tap(tester, 'Face punch in');
    }

    final keys = repository.keys;
    final sessions = [for (final p in repository.punches) p.sessionId];
    expect(sessions.toSet().length, 5, reason: 'every attempt is bound to a fresh challenge');
    expect(keys[1], keys[0], reason: 'timeout -> retry resends the same key');
    expect(keys[2], keys[1], reason: 'network failure -> retry resends the same key');
    expect(keys[3], keys[2], reason: 'proxy 504 without the API envelope -> outcome unknown');
    expect(keys[4], isNot(keys[3]), reason: 'a real API answer (422) ends the unconfirmed attempt');
  });

  testWidgets('a timeout explains that retrying is safe', (tester) async {
    final repository = _FakeRepository(() async => throw NetworkError.timeout(isWrite: true));
    await _pump(tester, repository: repository);

    await _tap(tester, 'Face punch in');

    expect(find.textContaining('will not be recorded twice'), findsOneWidget);
  });

  testWidgets('switching direction after an unconfirmed punch uses a new key', (tester) async {
    final repository = _FakeRepository(() async => throw NetworkError.timeout(isWrite: true));
    await _pump(tester, repository: repository);

    await _tap(tester, 'Face punch in');
    await _tap(tester, 'Face punch out');

    expect(repository.keys[1], isNot(repository.keys[0]));
  });

  testWidgets('a liveness server error is a real answer, not an unknown outcome', (tester) async {
    final outcomes = <Future<FacePunchResult> Function()>[
      () async => throw ApiError(status: 503, code: 'FACE_LIVENESS_TIMEOUT', message: 'Face check took too long'),
      () async => _result('IN'),
    ];
    final repository = _FakeRepository(() => outcomes.removeAt(0)());
    await _pump(tester, repository: repository);

    await _tap(tester, 'Face punch in');
    expect(find.text('Face check took too long'), findsOneWidget);
    await _tap(tester, 'Face punch in');

    expect(repository.keys[1], isNot(repository.keys[0]));
  });

  for (final (code, message) in [
    ('FACE_SPOOF_SUSPECTED', 'We could not confirm a live face.'),
    ('FACE_LIVENESS_INCONCLUSIVE', 'We could not check your face clearly.'),
    ('FACE_MULTIPLE_FACES', 'More than one face was detected.'),
    ('FACE_LIVENESS_CHALLENGE_EXPIRED', 'This face check expired. Start the face punch again.'),
  ]) {
    testWidgets('$code shows the server reason and offers no override', (tester) async {
      final repository = _FakeRepository(() async => throw ApiError(status: 422, code: code, message: message));
      var refreshed = 0;
      await _pump(tester, repository: repository, onPunched: () => refreshed++);

      await _tap(tester, 'Face punch in');

      expect(find.text(message), findsOneWidget);
      expect(refreshed, 0);
      expect(find.textContaining(RegExp('anyway|override|skip', caseSensitive: false)), findsNothing);
      // Back to the two normal buttons; a new attempt starts from a new challenge.
      expect(tester.widget<FilledButton>(find.byWidgetPredicate((w) => w is FilledButton)).onPressed, isNotNull);
    });
  }

  testWidgets('cancelling the capture sends nothing', (tester) async {
    final repository = _FakeRepository(() async => _result('IN'));
    await _pump(tester, repository: repository, capture: _FakeCapture(() => const FaceCaptureCancelled()));

    await _tap(tester, 'Face punch out');

    expect(repository.punches, isEmpty);
    expect(find.byType(SnackBar), findsNothing);
  });

  testWidgets('explains how to fix a blocked camera', (tester) async {
    final repository = _FakeRepository(() async => _result('IN'));
    await _pump(tester, repository: repository, capture: _FakeCapture(() => const FaceCapturePermissionDenied()));

    await _tap(tester, 'Face punch in');

    expect(find.textContaining('Allow camera access'), findsOneWidget);
    expect(repository.punches, isEmpty);
  });

  testWidgets('an expired challenge during capture sends nothing', (tester) async {
    final repository = _FakeRepository(() async => _result('IN'));
    await _pump(tester, repository: repository, capture: _FakeCapture(() => const FaceCaptureExpired()));

    await _tap(tester, 'Face punch in');

    expect(find.text('That took too long. Please try again.'), findsOneWidget);
    expect(repository.punches, isEmpty);
  });

  testWidgets('camera failure or an unsupported device is reported, nothing sent', (tester) async {
    final repository = _FakeRepository(() async => _result('IN'));
    await _pump(
      tester,
      repository: repository,
      capture: _FakeCapture(() => const FaceCaptureFailed('Face attendance is not supported on this device.')),
    );

    await _tap(tester, 'Face punch in');

    expect(find.text('Face attendance is not supported on this device.'), findsOneWidget);
    expect(repository.punches, isEmpty);
  });

  testWidgets('a refused challenge never opens the camera', (tester) async {
    final repository = _FakeRepository(
      () async => _result('IN'),
      challengeError: ApiError(status: 503, code: 'FACE_LIVENESS_UNAVAILABLE', message: 'Face attendance is temporarily unavailable'),
    );
    final capture = _FakeCapture();
    await _pump(tester, repository: repository, capture: capture);

    await _tap(tester, 'Face punch in');

    expect(find.textContaining('temporarily unavailable'), findsOneWidget);
    expect(capture.sessions, isEmpty);
    expect(repository.punches, isEmpty);
  });

  testWidgets('disables both buttons and ignores taps while verifying', (tester) async {
    final pending = Completer<FacePunchResult>();
    final repository = _FakeRepository(() => pending.future);
    await _pump(tester, repository: repository);

    await tester.tap(find.text('Face punch out'));
    await tester.pump();
    await tester.pump();

    expect(find.text('Verifying your face…'), findsOneWidget);
    expect(tester.widget<FilledButton>(find.byWidgetPredicate((w) => w is FilledButton)).onPressed, isNull);
    expect(tester.widget<OutlinedButton>(find.byWidgetPredicate((w) => w is OutlinedButton)).onPressed, isNull);
    await tester.tap(find.text('Face punch out'), warnIfMissed: false);
    await tester.pump();
    expect(repository.challenges, ['OUT'], reason: 'no second attempt while one is in flight');

    pending.complete(_result('OUT'));
    await tester.pumpAndSettle();
    expect(find.text('Punched out · face verified (97% match)'), findsOneWidget);
    expect(repository.punches, hasLength(1));
  });

  testWidgets('offers set-up when HR has opened enrollment', (tester) async {
    await _pumpStatus(tester, FaceEnrollmentStatus(windowExpiresAt: DateTime.utc(2026, 10, 3, 2)));

    expect(find.text('Set up face attendance'), findsOneWidget);
    expect(find.text('Face punch in'), findsNothing);

    await tester.tap(find.text('Set up face attendance'));
    await tester.pumpAndSettle();
    expect(find.text('Register your face'), findsOneWidget);
    expect(tester.widget<FilledButton>(find.byWidgetPredicate((w) => w is FilledButton)).onPressed, isNull,
        reason: 'Start stays disabled until consent is ticked');
  });

  testWidgets('waits for HR approval after submitting', (tester) async {
    await _pumpStatus(tester, FaceEnrollmentStatus(profileStatus: 'PENDING_APPROVAL'));

    expect(find.textContaining('waiting for HR approval'), findsOneWidget);
    expect(find.text('Face punch in'), findsNothing);
    expect(find.text('Set up face attendance'), findsNothing);
  });

  testWidgets('shows the rejection reason', (tester) async {
    await _pumpStatus(tester, FaceEnrollmentStatus(profileStatus: 'REJECTED', reviewNote: 'Photo too dark'));

    expect(find.textContaining('Reason: Photo too dark'), findsOneWidget);
    expect(find.text('Face punch in'), findsNothing);
  });

  testWidgets('tells an unenrolled employee to ask HR', (tester) async {
    await _pumpStatus(tester, FaceEnrollmentStatus());

    expect(find.textContaining('Ask HR to open face enrollment'), findsOneWidget);
    expect(find.text('Face punch in'), findsNothing);
  });
}
