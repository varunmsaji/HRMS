import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:hrms_mobile/core/api/api_error.dart';
import 'package:hrms_mobile/features/attendance/data/attendance_repository.dart';
import 'package:hrms_mobile/features/attendance/presentation/face_punch_card.dart';
import 'package:hrms_mobile/features/attendance/presentation/holiday_calendars_screen.dart'
    show attendanceRepositoryProvider;

const _selfie = [0xff, 0xd8, 0xff, 0xe0];

FaceEnrollmentStatus _enrolled() => FaceEnrollmentStatus(profileStatus: 'ENROLLED');

class _FakeRepository implements AttendanceRepository {
  _FakeRepository(this.respond, {FaceEnrollmentStatus? status}) : status = status ?? _enrolled();

  final Future<FacePunchResult> Function() respond;
  final FaceEnrollmentStatus status;
  final calls = <({String direction, List<int> photo})>[];

  @override
  Future<FaceEnrollmentStatus> getMyFaceEnrollment() async => status;

  @override
  Future<FacePunchResult> facePunchMe({required String direction, required List<int> photoJpeg}) {
    calls.add((direction: direction, photo: photoJpeg));
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

Future<void> _pump(
  WidgetTester tester, {
  required _FakeRepository repository,
  required FaceCapture capture,
  VoidCallback? onPunched,
}) {
  return tester.pumpWidget(ProviderScope(
    overrides: [
      attendanceRepositoryProvider.overrideWithValue(repository),
      faceCaptureProvider.overrideWithValue(capture),
    ],
    child: MaterialApp(home: Scaffold(body: FacePunchCard(onPunched: onPunched))),
  )).then((_) => tester.pumpAndSettle());
}

Future<void> _pumpStatus(WidgetTester tester, FaceEnrollmentStatus status) => _pump(
      tester,
      repository: _FakeRepository(() async => _result('IN'), status: status),
      capture: () async => _selfie,
    );

void main() {
  testWidgets('punches in with the captured selfie and reports the match', (tester) async {
    final repository = _FakeRepository(() async => _result('IN'));
    var refreshed = 0;
    await _pump(tester, repository: repository, capture: () async => _selfie, onPunched: () => refreshed++);

    await tester.tap(find.text('Face punch in'));
    await tester.pumpAndSettle();

    expect(repository.calls.single.direction, 'IN');
    expect(repository.calls.single.photo, _selfie);
    expect(find.text('Punched in · face verified (97% match)'), findsOneWidget);
    expect(refreshed, 1);
  });

  testWidgets('cancelling the camera sends nothing', (tester) async {
    final repository = _FakeRepository(() async => _result('IN'));
    await _pump(tester, repository: repository, capture: () async => null);

    await tester.tap(find.text('Face punch out'));
    await tester.pumpAndSettle();

    expect(repository.calls, isEmpty);
  });

  testWidgets('shows the server reason when the face is rejected', (tester) async {
    final repository = _FakeRepository(() async => throw ApiError(
          status: 422,
          code: 'FACE_LIVENESS_FAILED',
          message: 'We could not confirm a live face. Face the camera directly and try again.',
        ));
    var refreshed = 0;
    await _pump(tester, repository: repository, capture: () async => _selfie, onPunched: () => refreshed++);

    await tester.tap(find.text('Face punch in'));
    await tester.pumpAndSettle();

    expect(find.text('We could not confirm a live face. Face the camera directly and try again.'), findsOneWidget);
    expect(refreshed, 0);
  });

  testWidgets('disables both buttons while verifying', (tester) async {
    final pending = Completer<FacePunchResult>();
    final repository = _FakeRepository(() => pending.future);
    await _pump(tester, repository: repository, capture: () async => _selfie);

    await tester.tap(find.text('Face punch out'));
    await tester.pump();

    expect(find.text('Verifying your face…'), findsOneWidget);
    expect(tester.widget<FilledButton>(find.byWidgetPredicate((w) => w is FilledButton)).onPressed, isNull);
    expect(tester.widget<OutlinedButton>(find.byWidgetPredicate((w) => w is OutlinedButton)).onPressed, isNull);

    pending.complete(_result('OUT'));
    await tester.pumpAndSettle();
    expect(find.text('Punched out · face verified (97% match)'), findsOneWidget);
  });

  testWidgets('explains how to fix a blocked camera', (tester) async {
    final repository = _FakeRepository(() async => _result('IN'));
    await _pump(tester, repository: repository, capture: () async => throw Exception('camera_access_denied'));

    await tester.tap(find.text('Face punch in'));
    await tester.pumpAndSettle();

    expect(find.textContaining('Allow camera access'), findsOneWidget);
    expect(repository.calls, isEmpty);
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
