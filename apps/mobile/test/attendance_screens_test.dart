import 'dart:convert';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:hrms_mobile/core/auth/permissions.dart';
import 'package:hrms_mobile/core/providers.dart';
import 'package:hrms_mobile/features/attendance/data/attendance_repository.dart';
import 'package:hrms_mobile/features/attendance/presentation/attendance_day_detail_screen.dart';
import 'package:hrms_mobile/features/attendance/presentation/face_enrollment_admin_card.dart';
import 'package:hrms_mobile/features/attendance/presentation/team_attendance_screen.dart';
import 'package:hrms_mobile/features/payroll/presentation/employee_salary_panel.dart';

import 'support/fake_api_client.dart';
import 'support/fake_auth.dart';

/// A realistic `AttendanceDayRead` — the generated contract fixture with a few facts overridden.
Map<String, dynamic> _dayJson({Map<String, dynamic> over = const {}}) {
  final base = jsonDecode(File('test/fixtures/contract/attendance.AttendanceDayRead.sparse.json').readAsStringSync()) as Map<String, dynamic>;
  return {
    ...base,
    'id': 'day-1',
    'employee_id': 'emp-1',
    'attendance_date': '2026-10-01',
    'timezone': 'Asia/Kolkata',
    'attendance_status': 'PRESENT',
    'actual_first_in': '2026-10-01T03:30:00Z',
    'actual_last_out': '2026-10-01T12:45:00Z',
    'worked_minutes': 555,
    'late_minutes': 0,
    'is_locked': false,
    'breaks': <dynamic>[],
    'is_late': false,
    'is_early_out': false,
    'is_overtime': false,
    'missing_punch': false,
    'work_on_leave_flagged': false,
    'is_pending_approval': false,
    ...over,
  };
}

class _FakeAttendance implements AttendanceRepository {
  _FakeAttendance(this.day, {this.days = const []});
  final Map<String, dynamic> day;
  final List<Map<String, dynamic>> days;
  final calls = <String>[];

  @override
  Future<AttendanceDay> getAttendanceDay(String id) async => AttendanceDay.fromJson(day);

  @override
  Future<List<LeaveDayProjection>> listLeaveProjections({required String employeeId, required String dateFrom, required String dateTo}) async => const [];

  @override
  Future<AttendanceDay> recomputeAttendanceDay(String id) async {
    calls.add('recompute');
    return AttendanceDay.fromJson(day);
  }

  @override
  Future<AttendanceDay> keepLeaveOverPunches(String id, {required String reason}) async {
    calls.add('keep-leave:$reason');
    return AttendanceDay.fromJson({...day, 'work_on_leave_resolution': 'KEEP_LEAVE'});
  }

  @override
  Future<List<AttendanceDay>> listAttendanceDays({String? employeeId, required String dateFrom, required String dateTo, String? attendanceStatus}) async {
    calls.add('days:${employeeId ?? '*'}:$dateFrom:${attendanceStatus ?? '*'}');
    return days.map(AttendanceDay.fromJson).toList();
  }

  @override
  dynamic noSuchMethod(Invocation invocation) => super.noSuchMethod(invocation);
}

Future<_FakeAttendance> _pumpDetail(WidgetTester tester, Map<String, dynamic> day, List<String> permissions) async {
  tester.view.physicalSize = const Size(800, 4000);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
  final repo = _FakeAttendance(day);
  await tester.pumpWidget(ProviderScope(
    overrides: [attendanceRepositoryProvider.overrideWithValue(repo), fakeAuth(permissions)],
    child: const MaterialApp(home: AttendanceDayDetailScreen(dayId: 'day-1')),
  ));
  await tester.pumpAndSettle();
  return repo;
}

