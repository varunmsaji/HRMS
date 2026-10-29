import 'package:dio/dio.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:hrms_mobile/core/api/api_client.dart';
import 'package:hrms_mobile/core/api/api_error.dart';
import 'package:hrms_mobile/features/attendance/data/attendance_repository.dart';
import 'package:hrms_mobile/features/attendance/domain/punch_location.dart';

class _RecordingClient implements ApiClient {
  final bodies = <Map<String, dynamic>>[];
  final forms = <Map<String, String>>[];

  @override
  dynamic noSuchMethod(Invocation invocation) {
    if (invocation.memberName == #postMultipart) {
      final form = (invocation.namedArguments[#buildForm] as FormData Function())();
      forms.add({for (final f in form.fields) f.key: f.value});
      return Future<FacePunchResult>.error(ApiError(status: 0, code: 'NETWORK_ERROR', message: 'offline'));
    }
    if (invocation.memberName == #post) {
      bodies.add(Map<String, dynamic>.from(invocation.namedArguments[#body] as Map));
      return Future<void>.value();
    }
    return super.noSuchMethod(invocation);
  }
}

final _loc = PunchLocation(latitude: 9.9312, longitude: 76.2673, accuracyM: 12.5, capturedAt: DateTime.utc(2026, 10, 28, 9));

/// The recording client fails the multipart call (only the form fields matter here).
Future<void> _faceBestEffort(_RecordingClient client, {PunchLocation? location, LocationFailure? locationError}) async {
  try {
    await AttendanceRepository(client).facePunchMe(
      direction: 'OUT',
      livenessSessionId: 's',
      frames: const [<int>[1]],
      idempotencyKey: 'k',
      location: location,
      locationError: locationError,
    );
  } on ApiError {
    // expected: the fake transport reports the network as down
  }
}

void main() {
  test('a plain punch sends no location fields unless one was captured', () async {
    final client = _RecordingClient();
    await AttendanceRepository(client).punchMe(direction: 'IN');
    expect(client.bodies.single.keys, {'direction', 'idempotency_key'});
  });

  test('a captured location rides along with exactly position, accuracy and capture time', () async {
    final client = _RecordingClient();
    await AttendanceRepository(client).punchMe(direction: 'IN', location: _loc);
    final body = client.bodies.single;
    expect(body['location'], {
      'latitude': 9.9312,
      'longitude': 76.2673,
      'accuracy_m': 12.5,
      'captured_at': '2026-10-28T09:00:00.000Z',
    });
    expect(body.containsKey('location_error'), isFalse);
    expect(body.keys.any((k) => k.contains('company') || k.contains('employee') || k.contains('branch')), isFalse);
  });

  test('a capture failure is reported by code; client-judged failures send nothing', () async {
    final client = _RecordingClient();
    final repo = AttendanceRepository(client);
    await repo.punchMe(direction: 'IN', locationError: LocationFailure.permissionDenied);
    await repo.punchMe(direction: 'IN', locationError: LocationFailure.poorAccuracy);
    expect(client.bodies[0]['location_error'], 'PERMISSION_DENIED');
    expect(client.bodies[1].containsKey('location_error'), isFalse);
  });

  test('a retry after a refusal can reuse the same idempotency key with a fresh location', () async {
    final client = _RecordingClient();
    final repo = AttendanceRepository(client);
    await repo.punchMe(direction: 'IN', idempotencyKey: 'idem_fixed', location: _loc);
    await repo.punchMe(direction: 'IN', idempotencyKey: 'idem_fixed', location: _loc);
    expect(client.bodies.map((b) => b['idempotency_key']), ['idem_fixed', 'idem_fixed']);
  });

  test('a face punch carries the location as form fields', () async {
    final client = _RecordingClient();
    await _faceBestEffort(
      client,
      location: _loc,
    );
    final form = client.forms.single;
    expect(form['location_latitude'], '9.9312');
    expect(form['location_longitude'], '76.2673');
    expect(form['location_accuracy_m'], '12.5');
    expect(form['location_captured_at'], '2026-10-28T09:00:00.000Z');
    expect(form.containsKey('location_error'), isFalse);
  });

  test('a face punch with a capture failure sends the error code only', () async {
    final client = _RecordingClient();
    await _faceBestEffort(client, locationError: LocationFailure.servicesDisabled);
    final form = client.forms.single;
    expect(form['location_error'], 'SERVICES_DISABLED');
    expect(form.keys.any((k) => k.startsWith('location_l') || k == 'location_accuracy_m'), isFalse);
  });

  test('geofence refusals are recognised by code, other errors are not', () {
    ApiError e(String code) => ApiError(status: 422, code: code, message: 'm');
    expect(isGeofenceError(e('PUNCH_OUTSIDE_GEOFENCE')), isTrue);
    expect(isGeofenceError(e('PUNCH_NO_APPLICABLE_WORKPLACE')), isTrue);
    expect(isGeofenceError(e('FACE_VERIFICATION_REQUIRED')), isFalse);
    expect(isGeofenceError(StateError('x')), isFalse);
    expect(geofenceErrorIsRetryable('PUNCH_OUTSIDE_GEOFENCE'), isTrue);
    expect(geofenceErrorIsRetryable('PUNCH_NO_APPLICABLE_WORKPLACE'), isFalse);
  });
}
