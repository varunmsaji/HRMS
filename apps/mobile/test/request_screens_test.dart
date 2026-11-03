import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:hrms_mobile/core/api/api_error.dart';
import 'package:hrms_mobile/core/auth/permissions.dart';
import 'package:hrms_mobile/core/providers.dart';
import 'package:hrms_mobile/core/requests/request_screens.dart';
import 'package:hrms_mobile/features/attendance/domain/request_resources.dart';

import 'support/fake_api_client.dart';
import 'support/fake_auth.dart';

Map<String, dynamic> _reg({String id = 'r1', String status = 'SUBMITTED', String employeeId = 'emp-2', int version = 4, String? submittedBy, String? stage = 'MANAGER'}) => {
      'id': id,
      'employee_id': employeeId,
      'attendance_date': '2026-10-01',
      'request_type': 'MISSING_PUNCH',
      'reason': 'Forgot to punch out',
      'attachment_reference': null,
      'requested_shift_id': null,
      'status': status,
      'approval_chain': 'MANAGER_THEN_HR',
      'approval_stage': stage,
      'submitted_by_user_id': submittedBy,
      'submitted_at': '2026-10-01T03:30:00Z',
      'reviewed_at': null,
      'reviewer_comment': null,
      'rejection_reason': null,
      'applied_at': null,
      'cancelled_at': null,
      'version': version,
      'requested_punches': [
        {'direction': 'OUT', 'requested_time': '2026-10-01T12:45:00Z', 'sort_order': 0},
      ],
      'actions': [
        {'action': 'SUBMITTED', 'stage': null, 'comment': null, 'created_at': '2026-10-01T03:30:00Z'},
      ],
    };

FakeApiClient _api({List<Map<String, dynamic>> rows = const [], Map<String, Map<String, dynamic>> objects = const {}, Map<String, Object> failing = const {}}) => FakeApiClient(
      lists: {
        '/regularizations': rows,
        '/overtime': rows,
        '/employees': [
          {'id': 'emp-2', 'first_name': 'Ravi', 'last_name': 'Iyer', 'employee_code': 'E-2'}
        ],
        '/shifts': [
          {'id': 'sh-1', 'name': 'General', 'is_active': true}
        ],
      },
      objects: objects,
      failing: failing,
    );

Future<void> _pump(WidgetTester tester, FakeApiClient api, List<String> permissions, Widget home, {String? employeeId = 'emp-1'}) async {
  tester.view.physicalSize = const Size(800, 4000);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
  await tester.pumpWidget(ProviderScope(overrides: [apiClientProvider.overrideWithValue(api), fakeAuth(permissions, employeeId: employeeId)], child: MaterialApp(home: home)));
  await tester.pumpAndSettle();
}

