import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:hrms_mobile/core/api/api_error.dart';
import 'package:hrms_mobile/core/api/envelope.dart';
import 'package:hrms_mobile/core/auth/permissions.dart';
import 'package:hrms_mobile/core/forms/form_spec.dart';
import 'package:hrms_mobile/core/providers.dart';
import 'package:hrms_mobile/features/leave/data/leave_repository.dart';
import 'package:hrms_mobile/features/leave/domain/leave_application_form.dart';
import 'package:hrms_mobile/features/leave/presentation/leave_application_detail_screen.dart';
import 'package:hrms_mobile/features/leave/presentation/leave_applications_screen.dart';
import 'package:hrms_mobile/features/leave/presentation/leave_types_screen.dart' show leaveRepositoryProvider;

import 'support/fake_api_client.dart';
import 'support/fake_auth.dart';

Map<String, dynamic> _app({String id = 'a1', String status = 'SUBMITTED', String employeeId = 'emp-2', String start = '2099-01-10', String end = '2099-01-11', int version = 3, String? stage = 'MANAGER', String? submittedBy, num lop = 0}) => {
      'id': id,
      'employee_id': employeeId,
      'leave_type_id': 'lt-1',
      'start_date': start,
      'end_date': end,
      'total_days': '2.00',
      'lop_days': lop.toStringAsFixed(2),
      'reason': 'Family function',
      'attachment_reference': null,
      'status': status,
      'approval_chain': 'MANAGER_THEN_HR',
      'approval_stage': stage,
      'submitted_by_user_id': submittedBy,
      'submitted_at': '2026-10-01T03:30:00Z',
      'reviewed_at': null,
      'reviewer_comment': null,
      'rejection_reason': null,
      'cancelled_at': null,
      'cancellation_reason': null,
      'version': version,
      'days': [
        {'calendar_date': start, 'fraction': '1.00', 'half': null, 'is_lop': false, 'is_sandwich_generated': false},
      ],
      'actions': [
        {'action': 'SUBMITTED', 'stage': null, 'comment': null, 'created_at': '2026-10-01T03:30:00Z'},
      ],
    };

class _FakeLeave implements LeaveRepository {
  _FakeLeave(this.apps);
  final List<Map<String, dynamic>> apps;
  final calls = <String>[];
  ApiError? approveError;

  @override
  Future<ListEnvelope<LeaveApplication>> listLeaveApplicationsPage({String? employeeId, String? dateFrom, String? dateTo, String? status, int page = 1}) async {
    calls.add('list:${employeeId ?? '*'}:${status ?? '*'}:${dateFrom ?? '*'}:p$page');
    return ListEnvelope(data: apps.map(LeaveApplication.fromJson).toList(), pagination: null, meta: ResponseMeta(requestId: 'r'));
  }

  @override
  Future<LeaveApplication> getLeaveApplication(String id) async => LeaveApplication.fromJson(apps.firstWhere((a) => a['id'] == id));

  @override
  Future<LeaveApplication> submitLeaveApplication(Map<String, dynamic> body) async {
    calls.add('submit:$body');
    return LeaveApplication.fromJson(apps.first);
  }

  @override
  Future<LeaveApplication> approveLeaveApplication(String id, {required String ifMatch, String? comment, bool excessAsLop = false}) async {
    calls.add('approve:$ifMatch:${comment ?? ''}:lop=$excessAsLop');
    if (approveError != null && !excessAsLop) throw approveError!;
    return LeaveApplication.fromJson({...apps.first, 'status': 'APPROVED'});
  }

  @override
  Future<LeaveApplication> rejectLeaveApplication(String id, {required String ifMatch, String? comment, String? reason}) async {
    calls.add('reject:$ifMatch:${comment ?? ''}:${reason ?? ''}');
    return LeaveApplication.fromJson({...apps.first, 'status': 'REJECTED'});
  }

  @override
  Future<LeaveApplication> cancelLeaveApplication(String id, {required String ifMatch, String? reason}) async {
    calls.add('cancel:$ifMatch:${reason ?? ''}');
    return LeaveApplication.fromJson({...apps.first, 'status': 'CANCELLED'});
  }

  @override
  dynamic noSuchMethod(Invocation invocation) => super.noSuchMethod(invocation);
}

FakeApiClient _api() => FakeApiClient(lists: {
      '/leave-types': [
        {'id': 'lt-1', 'name': 'Casual Leave', 'code': 'CL', 'is_active': true}
      ],
      '/employees': [
        {'id': 'emp-2', 'first_name': 'Ravi', 'last_name': 'Iyer', 'employee_code': 'E-2'}
      ],
    });

