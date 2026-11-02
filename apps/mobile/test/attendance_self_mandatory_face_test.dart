import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:hrms_mobile/core/api/api_error.dart';
import 'package:hrms_mobile/features/attendance/data/attendance_repository.dart';
import 'package:hrms_mobile/features/attendance/domain/punch_location.dart';
import 'package:hrms_mobile/features/attendance/presentation/attendance_self_screen.dart';

import 'support/fake_auth.dart';

class _Repo implements AttendanceRepository {
  _Repo(this.status, {this.punchError});
  final FaceEnrollmentStatus status;
  final Object? punchError;
  final plainPunches = <String>[];

  @override
  Future<FaceEnrollmentStatus> getMyFaceEnrollment() async => status;

  @override
  Future<List<AttendanceDay>> listAttendanceDays({String? employeeId, required String dateFrom, required String dateTo, String? attendanceStatus}) async => [];

  @override
  Future<void> punchMe({required String direction, String? reference, String? idempotencyKey, PunchLocation? location, LocationFailure? locationError}) async {
    plainPunches.add(direction);
    if (punchError != null) throw punchError!;
  }

  @override
  dynamic noSuchMethod(Invocation invocation) => super.noSuchMethod(invocation);
}

Future<void> _pump(WidgetTester tester, _Repo repo) async {
  await tester.pumpWidget(ProviderScope(
    overrides: [
      fakeAuth(['ATTENDANCE.PUNCH'], employeeId: 'e-1'),
      attendanceRepositoryProvider.overrideWithValue(repo),
    ],
    child: const MaterialApp(home: Scaffold(body: AttendanceSelfScreen())),
  ));
  await tester.pumpAndSettle();
}

void main() {
  test('face_verification_required is read from the API, else derived from the status', () {
    expect(
      FaceEnrollmentStatus.fromJson({'profile': {'status': 'ENROLLED'}, 'open_window': null, 'face_verification_required': true})
          .faceVerificationRequired,
      isTrue,
    );
    expect(
      FaceEnrollmentStatus.fromJson({'profile': {'status': 'PENDING_APPROVAL'}, 'open_window': null, 'face_verification_required': false})
          .faceVerificationRequired,
      isFalse,
    );
    expect(FaceEnrollmentStatus(profileStatus: 'ENROLLED').faceVerificationRequired, isTrue);
    expect(FaceEnrollmentStatus().faceVerificationRequired, isFalse);
  });

  testWidgets('enrolled employee punches in with their face and out with a plain Punch out', (tester) async {
    await _pump(tester, _Repo(FaceEnrollmentStatus(profileStatus: 'ENROLLED', faceVerificationRequired: true)));

    // Face verification gates check-in only.
    expect(find.text('Face punch in'), findsOneWidget);
    expect(find.text('Punch out'), findsOneWidget);
    expect(find.text('Punch in'), findsNothing);
    expect(find.text('Face punch out'), findsNothing);
  });

  testWidgets('unenrolled employee keeps the plain Punch in/out', (tester) async {
    final repo = _Repo(FaceEnrollmentStatus());
    await _pump(tester, repo);

    expect(find.text('Punch in'), findsOneWidget);
    expect(find.text('Punch out'), findsOneWidget);
    await tester.tap(find.text('Punch in'));
    await tester.pumpAndSettle();
    expect(repo.plainPunches, ['IN']);
  });

  testWidgets('pending-approval employee keeps the plain Punch in/out', (tester) async {
    await _pump(tester, _Repo(FaceEnrollmentStatus(profileStatus: 'PENDING_APPROVAL', faceVerificationRequired: false)));

    expect(find.text('Punch in'), findsOneWidget);
    expect(find.text('Face punch in'), findsNothing);
  });

  testWidgets('a FACE_VERIFICATION_REQUIRED answer turns Punch in into Face punch in, with no plain fallback', (tester) async {
    final repo = _Repo(
      FaceEnrollmentStatus(),
      punchError: ApiError(status: 403, code: 'FACE_VERIFICATION_REQUIRED', message: 'Face verification is required to punch.'),
    );
    await _pump(tester, repo);

    await tester.tap(find.text('Punch in'));
    await tester.pumpAndSettle();

    expect(repo.plainPunches, ['IN']);
    expect(find.text('Punch in'), findsNothing);
    expect(find.text('Face punch in'), findsOneWidget);
    expect(find.text('Punch out'), findsOneWidget);
  });
}
