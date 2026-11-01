import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:hrms_mobile/features/attendance/data/attendance_repository.dart';
import 'package:hrms_mobile/features/home/presentation/employee_home_screen.dart';

class _Repo implements AttendanceRepository {
  _Repo({this.failWith});
  final Object? failWith;
  int starts = 0;

  @override
  Future<void> startMyFaceEnrollment() async {
    starts++;
    if (failWith != null) throw failWith!;
  }

  @override
  dynamic noSuchMethod(Invocation invocation) => super.noSuchMethod(invocation);
}

Widget _host(_Repo repo, FaceEnrollmentStatus status, VoidCallback onChanged) => ProviderScope(
      overrides: [attendanceRepositoryProvider.overrideWithValue(repo)],
      child: MaterialApp(home: Scaffold(body: FaceSetupCard(status: status, onChanged: onChanged))),
    );

FaceEnrollmentStatus _status(Map<String, dynamic> json) => FaceEnrollmentStatus.fromJson(json);

void main() {
  test('status parses the server state and the company requirement', () {
    final s = _status({'profile': null, 'open_window': null, 'enrollment_state': 'NOT_ENROLLED', 'company_requires_enrollment': true});
    expect(s.enrollmentState, 'NOT_ENROLLED');
    expect(s.companyRequiresEnrollment, isTrue);
    expect(s.isEnrolled, isFalse);
    expect(s.canEnroll, isFalse);
    expect(_status({'profile': null, 'open_window': null}).companyRequiresEnrollment, isFalse); // older server
  });

  testWidgets('not enrolled: explains, offers Start Enrollment, calls the self-start API', (tester) async {
    final repo = _Repo(failWith: Exception('boom'));
    var changed = 0;
    await tester.pumpWidget(_host(repo, _status({'profile': null, 'open_window': null, 'company_requires_enrollment': true}), () => changed++));
    expect(find.text('Face Attendance Setup'), findsOneWidget);
    expect(find.textContaining('Your company requires face enrollment'), findsOneWidget);
    await tester.tap(find.text('Start Enrollment'));
    await tester.pumpAndSettle();
    expect(repo.starts, 1);
    // Backend refusal: stays on the card (no capture screen), tells the user, refreshes status.
    expect(find.text('Face Attendance Setup'), findsOneWidget);
    expect(find.byType(SnackBar), findsOneWidget);
    expect(changed, 1);
  });

  testWidgets('pending approval: no action offered, never claims enrollment', (tester) async {
    final status = _status({
      'profile': {'status': 'PENDING_APPROVAL'},
      'open_window': null,
      'enrollment_state': 'PENDING_APPROVAL',
    });
    await tester.pumpWidget(_host(_Repo(), status, () {}));
    expect(find.text('Face enrollment submitted'), findsOneWidget);
    expect(find.text('Start Enrollment'), findsNothing);
  });

  testWidgets('rejected: shows HR note and allows retry', (tester) async {
    final status = _status({
      'profile': {'status': 'REJECTED', 'review_note': 'Photo too dark'},
      'open_window': null,
    });
    await tester.pumpWidget(_host(_Repo(), status, () {}));
    expect(find.textContaining('Photo too dark'), findsOneWidget);
    expect(find.text('Start Enrollment'), findsOneWidget);
  });

  testWidgets('window already open: offers Continue Enrollment without starting a second one', (tester) async {
    final status = _status({
      'profile': null,
      'open_window': {'expires_at': '2099-01-01T00:00:00Z'},
    });
    await tester.pumpWidget(_host(_Repo(), status, () {}));
    expect(find.text('Continue Enrollment'), findsOneWidget);
  });
}