void main() {
  faceAdminTests();
  testWidgets('times are shown in the company zone, not as raw UTC', (tester) async {
    await _pumpDetail(tester, _dayJson(), const []);
    expect(find.text('Oct 1, 2026, 9:00 am IST'), findsOneWidget); // first in
    expect(find.text('Oct 1, 2026, 6:15 pm IST'), findsOneWidget); // last out
    expect(find.text('9h 15m'), findsNWidgets(2)); // worked minutes: the status header figure and the Actual row
    expect(find.textContaining('03:30'), findsNothing);
    // S12: the status header carries the date and the zone the day was computed in.
    expect(find.text('2026-10-01'), findsOneWidget);
    expect(find.text('Asia/Kolkata (IST)'), findsOneWidget);
  });

  testWidgets('flags show as badges', (tester) async {
    await _pumpDetail(tester, _dayJson(over: {'is_late': true, 'missing_punch': true, 'is_overtime': true}), const []);
    expect(find.text('Late'), findsWidgets); // the badge and the "Late" row
    expect(find.text('Missing punch'), findsOneWidget);
    expect(find.text('Overtime'), findsOneWidget);
  });

  testWidgets('recompute needs the permission and is blocked on a locked day', (tester) async {
    await _pumpDetail(tester, _dayJson(), const []);
    expect(find.text('Recompute'), findsNothing);
  });

  testWidgets('a privileged user can recompute after confirming', (tester) async {
    final repo = await _pumpDetail(tester, _dayJson(), [attendanceRecompute]);
    await tester.tap(find.text('Recompute'));
    await tester.pumpAndSettle();
    await tester.tap(find.widgetWithText(FilledButton, 'Recompute'));
    await tester.pumpAndSettle();
    // The screen also looks up the neighbouring days for previous/next.
    expect(repo.calls.where((c) => !c.startsWith('days:')), ['recompute']);
  });

  testWidgets('recompute is disabled when the day is locked', (tester) async {
    await _pumpDetail(tester, _dayJson(over: {'is_locked': true}), [attendanceRecompute]);
    final button = tester.widget<OutlinedButton>(find.widgetWithText(OutlinedButton, 'Recompute'));
    expect(button.onPressed, isNull);
    expect(find.text('Locked'), findsOneWidget);
  });

  testWidgets('keep leave is offered only for an unresolved work-on-leave day, and needs a reason', (tester) async {
    final repo = await _pumpDetail(tester, _dayJson(over: {'work_on_leave_flagged': true, 'work_on_leave_resolution': null}), [attendanceRecompute]);
    expect(find.text('Worked on leave — needs HR decision'), findsOneWidget);
    await tester.tap(find.widgetWithText(OutlinedButton, 'Keep leave'));
    await tester.pumpAndSettle();
    await tester.tap(find.widgetWithText(FilledButton, 'Keep leave'));
    await tester.pumpAndSettle();
    expect(find.text('A reason is required.'), findsOneWidget);
    await tester.enterText(find.byType(TextField).last, 'Leave approved earlier');
    await tester.tap(find.widgetWithText(FilledButton, 'Keep leave'));
    await tester.pumpAndSettle();
    // The screen also looks up the neighbouring days for previous/next.
    expect(repo.calls.where((c) => !c.startsWith('days:')), ['keep-leave:Leave approved earlier']);
  });

  testWidgets('keep leave is hidden once resolved', (tester) async {
    await _pumpDetail(tester, _dayJson(over: {'work_on_leave_flagged': true, 'work_on_leave_resolution': 'KEEP_LEAVE'}), [attendanceRecompute]);
    expect(find.widgetWithText(OutlinedButton, 'Keep leave'), findsNothing);
    expect(find.text('Leave kept by HR'), findsOneWidget);
  });

  group('team attendance', () {
    Future<_FakeAttendance> pump(WidgetTester tester, List<String> permissions) async {
      tester.view.physicalSize = const Size(800, 3000);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.reset);
      final repo = _FakeAttendance(
        _dayJson(),
        days: [
          _dayJson(over: {'id': 'a', 'employee_id': 'e1', 'missing_punch': true, 'attendance_status': 'INCOMPLETE'}),
          _dayJson(over: {'id': 'b', 'employee_id': 'e2', 'attendance_status': 'PRESENT'}),
        ],
      );
      final api = FakeApiClient(lists: {
        '/employees': [
          {'id': 'e1', 'first_name': 'Asha', 'last_name': 'Rao', 'employee_code': 'E-1'},
          {'id': 'e2', 'first_name': 'Ravi', 'last_name': 'Iyer', 'employee_code': 'E-2'},
        ],
      });
      await tester.pumpWidget(ProviderScope(
        overrides: [attendanceRepositoryProvider.overrideWithValue(repo), apiClientProvider.overrideWithValue(api), fakeAuth(permissions)],
        child: const MaterialApp(home: TeamAttendanceScreen()),
      ));
      await tester.pumpAndSettle();
      return repo;
    }

    testWidgets('lists the day for everyone, labelled by employee', (tester) async {
      await pump(tester, const []);
      expect(find.textContaining('Asha Rao (E-1)'), findsOneWidget);
      expect(find.textContaining('Ravi Iyer (E-2)'), findsOneWidget);
    });

    testWidgets('the missing-punch filter narrows the list', (tester) async {
      await pump(tester, const []);
      await tester.tap(find.text('Missing punch'));
      await tester.pumpAndSettle();
      expect(find.textContaining('Asha Rao (E-1)'), findsOneWidget);
      expect(find.textContaining('Ravi Iyer (E-2)'), findsNothing);
    });

    testWidgets('recording a punch on behalf is gated on the permission', (tester) async {
      await pump(tester, const []);
      expect(find.byTooltip('Record punch'), findsNothing);
    });

    testWidgets('a user with the permission sees the record-punch action', (tester) async {
      await pump(tester, [attendancePunchOnBehalf]);
      expect(find.byTooltip('Record punch'), findsOneWidget);
    });

    testWidgets('the status filter narrows the list locally, keeping the day summary whole', (tester) async {
      final repo = await pump(tester, const []);
      await tester.tap(find.byType(DropdownButtonFormField<String>).first);
      await tester.pumpAndSettle();
      await tester.tap(find.text('PRESENT').last);
      await tester.pumpAndSettle();
      expect(repo.calls.last, endsWith(':*'));
      expect(find.textContaining('Ravi Iyer (E-2)'), findsOneWidget);
      expect(find.textContaining('Asha Rao (E-1)'), findsNothing);
      expect(find.text('Status distribution'), findsOneWidget);
    });
  });

  group('employee salary panel', () {
    Future<FakeApiClient> pumpSalary(WidgetTester tester, List<String> permissions, {List<Map<String, dynamic>> history = const []}) async {
      tester.view.physicalSize = const Size(800, 3000);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.reset);
      final client = FakeApiClient(
        lists: {
          '/employees/emp-1/salary': history,
          '/payroll/salary-structures': [
            {'id': 'ss-1', 'name': 'Standard', 'code': 'STD', 'is_active': true}
          ],
        },
        objects: {
          '/employees/emp-1/salary/breakup': {
            'employee_id': 'emp-1',
            'as_of': '2026-10-01',
            'pay_basis': 'MONTHLY',
            'salary_structure_id': 'ss-1',
            'pf_applicable': true,
            'esi_applicable': false,
            'breakup': {
              'annual_ctc_minor': 120000000,
              'monthly_ctc_minor': 10000000,
              'gross_monthly_minor': 9000000,
              'employer_contributions_monthly_minor': 1000000,
              'lines': [
                {'component_code': 'BASIC', 'component_name': 'Basic', 'component_type': 'EARNING', 'monthly_minor': 5000000, 'annual_minor': 60000000, 'basis': '50% of CTC'},
                {'component_code': 'PF', 'component_name': 'Employer PF', 'component_type': 'EMPLOYER_CONTRIBUTION', 'monthly_minor': 1000000, 'annual_minor': 12000000, 'basis': '12% of basic'},
              ],
            },
          },
        },
      );
      await tester.pumpWidget(ProviderScope(
        overrides: [apiClientProvider.overrideWithValue(client), fakeAuth(permissions)],
        child: const MaterialApp(home: Scaffold(body: EmployeeSalaryPanel(employeeId: 'emp-1'))),
      ));
      await tester.pumpAndSettle();
      return client;
    }

    testWidgets('shows the CTC breakup and the structure name', (tester) async {
      await pumpSalary(tester, const []);
      expect(find.textContaining('Standard · PF applies'), findsOneWidget);
      expect(find.text('Basic'), findsOneWidget);
      expect(find.textContaining('₹1,00,000 / mo'), findsWidgets); // cost to company
      expect(find.text('Assign'), findsNothing);
    });

    testWidgets('assigning a structure posts structure, date and reason without the UI-only toggle', (tester) async {
      final client = await pumpSalary(tester, [payrollSetupManage]);
      await tester.tap(find.text('Assign'));
      await tester.pumpAndSettle();
      await tester.tap(find.byType(DropdownButtonFormField<String>).first);
      await tester.pumpAndSettle();
      await tester.tap(find.text('Standard').last);
      await tester.pumpAndSettle();
      await tester.tap(find.widgetWithText(TextField, '').first);
      await tester.pumpAndSettle();
      await tester.tap(find.text('OK'));
      await tester.pumpAndSettle();
      await tester.enterText(find.byType(TextField).last, 'Joined');
      await tester.tap(find.widgetWithText(FilledButton, 'Create'));
      await tester.pumpAndSettle();
      final call = client.calls.single;
      expect(call.path, '/employees/emp-1/salary');
      final body = call.body as Map<String, dynamic>;
      expect(body.keys.toSet(), {'salary_structure_id', 'effective_from', 'reason'});
      expect(body['salary_structure_id'], 'ss-1');
      expect(body['reason'], 'Joined');
    });
  });
}

