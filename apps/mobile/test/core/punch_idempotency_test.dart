import 'package:dio/dio.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:hrms_mobile/core/api/api_error.dart';
import 'package:hrms_mobile/core/api/api_client.dart';
import 'package:hrms_mobile/features/attendance/data/attendance_repository.dart';

/// Records the body of every POST and the form fields of every multipart POST.
class _RecordingClient implements ApiClient {
  final bodies = <Map<String, dynamic>>[];
  final forms = <Map<String, String>>[];

  @override
  dynamic noSuchMethod(Invocation invocation) {
    if (invocation.memberName == #postMultipart) {
      final form =
          (invocation.namedArguments[#buildForm] as FormData Function())();
      forms.add({for (final f in form.fields) f.key: f.value});
      return Future<FacePunchResult>.error(ApiError(status: 0, code: 'NETWORK_ERROR', message: 'offline'));
    }
    if (invocation.memberName == #post) {
      bodies.add(
        Map<String, dynamic>.from(invocation.namedArguments[#body] as Map),
      );
      return Future<void>.value();
    }
    return super.noSuchMethod(invocation);
  }
}

void main() {
  test(
    'a self punch always carries an idempotency key, and a retry can resend the same one',
    () async {
      final client = _RecordingClient();
      final repo = AttendanceRepository(client);

      await repo.punchMe(direction: 'IN');
      await repo.punchMe(direction: 'IN', idempotencyKey: 'idem_fixed');
      await repo.punchMe(direction: 'IN', idempotencyKey: 'idem_fixed');

      expect(client.bodies[0]['idempotency_key'], startsWith('idem_'));
      expect(client.bodies[1]['idempotency_key'], 'idem_fixed');
      expect(client.bodies[2]['idempotency_key'], 'idem_fixed');
    },
  );

  test(
    'a face punch carries its key and challenge, and a retry resends the same key',
    () async {
      final client = _RecordingClient();
      final repo = AttendanceRepository(client);

      for (final (session, key) in [
        ('session-1', 'idem_first_key_0123456789'),
        ('session-2', 'idem_fixed_key_0123456789'),
        ('session-3', 'idem_fixed_key_0123456789'),
      ]) {
        await expectLater(
          repo.facePunchMe(
            direction: 'IN',
            livenessSessionId: session,
            frames: const [
              [1, 2, 3],
            ],
            idempotencyKey: key,
          ),
          throwsA(isA<ApiError>()),
        );
      }

      expect(client.forms[0]['idempotency_key'], 'idem_first_key_0123456789');
      expect(client.forms[1]['idempotency_key'], 'idem_fixed_key_0123456789');
      expect(client.forms[2]['idempotency_key'], 'idem_fixed_key_0123456789');
      expect(client.forms[2]['liveness_session_id'], 'session-3');
      expect(client.forms[0]['direction'], 'IN');
    },
  );
}
