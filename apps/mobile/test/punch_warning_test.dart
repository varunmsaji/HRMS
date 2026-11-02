import 'package:flutter_test/flutter_test.dart';
import 'package:hrms_mobile/core/api/api_error.dart';
import 'package:hrms_mobile/core/api/envelope.dart';
import 'package:hrms_mobile/features/attendance/domain/punch_warning.dart';

ApiError _error(String code, Map<String, dynamic> context) => ApiError(
      status: 409,
      code: code,
      message: 'm',
      details: [ErrorDetail(code: code, message: 'm', context: context)],
    );

void main() {
  test('reads a too-soon refusal with the wait and the previous punch', () {
    final w = PunchWarning.fromError(_error(punchTooSoonCode, {
      'retry_after_seconds': 95,
      'min_gap_seconds': 120,
      'last_direction': 'IN',
      'last_punch_time': '2026-11-02T07:12:00+00:00',
    }))!;
    expect(w.kind, PunchWarningKind.tooSoon);
    expect(w.retryAfterSeconds, 95);
    expect(w.lastWasIn, isTrue);
    expect(w.explanation, contains('2 minutes'));
  });

  test('reads an already-recorded refusal', () {
    final w = PunchWarning.fromError(_error(punchAlreadyRecordedCode, {
      'last_direction': 'OUT',
      'last_punch_time': '2026-11-02T07:12:00+00:00',
    }))!;
    expect(w.kind, PunchWarningKind.alreadyRecorded);
    expect(w.title, "You're already punched out");
  });

  test('ignores other errors and unreadable details', () {
    expect(PunchWarning.fromError(_error('SOMETHING_ELSE', {})), isNull);
    expect(PunchWarning.fromError(_error(punchTooSoonCode, {'oops': 1})), isNull);
    expect(PunchWarning.fromError(StateError('x')), isNull);
  });
}