// ---- HR face-enrollment admin ----------------------------------------------------------------

class _FakeFaceRepo implements AttendanceRepository {
  _FakeFaceRepo(this.status);
  final Map<String, dynamic> status;
  final calls = <String>[];

  @override
  Future<Map<String, dynamic>> getFaceProfileStatus(String employeeId) async => status;

  @override
  Future<void> openFaceEnrollmentWindow(String employeeId) async => calls.add('open');

  @override
  Future<void> approveFaceProfile(String employeeId) async => calls.add('approve');

  @override
  Future<void> rejectFaceProfile(String employeeId, {String? note}) async => calls.add('reject:${note ?? ''}');

  @override
  Future<void> revokeFaceProfile(String employeeId) async => calls.add('revoke');

  @override
  Future<void> cancelFaceEnrollmentWindow(String employeeId) async => calls.add('cancel');

  @override
  dynamic noSuchMethod(Invocation invocation) => super.noSuchMethod(invocation);
}

void faceAdminTests() {
  Future<_FakeFaceRepo> pumpFace(WidgetTester tester, Map<String, dynamic> status) async {
    tester.view.physicalSize = const Size(800, 3000);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.reset);
    final repo = _FakeFaceRepo(status);
    await tester.pumpWidget(ProviderScope(
      overrides: [attendanceRepositoryProvider.overrideWithValue(repo), fakeAuth(const [])],
      child: const MaterialApp(home: Scaffold(body: SingleChildScrollView(child: FaceEnrollmentAdminCard(employeeId: 'emp-1', employeeLabel: 'Asha Rao')))),
    ));
    await tester.pumpAndSettle();
    return repo;
  }

  group('face enrollment admin', () {
    testWidgets('not enrolled -> open enrollment', (tester) async {
      final repo = await pumpFace(tester, {'profile': null, 'open_window': null});
      expect(find.text('Not enrolled'), findsOneWidget);
      await tester.tap(find.text('Open face enrollment'));
      await tester.pumpAndSettle();
      expect(repo.calls, ['open']);
    });

    testWidgets('an open window can be cancelled', (tester) async {
      final repo = await pumpFace(tester, {'profile': null, 'open_window': {'expires_at': '2026-10-02T10:00:00Z'}});
      expect(find.text('Enrollment open'), findsOneWidget);
      expect(find.textContaining('until Oct 2, 2026, 3:30 pm IST'), findsOneWidget);
      await tester.tap(find.text('Cancel enrollment'));
      await tester.pumpAndSettle();
      expect(repo.calls, ['cancel']);
    });

    testWidgets('a pending submission can be approved', (tester) async {
      final repo = await pumpFace(tester, {
        'profile': {'status': 'PENDING_APPROVAL', 'enrolled_at': '2026-10-01T03:30:00Z', 'has_review_photo': false},
        'open_window': null,
      });
      expect(find.text('Awaiting approval'), findsOneWidget);
      await tester.tap(find.text('Approve'));
      await tester.pumpAndSettle();
      expect(repo.calls, ['approve']);
    });

    testWidgets('a pending submission can be rejected with a reason', (tester) async {
      final repo = await pumpFace(tester, {
        'profile': {'status': 'PENDING_APPROVAL', 'enrolled_at': '2026-10-01T03:30:00Z', 'has_review_photo': false},
        'open_window': null,
      });
      await tester.tap(find.widgetWithText(OutlinedButton, 'Reject'));
      await tester.pumpAndSettle();
      await tester.enterText(find.byType(TextField), 'Photo is blurry');
      await tester.tap(find.widgetWithText(FilledButton, 'Reject'));
      await tester.pumpAndSettle();
      expect(repo.calls, ['reject:Photo is blurry']);
    });

    testWidgets('an enrolled profile can be revoked after confirming', (tester) async {
      final repo = await pumpFace(tester, {
        'profile': {'status': 'ENROLLED', 'reviewed_at': '2026-10-01T03:30:00Z', 'reference_photo_count': 5},
        'open_window': null,
      });
      expect(find.text('Enrolled'), findsOneWidget);
      await tester.tap(find.widgetWithText(OutlinedButton, 'Revoke'));
      await tester.pumpAndSettle();
      await tester.tap(find.widgetWithText(FilledButton, 'Revoke'));
      await tester.pumpAndSettle();
      expect(repo.calls, ['revoke']);
    });

    testWidgets('a rejected profile shows the reason and offers a retry', (tester) async {
      await pumpFace(tester, {
        'profile': {'status': 'REJECTED', 'reviewed_at': '2026-10-01T03:30:00Z', 'review_note': 'Blurry'},
        'open_window': null,
      });
      expect(find.textContaining('Reason: Blurry'), findsOneWidget);
      expect(find.text('Open face enrollment'), findsOneWidget);
    });
  });
}