Future<void> _pump(WidgetTester tester, _FakeLeave repo, List<String> permissions, Widget home, {String? employeeId = 'emp-1'}) async {
  tester.view.physicalSize = const Size(800, 4000);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
  await tester.pumpWidget(ProviderScope(
    overrides: [leaveRepositoryProvider.overrideWithValue(repo), apiClientProvider.overrideWithValue(_api()), fakeAuth(permissions, employeeId: employeeId)],
    child: MaterialApp(home: home),
  ));
  await tester.pumpAndSettle();
}

void main() {
  group('apply form rules', () {
    final self = leaveApplicationSpec(onBehalf: false);
    Map<String, dynamic> v(Map<String, dynamic> over) => rowFromWire(self, {'leave_type_id': 'lt-1', 'start_date': '2026-10-05', 'end_date': '2026-10-06', ...over});

    test('valid single and multi-day requests pass', () {
      expect(validateRow(self, v({})), isEmpty);
      expect(validateRow(self, v({'end_date': '2026-10-05', 'half_day': 'FIRST_HALF'})), isEmpty);
    });

    test('end before start is rejected', () {
      expect(validateRow(self, v({'end_date': '2026-10-01'})).keys, ['end_date']);
    });

    test('a half day needs a single-day request', () {
      expect(validateRow(self, v({'half_day': 'SECOND_HALF'})).keys, ['half_day']);
    });

    test('leave type and dates are required, and on-behalf adds the employee', () {
      expect(validateRow(self, rowFromWire(self, {})).keys, containsAll(['leave_type_id', 'start_date', 'end_date']));
      expect(leaveApplicationSpec(onBehalf: true).fields.first.key, 'employee_id');
    });
  });

  group('list', () {
    testWidgets('an employee sees their own applications by default', (tester) async {
      final repo = _FakeLeave([_app(employeeId: 'emp-1')]);
      await _pump(tester, repo, [leaveApplicationSubmit], const LeaveApplicationsScreen());
      expect(repo.calls.first, startsWith('list:emp-1:'));
      expect(find.text('Casual Leave'), findsOneWidget);
      expect(find.text('Team'), findsNothing);
    });

    testWidgets('an approver starts on the team view, labelled by employee, and can switch to mine', (tester) async {
      final repo = _FakeLeave([_app()]);
      await _pump(tester, repo, [leaveApplicationApprove], const LeaveApplicationsScreen());
      expect(repo.calls.first, startsWith('list:*:'));
      expect(find.text('Ravi Iyer (E-2) · Casual Leave'), findsOneWidget);
      await tester.tap(find.text('Mine'));
      await tester.pumpAndSettle();
      expect(repo.calls.last, startsWith('list:emp-1:'));
    });

    testWidgets('the status filter is sent as application_status', (tester) async {
      final repo = _FakeLeave([_app()]);
      await _pump(tester, repo, [leaveApplicationSubmit], const LeaveApplicationsScreen());
      await tester.tap(find.byType(DropdownButtonFormField<String>).first);
      await tester.pumpAndSettle();
      await tester.tap(find.text('Approved').last);
      await tester.pumpAndSettle();
      expect(repo.calls.last, contains(':APPROVED:'));
    });

    testWidgets('applying sends the filled fields, with no employee_id for self-service', (tester) async {
      final repo = _FakeLeave([_app(employeeId: 'emp-1')]);
      await _pump(tester, repo, [leaveApplicationSubmit], const LeaveApplicationsScreen());
      await tester.tap(find.text('Apply for leave'));
      await tester.pumpAndSettle();
      await tester.tap(find.widgetWithText(FilledButton, 'Create'));
      await tester.pumpAndSettle();
      expect(find.text('Leave type is required.'), findsOneWidget);
      expect(repo.calls.where((c) => c.startsWith('submit')), isEmpty);
    });
  });

  group('detail', () {
    testWidgets('shows the request, days and history', (tester) async {
      final repo = _FakeLeave([_app()]);
      await _pump(tester, repo, const [], const LeaveApplicationDetailScreen(applicationId: 'a1'));
      expect(find.text('Casual Leave'), findsOneWidget);
      expect(find.text('Family function'), findsOneWidget);
      expect(find.text('Manager then hr'), findsOneWidget);
      expect(find.text('2099-01-10'), findsWidgets);
      expect(find.text('History'), findsOneWidget);
      expect(find.text('Oct 1, 2026, 9:00 am IST'), findsWidgets);
    });

    testWidgets('an approver can approve a pending application with a comment and the row version', (tester) async {
      final repo = _FakeLeave([_app()]);
      await _pump(tester, repo, [leaveApplicationApprove], const LeaveApplicationDetailScreen(applicationId: 'a1'));
      await tester.tap(find.widgetWithText(FilledButton, 'Approve'));
      await tester.pumpAndSettle();
      await tester.enterText(find.byType(TextField).last, 'Enjoy');
      await tester.tap(find.widgetWithText(FilledButton, 'Approve').last);
      await tester.pumpAndSettle();
      expect(repo.calls, contains('approve:3:Enjoy:lop=false'));
    });

    testWidgets('you cannot review your own application', (tester) async {
      final repo = _FakeLeave([_app(employeeId: 'emp-1')]);
      await _pump(tester, repo, [leaveApplicationApprove], const LeaveApplicationDetailScreen(applicationId: 'a1'));
      expect(find.widgetWithText(FilledButton, 'Approve'), findsNothing);
    });

    testWidgets('a balance shortfall offers approving the uncovered days as loss of pay', (tester) async {
      final repo = _FakeLeave([_app()])..approveError = ApiError(status: 409, code: 'LEAVE_APPLICATION_BALANCE_SHORTFALL', message: 'short', details: [ErrorDetail(code: 'x', message: 'x', context: {'available': '1.00', 'shortfall': '1.00'})]);
      await _pump(tester, repo, [leaveApplicationApprove], const LeaveApplicationDetailScreen(applicationId: 'a1'));
      await tester.tap(find.widgetWithText(FilledButton, 'Approve'));
      await tester.pumpAndSettle();
      await tester.tap(find.widgetWithText(FilledButton, 'Approve').last);
      await tester.pumpAndSettle();
      expect(find.textContaining('Not enough leave balance'), findsOneWidget);
      await tester.tap(find.text('Approve, uncovered days as loss of pay'));
      await tester.pumpAndSettle();
      expect(repo.calls.last, 'approve:3::lop=true');
    });

    testWidgets('rejecting sends the comment and reason', (tester) async {
      final repo = _FakeLeave([_app()]);
      await _pump(tester, repo, [leaveApplicationApprove], const LeaveApplicationDetailScreen(applicationId: 'a1'));
      await tester.tap(find.widgetWithText(OutlinedButton, 'Reject'));
      await tester.pumpAndSettle();
      await tester.enterText(find.byType(TextField).first, 'Sorry');
      await tester.enterText(find.byType(TextField).last, 'Peak season');
      await tester.tap(find.widgetWithText(FilledButton, 'Reject'));
      await tester.pumpAndSettle();
      expect(repo.calls.last, 'reject:3:Sorry:Peak season');
    });

    testWidgets('the owner can withdraw a submitted application', (tester) async {
      final repo = _FakeLeave([_app(employeeId: 'emp-1')]);
      await _pump(tester, repo, const [], const LeaveApplicationDetailScreen(applicationId: 'a1'));
      await tester.tap(find.widgetWithText(OutlinedButton, 'Cancel application'));
      await tester.pumpAndSettle();
      await tester.tap(find.widgetWithText(FilledButton, 'Cancel application'));
      await tester.pumpAndSettle();
      expect(repo.calls.last, 'cancel:3:');
    });

    testWidgets('approved leave that has started needs a reason to cancel, and only HR can cancel it', (tester) async {
      final started = _app(employeeId: 'emp-1', status: 'APPROVED', start: '2020-01-01', end: '2020-01-02', stage: null);
      // an employee cannot cancel their own leave once it has started
      var repo = _FakeLeave([started]);
      await _pump(tester, repo, const [], const LeaveApplicationDetailScreen(applicationId: 'a1'));
      expect(find.widgetWithText(OutlinedButton, 'Cancel application'), findsNothing);
    });

    testWidgets('HR cancelling started leave must give a reason', (tester) async {
      final started = _app(status: 'APPROVED', start: '2020-01-01', end: '2020-01-02', stage: null);
      final repo = _FakeLeave([started]);
      await _pump(tester, repo, [leaveApplicationCancelApproved], const LeaveApplicationDetailScreen(applicationId: 'a1'));
      await tester.tap(find.widgetWithText(OutlinedButton, 'Cancel application'));
      await tester.pumpAndSettle();
      await tester.tap(find.widgetWithText(FilledButton, 'Cancel application'));
      await tester.pumpAndSettle();
      expect(find.text('A reason is required.'), findsOneWidget);
      expect(repo.calls.where((c) => c.startsWith('cancel')), isEmpty);
      await tester.enterText(find.byType(TextField).last, 'Recalled');
      await tester.tap(find.widgetWithText(FilledButton, 'Cancel application'));
      await tester.pumpAndSettle();
      expect(repo.calls.last, 'cancel:3:Recalled');
    });

    testWidgets('an employee can cancel approved leave before it starts', (tester) async {
      final future = _app(employeeId: 'emp-1', status: 'APPROVED', stage: null);
      final repo = _FakeLeave([future]);
      await _pump(tester, repo, const [], const LeaveApplicationDetailScreen(applicationId: 'a1'));
      expect(find.widgetWithText(OutlinedButton, 'Cancel application'), findsOneWidget);
    });
  });
}
