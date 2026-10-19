import 'dart:typed_data';

import 'package:dio/dio.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:hrms_mobile/core/api/api_client.dart';
import 'package:hrms_mobile/core/api/api_error.dart';
import 'package:hrms_mobile/features/attendance/data/attendance_repository.dart';
import 'package:hrms_mobile/features/attendance/domain/face_liveness_capture.dart';

const _good = FaceFrameReading(faceCount: 1, faceWidthFraction: 0.45, yaw: 2, pitch: -3, leftEyeOpen: 0.9, rightEyeOpen: 0.8);

FaceFrameReading _with({int? faceCount, double? width, double? yaw, double? pitch, double? leftEye}) => FaceFrameReading(
      faceCount: faceCount ?? 1,
      faceWidthFraction: width ?? 0.45,
      yaw: yaw ?? 2,
      pitch: pitch ?? -3,
      leftEyeOpen: leftEye ?? 0.9,
      rightEyeOpen: 0.8,
    );

/// Answers the two face-punch calls from canned envelopes, recording what was sent.
class _RecordingClient implements ApiClient {
  final posts = <(String, Object?)>[];
  final forms = <(String, FormData)>[];

  @override
  dynamic noSuchMethod(Invocation invocation) {
    final path = invocation.positionalArguments.first as String;
    final parse = invocation.namedArguments[#parse] as dynamic Function(dynamic);
    if (invocation.memberName == #post) {
      posts.add((path, invocation.namedArguments[#body]));
      return Future<FaceLivenessSession>.value(parse({'session_id': 's-1', 'direction': 'IN', 'expires_at': '2026-10-15T10:02:00Z', 'frames_required': 3}) as FaceLivenessSession);
    }
    if (invocation.memberName == #postMultipart) {
      forms.add((path, (invocation.namedArguments[#buildForm] as FormData Function())()));
      return Future<FacePunchResult>.value(parse({
        'punch': {'id': 'p-1', 'direction': 'IN', 'punch_time': '2026-10-15T10:00:30Z'},
        'similarity': '0.9700',
        'liveness_score': '0.9500',
      }) as FacePunchResult);
    }
    return super.noSuchMethod(invocation);
  }
}

void main() {
  group('FaceCaptureGate (quality only, never liveness)', () {
    test('needs several consecutive good readings', () {
      final gate = FaceCaptureGate(stableReadings: 3);
      expect(gate.accept(_good), FaceCaptureHint.holdStill);
      expect(gate.accept(_good), FaceCaptureHint.holdStill);
      expect(gate.accept(_good), FaceCaptureHint.ready);
      expect(gate.ready, isTrue);
    });

    test('any bad reading starts the count again', () {
      final gate = FaceCaptureGate(stableReadings: 2);
      gate.accept(_good);
      expect(gate.accept(_with(faceCount: 2)), FaceCaptureHint.multipleFaces);
      expect(gate.accept(_good), FaceCaptureHint.holdStill);
      expect(gate.ready, isFalse);
    });

    test('names the problem', () {
      final gate = FaceCaptureGate();
      expect(gate.accept(_with(faceCount: 0)), FaceCaptureHint.noFace);
      expect(gate.accept(_with(width: 0.1)), FaceCaptureHint.moveCloser);
      expect(gate.accept(_with(width: 0.95)), FaceCaptureHint.moveBack);
      expect(gate.accept(_with(yaw: 30)), FaceCaptureHint.lookStraight);
      expect(gate.accept(_with(pitch: -25)), FaceCaptureHint.lookStraight);
      expect(gate.accept(_with(leftEye: 0.05)), FaceCaptureHint.openEyes);
      expect(gate.accept(const FaceFrameReading(faceCount: 1)), FaceCaptureHint.moveCloser);
    });

    test('every hint has user-facing text', () {
      for (final hint in FaceCaptureHint.values) {
        expect(faceCaptureHintText(hint), isNotEmpty);
      }
    });
  });

  test('a challenge is usable only while capture and upload still fit before it expires', () {
    final expires = DateTime.utc(2026, 10, 15, 10, 2);
    expect(challengeStillUsable(expires, DateTime.utc(2026, 10, 15, 10, 1)), isTrue);
    expect(challengeStillUsable(expires, DateTime.utc(2026, 10, 15, 10, 1, 50)), isFalse);
    expect(challengeStillUsable(expires, DateTime.utc(2026, 10, 15, 10, 3)), isFalse);
  });

  group('facePunchOutcomeUnknown', () {
    test('no response or a proxy failure is unknown', () {
      expect(facePunchOutcomeUnknown(NetworkError()), isTrue);
      expect(facePunchOutcomeUnknown(NetworkError.timeout(isWrite: true)), isTrue);
      expect(facePunchOutcomeUnknown(ApiError(status: 504, code: 'SERVICE_UNAVAILABLE', message: 'x')), isTrue);
      expect(facePunchOutcomeUnknown(ApiError(status: 500, code: 'UNKNOWN_ERROR', message: 'x')), isTrue);
    });

    test('any answer from the API itself is known', () {
      for (final (status, code) in [
        (422, 'FACE_SPOOF_SUSPECTED'),
        (503, 'FACE_LIVENESS_UNAVAILABLE'),
        (502, 'FACE_PROVIDER_FAILED'),
        (409, 'FACE_LIVENESS_CHALLENGE_USED'),
        (500, 'INTERNAL_ERROR'),
      ]) {
        expect(facePunchOutcomeUnknown(ApiError(status: status, code: code, message: 'x')), isFalse, reason: code);
      }
      expect(facePunchOutcomeUnknown(Exception('x')), isFalse);
    });
  });

  test('the repository requests a challenge, then sends the frames bound to it', () async {
    final client = _RecordingClient();
    final repository = AttendanceRepository(client);

    final session = await repository.startFaceLivenessSession('IN');
    expect(session.sessionId, 's-1');
    expect(session.framesRequired, 3);
    expect(session.expiresAt, DateTime.utc(2026, 10, 15, 10, 2));
    expect(client.posts.single.$1, '/attendance/face-punches/me/liveness-sessions');
    expect(client.posts.single.$2, {'direction': 'IN'});

    final frames = [
      for (var i = 0; i < 3; i++) Uint8List.fromList([0xff, 0xd8, i]),
    ];
    final result = await repository.facePunchMe(direction: 'IN', livenessSessionId: session.sessionId, frames: frames, idempotencyKey: 'idem_key_0123456789');

    final (path, form) = client.forms.single;
    expect(path, '/attendance/face-punches/me');
    expect(Map.fromEntries(form.fields), {'direction': 'IN', 'liveness_session_id': 's-1', 'idempotency_key': 'idem_key_0123456789'});
    expect(form.files.map((f) => f.key), ['frames', 'frames', 'frames']);
    expect(form.fields.any((f) => f.key.contains('live') && f.key != 'liveness_session_id'), isFalse,
        reason: 'the app never sends a liveness verdict or score');
    expect(result.livenessScore, closeTo(0.95, 1e-9));
  });
}