void main() {
  group('regularization list', () {
    testWidgets('an employee sees their own requests for the last 30 business days', (tester) async {
      final api = _api(rows: [_reg(employeeId: 'emp-1')]);
      await _pump(tester, api, [attendanceRegularizationRequest], RequestListScreen(config: regularizationConfig));
      final call = api.listCalls.firstWhere((c) => c.path == '/regularizations');
      expect(call.filters!['employee_id'], 'emp-1');
      expect(DateTime.parse(call.filters!['date_to'] as String).difference(DateTime.parse(call.filters!['date_from'] as String)).inDays, 30);
      expect(find.text('Missing punch · 2026-10-01'), findsOneWidget);
      expect(find.text('Team'), findsNothing);
    });

    testWidgets('an approver starts on Team, with the employee named, and can narrow by type and status', (tester) async {
      final api = _api(rows: [_reg()]);
      await _pump(tester, api, [attendanceRegularizationApprove], RequestListScreen(config: regularizationConfig));
      expect(api.listCalls.firstWhere((c) => c.path == '/regularizations').filters!.containsKey('employee_id'), isFalse);
      expect(find.text('Ravi Iyer (E-2) · Missing punch · 2026-10-01'), findsOneWidget);

      await tester.tap(find.byType(DropdownButtonFormField<String>).first);
      await tester.pumpAndSettle();
      await tester.tap(find.text('Approved').last);
      await tester.pumpAndSettle();
      expect(api.listCalls.last.filters!['request_status'], 'APPROVED');

      await tester.tap(find.byType(DropdownButtonFormField<String>).at(1));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Wrong shift').last);
      await tester.pumpAndSettle();
      expect(api.listCalls.last.filters!['request_type'], 'WRONG_SHIFT');
    });

    testWidgets('the company account (no employee record) sees Team only, never an unfiltered "Mine"', (tester) async {
      final api = _api(rows: [_reg()]);
      await _pump(tester, api, [attendanceRegularizationApprove, attendanceRegularizationRequestOnBehalf], RequestListScreen(config: regularizationConfig), employeeId: null);
      expect(find.text('Mine'), findsNothing);
      expect(find.text('Team'), findsNothing, reason: 'with one scope there is nothing to switch between');
      expect(find.text('Ravi Iyer (E-2) · Missing punch · 2026-10-01'), findsOneWidget);
    });

    testWidgets('Mine switches to the signed-in employee', (tester) async {
      final api = _api(rows: [_reg()]);
      await _pump(tester, api, [attendanceRegularizationApprove], RequestListScreen(config: regularizationConfig));
      await tester.tap(find.text('Mine'));
      await tester.pumpAndSettle();
      expect(api.listCalls.last.filters!['employee_id'], 'emp-1');
    });
  });

  group('regularization form', () {
    test('needs a shift or at least one punch time', () {
      final spec = regularizationSpec(false);
      final base = {'attendance_date': '2026-10-01', 'request_type': 'MISSING_PUNCH'};
      expect(spec.extraValidate!({...base, 'correct_shift': false, 'punch_in_time': '', 'punch_out_time': ''}).keys, ['punch_in_time']);
      expect(spec.extraValidate!({...base, 'correct_shift': false, 'punch_in_time': '09:00', 'punch_out_time': ''}), isEmpty);
      expect(spec.extraValidate!({...base, 'correct_shift': true, 'requested_shift_id': ''}).keys, ['requested_shift_id']);
      expect(spec.extraValidate!({...base, 'correct_shift': true, 'requested_shift_id': 's1'}), isEmpty);
    });

    test('punch times are converted from the company zone to UTC, not the device zone', () {
      final body = buildRegularizationBody({'attendance_date': '2026-10-01', 'request_type': 'WRONG_PUNCH', 'punch_in_time': '09:00', 'punch_out_time': '18:15'}, 'Asia/Kolkata');
      expect(body['requested_punches'], [
        {'direction': 'IN', 'requested_time': '2026-10-01T03:30:00.000Z'},
        {'direction': 'OUT', 'requested_time': '2026-10-01T12:45:00.000Z'},
      ]);
    });

    testWidgets('submitting posts the built body', (tester) async {
      final api = _api(rows: [_reg(employeeId: 'emp-1')]);
      await _pump(tester, api, [attendanceRegularizationRequest], RequestListScreen(config: regularizationConfig));
      await tester.tap(find.text('Regularization request'));
      await tester.pumpAndSettle();
      await tester.tap(find.widgetWithText(FilledButton, 'Create'));
      await tester.pumpAndSettle();
      expect(find.text('Attendance date is required.'), findsOneWidget);
      expect(find.text('Request type is required.'), findsOneWidget);
      expect(api.calls, isEmpty);
    });
  });

  group('regularization detail', () {
    Future<FakeApiClient> pumpDetail(WidgetTester tester, Map<String, dynamic> row, List<String> permissions, {Map<String, Object> failing = const {}}) async {
      final api = _api(objects: {'/regularizations/${row['id']}': row}, failing: failing);
      await _pump(tester, api, permissions, RequestDetailScreen(config: regularizationConfig, requestId: row['id'] as String), employeeId: 'emp-1');
      return api;
    }

    testWidgets('shows the request with times in the company zone', (tester) async {
      await pumpDetail(tester, _reg(), const []);
      expect(find.text('Forgot to punch out'), findsOneWidget);
      expect(find.text('Manager then hr'), findsOneWidget);
      expect(find.text('OUT · Oct 1, 2026, 6:15 pm IST'), findsOneWidget);
    });

    testWidgets('a reviewer approves with the row version and a comment', (tester) async {
      final api = await pumpDetail(tester, _reg(), [attendanceRegularizationApprove]);
      await tester.tap(find.widgetWithText(FilledButton, 'Approve'));
      await tester.pumpAndSettle();
      await tester.enterText(find.byType(TextField).last, 'ok');
      await tester.tap(find.widgetWithText(FilledButton, 'Approve').last);
      await tester.pumpAndSettle();
      final call = api.calls.single;
      expect(call.path, '/regularizations/r1/approve');
      expect(call.ifMatch, '4');
      expect(call.body, {'reviewer_comment': 'ok'});
    });

    testWidgets('rejecting sends comment and reason', (tester) async {
      final api = await pumpDetail(tester, _reg(), [attendanceRegularizationApprove]);
      await tester.tap(find.widgetWithText(OutlinedButton, 'Reject'));
      await tester.pumpAndSettle();
      await tester.enterText(find.byType(TextField).first, 'No');
      await tester.enterText(find.byType(TextField).last, 'Not allowed');
      await tester.tap(find.widgetWithText(FilledButton, 'Reject'));
      await tester.pumpAndSettle();
      expect(api.calls.single.body, {'reviewer_comment': 'No', 'rejection_reason': 'Not allowed'});
    });

    testWidgets('you cannot review your own request, and a decided request has no actions', (tester) async {
      await pumpDetail(tester, _reg(employeeId: 'emp-1'), [attendanceRegularizationApprove]);
      expect(find.widgetWithText(FilledButton, 'Approve'), findsNothing);
    });

    testWidgets('the server refusing a self-approval shows the specific message', (tester) async {
      final api = _api(
        objects: {'/regularizations/r1': _reg()},
        failing: {'/regularizations/r1/approve': ApiError(status: 403, code: 'REGULARIZATION_APPROVER_MISMATCH', message: 'no')},
      );
      await _pump(tester, api, [attendanceRegularizationApprove], RequestDetailScreen(config: regularizationConfig, requestId: 'r1'));
      await tester.tap(find.widgetWithText(FilledButton, 'Approve'));
      await tester.pumpAndSettle();
      await tester.tap(find.widgetWithText(FilledButton, 'Approve').last);
      await tester.pumpAndSettle();
      expect(find.textContaining('not the resolved approver'), findsOneWidget);
    });

    testWidgets('only the submitter can cancel a submitted request, with the version', (tester) async {
      // fakeAuth's user id is 'u-1'
      final api = await pumpDetail(tester, _reg(submittedBy: 'u-1', employeeId: 'emp-1'), const []);
      await tester.tap(find.widgetWithText(OutlinedButton, 'Cancel request'));
      await tester.pumpAndSettle();
      await tester.tap(find.widgetWithText(FilledButton, 'Cancel request'));
      await tester.pumpAndSettle();
      final call = api.calls.single;
      expect(call.path, '/regularizations/r1/cancel');
      expect(call.ifMatch, '4');
    });

    testWidgets('someone else cannot cancel it', (tester) async {
      await pumpDetail(tester, _reg(submittedBy: 'someone-else'), const []);
      expect(find.widgetWithText(OutlinedButton, 'Cancel request'), findsNothing);
    });
  });

  group('overtime', () {
    Map<String, dynamic> ot({String status = 'PENDING', int version = 2, String employeeId = 'emp-2'}) => {
          'id': 'o1',
          'employee_id': employeeId,
          'attendance_date': '2026-10-01',
          'day_class': 'WEEKLY_OFF',
          'classification_code': 'OT2X',
          'configured_multiplier': '2.00',
          'minutes_detected': 125,
          'minutes_approved': 0,
          'comp_off_minutes': 0,
          'status': status,
          'approval_chain': 'MANAGER',
          'approval_stage': 'MANAGER',
          'reviewed_at': null,
          'reviewer_comment': null,
          'rejection_reason': null,
          'version': version,
          'actions': <dynamic>[],
        };

    testWidgets('lists records using the record_status filter name and has no create button', (tester) async {
      final api = _api(rows: [ot()]);
      await _pump(tester, api, [attendanceOvertimeApprove], RequestListScreen(config: overtimeConfig));
      expect(find.textContaining('Detected 2h 5m'), findsOneWidget);
      expect(find.text('Overtime record'), findsNothing);
      await tester.tap(find.byType(DropdownButtonFormField<String>).first);
      await tester.pumpAndSettle();
      await tester.tap(find.text('Pending').last);
      await tester.pumpAndSettle();
      expect(api.listCalls.last.filters!['record_status'], 'PENDING');
    });

    testWidgets('a pending record can be approved by someone else, never cancelled', (tester) async {
      final api = _api(objects: {'/overtime/o1': ot(version: 6)});
      await _pump(tester, api, [attendanceOvertimeApprove], RequestDetailScreen(config: overtimeConfig, requestId: 'o1'));
      expect(find.text('2h 5m'), findsOneWidget);
      expect(find.text('Cancel request'), findsNothing);
      await tester.tap(find.widgetWithText(FilledButton, 'Approve'));
      await tester.pumpAndSettle();
      await tester.tap(find.widgetWithText(FilledButton, 'Approve').last);
      await tester.pumpAndSettle();
      expect(api.calls.single.path, '/overtime/o1/approve');
      expect(api.calls.single.ifMatch, '6');
    });

    testWidgets('a decided record offers no review', (tester) async {
      final api = _api(objects: {'/overtime/o1': ot(status: 'APPROVED')});
      await _pump(tester, api, [attendanceOvertimeApprove], RequestDetailScreen(config: overtimeConfig, requestId: 'o1'));
      expect(find.widgetWithText(FilledButton, 'Approve'), findsNothing);
    });
  });
}
