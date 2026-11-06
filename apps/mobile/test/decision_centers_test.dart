import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:hrms_mobile/core/api/api_error.dart';
import 'package:hrms_mobile/core/auth/permissions.dart';
import 'package:hrms_mobile/core/providers.dart';
import 'package:hrms_mobile/core/requests/request_screens.dart';
import 'package:hrms_mobile/core/time.dart';
import 'package:hrms_mobile/features/attendance/domain/regularization_decision_center.dart';
import 'package:hrms_mobile/features/attendance/domain/request_resources.dart';
import 'package:hrms_mobile/features/attendance/presentation/regularization_decision_center_screen.dart';
import 'package:hrms_mobile/features/leave/domain/leave_decision_center.dart';
import 'package:hrms_mobile/features/leave/presentation/leave_applications_screen.dart';
import 'package:hrms_mobile/features/leave/presentation/leave_decision_center_screen.dart';

import 'support/fake_api_client.dart';
import 'support/fake_auth.dart';

const _leavePath = '/leave-applications/decision-center';
const _regPath = '/regularizations/decision-center';
final _now = DateTime.utc(2026, 11, 5, 6);

Map<String, dynamic> _leaveItem({String employeeId = 'e-2', String status = 'SUBMITTED', String lop = '1.00', String? balance = '2.00', List<Map<String, dynamic>> away = const [{'name': 'Asha Rao', 'start_date': '2026-11-09', 'end_date': '2026-11-09', 'status': 'APPROVED'}]}) => {
      'id': 'l-1',
      'version': 3,
      'employee_id': employeeId,
      'employee_name': 'Ravi Iyer',
      'employee_code': 'E-2',
      'designation': 'Engineer',
      'department': 'Platform',
      'leave_type_id': 'lt-1',
      'leave_type': 'Casual Leave',
      'start_date': '2026-11-09',
      'end_date': '2026-11-11',
      'total_days': '3.00',
      'lop_days': lop,
      'reason': 'Family function',
      'status': status,
      'approval_stage': 'MANAGER',
      'submitted_at': '2026-11-04T06:00:00Z',
      'current_balance': balance,
      'post_approval_balance': balance == null ? null : '0.00',
      'department_size': 8,
      'colleagues_away': away,
    };

Map<String, dynamic> _leaveData({List<Map<String, dynamic>>? items, int pending = 1}) => {
      'today': '2026-11-05',
      'summary': {'pending_count': pending, 'oldest_pending_at': pending == 0 ? null : '2026-11-03T06:00:00Z', 'on_leave_today': 3, 'on_leave_today_by_type': [['Casual Leave', 2], ['Sick Leave', 1]], 'active_staff': 48, 'available_pct': 93.75, 'upcoming_starts_7d': 4, 'peak_day': '2026-11-09', 'peak_day_away': 5},
      'counts': {'pending': pending, 'approved': 31, 'declined': 4},
      'tab': 'pending',
      'items': items ?? [_leaveItem()],
    };

Map<String, dynamic> _regItem({String employeeId = 'e-2'}) => {
      'id': 'r-1',
      'version': 2,
      'employee_id': employeeId,
      'employee_name': 'Ravi Iyer',
      'employee_code': 'E-2',
      'designation': 'Engineer',
      'department': 'Platform',
      'attendance_date': '2026-11-03',
      'timezone': 'Asia/Kolkata',
      'shift_name': 'General',
      'request_type': 'MISSING_PUNCH',
      'status': 'SUBMITTED',
      'approval_stage': 'HR',
      'submitted_at': '2026-11-04T06:00:00Z',
      'reason': 'Phone was off',
      'recorded_first_in': '2026-11-03T03:45:00Z',
      'recorded_last_out': null,
      'recorded_worked_minutes': null,
      'recorded_late_minutes': 15,
      'recorded_status': 'INCOMPLETE',
      'recorded_missing_punch': true,
      'requested_punches': [{'direction': 'OUT', 'time': '2026-11-03T12:30:00Z'}],
      'requested_span_minutes': 525,
    };

Map<String, dynamic> _regData() => {
      'today': '2026-11-05',
      'summary': {'pending_count': 1, 'oldest_pending_at': '2026-11-04T06:00:00Z', 'window_regularized_days': 6, 'window_expected_days': 240, 'window_rate_pct': 2.5},
      'counts': {'pending': 1, 'approved': 18, 'declined': 2},
      'tab': 'pending',
      'items': [_regItem()],
    };

/// Records the query the panel asks for (the base fake drops it).
class _Api extends FakeApiClient {
  _Api({super.objects, super.failing, super.lists});
  final asked = <String>[];

  @override
  Future<T> get<T>(String path, {required T Function(dynamic) parse, bool authenticated = true}) {
    asked.add(path);
    return super.get(path, parse: parse, authenticated: authenticated);
  }
}

Future<void> _pump(WidgetTester tester, _Api api, Widget child, {List<String> permissions = const [leaveApplicationApprove, attendanceRegularizationApprove], String? employeeId = 'me', double width = 390, double scale = 1}) async {
  tester.view.physicalSize = Size(width, 2400);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
  await tester.pumpWidget(ProviderScope(
    overrides: [apiClientProvider.overrideWithValue(api), fakeAuth(permissions, employeeId: employeeId)],
    child: MaterialApp(
      builder: (context, c) => MediaQuery(data: MediaQuery.of(context).copyWith(textScaler: TextScaler.linear(scale)), child: c!),
      home: child,
    ),
  ));
  await tester.pumpAndSettle();
}

void main() {
  group('helpers', () {
    test('relative times match the web', () {
      expect(relativeTime('2026-11-05T06:00:00Z', now: _now), 'just now');
      expect(relativeTime('2026-11-05T05:59:00Z', now: _now), '1 min ago');
      expect(relativeTime('2026-11-05T03:00:00Z', now: _now), '3 hours ago');
      expect(relativeTime('2026-11-03T06:00:00Z', now: _now), '2 days ago');
      expect(relativeTime('2026-08-01T06:00:00Z', now: _now), '1 Aug 2026');
    });

    test('days lose trailing zeros', () {
      expect(formatDays(6), '6');
      expect(formatDays(2.5), '2.5');
      expect(formatDays(null), '—');
    });

    test('the clash line names at most three people', () {
      LeaveDecisionItem item(List<String> names, {String? department = 'Platform'}) => LeaveDecisionItem.fromJson({
            ..._leaveItem(away: [for (final n in names) {'name': n}]),
            'department': department,
          });
      expect(item(const []).clash, (clash: false, text: 'No one else in Platform is away during this period.'));
      expect(item(const ['A', 'B', 'A']).clash.text, '2 of 8 in Platform also away: A, B.');
      expect(item(const ['A', 'B', 'C', 'D']).clash.text, '4 of 8 in Platform also away: A, B, C and 1 more.');
      expect(item(const [], department: null).clash.text, 'No one else in the same department is away during this period.');
    });

    test('the requested correction takes the earliest in and latest out', () {
      final item = RegularizationDecisionItem.fromJson({
        ..._regItem(),
        'requested_punches': [
          {'direction': 'IN', 'time': '2026-11-03T04:00:00Z'},
          {'direction': 'IN', 'time': '2026-11-03T03:30:00Z'},
          {'direction': 'OUT', 'time': '2026-11-03T12:00:00Z'},
          {'direction': 'OUT', 'time': '2026-11-03T13:00:00Z'},
        ],
      });
      expect(item.requestedTime('IN'), '2026-11-03T03:30:00Z');
      expect(item.requestedTime('OUT'), '2026-11-03T13:00:00Z');
      expect(RegularizationDecisionItem.fromJson({..._regItem(), 'requested_punches': const []}).requestedTime('IN'), isNull);
    });
  });

  group('leave decision centre', () {
    Widget panel() => Scaffold(body: LeaveDecisionCenterPanel(now: _now));

    testWidgets('shows the headline figures and what approving would do', (tester) async {
      await _pump(tester, _Api(objects: {_leavePath: _leaveData()}), panel());
      expect(find.text('Oldest submitted 2 days ago'), findsOneWidget);
      expect(find.text('2 Casual, 1 Sick · 48 active staff'), findsOneWidget);
      expect(find.text('Peak absence: 2026-11-09 (5 away)'), findsOneWidget);
      expect(find.text('94%'), findsOneWidget);
      expect(find.text('Ravi Iyer (E-2)'), findsOneWidget);
      expect(find.text('Casual Leave · 3 days'), findsOneWidget);
      expect(find.text('−2 days'), findsOneWidget, reason: 'three days less one of loss of pay');
      expect(find.text('1 day will be treated as loss of pay.'), findsOneWidget);
      expect(find.text('1 of 8 in Platform also away: Asha Rao.'), findsOneWidget);
    });

    testWidgets('tabs ask the server for that tab', (tester) async {
      final api = _Api(objects: {_leavePath: _leaveData()});
      await _pump(tester, api, panel());
      expect(api.asked.single, '$_leavePath?tab=pending');
      await tester.tap(find.text('Approved leaves (31)'));
      await tester.pumpAndSettle();
      expect(api.asked.last, '$_leavePath?tab=approved');
    });

    testWidgets('your own request cannot be decided from here', (tester) async {
      await _pump(tester, _Api(objects: {_leavePath: _leaveData(items: [_leaveItem(employeeId: 'me')])}), panel());
      expect(find.text('Approve leave'), findsNothing);
      expect(find.text('Decline'), findsNothing);
      expect(find.text('View details'), findsOneWidget);
    });

    testWidgets('a decided request has no decision buttons or balance preview', (tester) async {
      await _pump(tester, _Api(objects: {_leavePath: _leaveData(items: [_leaveItem(status: 'APPROVED')])}), panel());
      expect(find.text('Approve leave'), findsNothing);
      expect(find.text('Balance deduction'.toUpperCase()), findsNothing);
    });

    testWidgets('says when the server sent only part of a tab', (tester) async {
      await _pump(tester, _Api(objects: {_leavePath: _leaveData(pending: 60)}), panel());
      expect(find.text('Showing 1 of 60. Use Team to filter further.'), findsOneWidget);
    });

    testWidgets('nothing waiting is explained', (tester) async {
      await _pump(tester, _Api(objects: {_leavePath: _leaveData(items: const [], pending: 0)}), panel());
      expect(find.text('No requests here.'), findsOneWidget);
      expect(find.text('Nothing waiting'), findsOneWidget);
    });

    testWidgets('no access is explained', (tester) async {
      await _pump(tester, _Api(failing: {_leavePath: ApiError(status: 403, code: 'PERMISSION_DENIED', message: 'x')}), panel());
      expect(find.text('You do not have permission to review leave requests.'), findsOneWidget);
    });

    testWidgets('fits a small phone at large text', (tester) async {
      await _pump(tester, _Api(objects: {_leavePath: _leaveData()}), panel(), width: 320, scale: 2);
      expect(tester.takeException(), isNull);
    });
  });

  group('attendance correction decision centre', () {
    Widget panel() => Scaffold(body: RegularizationDecisionCenterPanel(now: _now));

    testWidgets('puts what was recorded beside what is being asked for', (tester) async {
      await _pump(tester, _Api(objects: {_regPath: _regData()}), panel());
      expect(find.text('2.5%'), findsOneWidget);
      expect(find.text('6 of 240 working days regularized'), findsOneWidget);
      expect(find.text('18 / 2'), findsOneWidget);
      expect(find.text('Pending HR review'), findsOneWidget);
      expect(find.text('Missing'), findsOneWidget);
      expect(find.text('Status incomplete · 15m late'), findsOneWidget);
      expect(find.text('Missing punch'), findsOneWidget);
      expect(find.textContaining('6:00 pm'), findsOneWidget, reason: 'the requested out, in the zone of the day');
      expect(find.text('No change'), findsOneWidget);
      expect(find.text('8h 45m'), findsOneWidget);
    });

    testWidgets('Approve opens the existing review, and a decision refreshes the list', (tester) async {
      final api = _Api(objects: {_regPath: _regData(), '/regularizations/r-1': _regItem(), '/regularizations/r-1/approve': {..._regItem(), 'status': 'APPROVED'}});
      await _pump(tester, api, panel());
      await tester.tap(find.text('Approve'));
      await tester.pumpAndSettle();
      expect(api.asked, contains('/regularizations/r-1'));
      final asksBefore = api.asked.where((p) => p.startsWith(_regPath)).length;
      await tester.tap(find.widgetWithText(FilledButton, 'Approve').last);
      await tester.pumpAndSettle();
      expect(api.calls.single.path, '/regularizations/r-1/approve');
      expect(api.calls.single.ifMatch, '2');
      expect(find.text('Pending decisions'), findsOneWidget, reason: 'back on the decision centre');
      expect(api.asked.where((p) => p.startsWith(_regPath)).length, asksBefore + 1);
    });

    testWidgets('backing out of the review saves nothing and returns to the list', (tester) async {
      final api = _Api(objects: {_regPath: _regData(), '/regularizations/r-1': _regItem()});
      await _pump(tester, api, panel());
      await tester.tap(find.text('Decline'));
      await tester.pumpAndSettle();
      await tester.tap(find.widgetWithText(TextButton, 'Cancel'));
      await tester.pumpAndSettle();
      expect(api.calls, isEmpty);
      expect(find.text('Decline'), findsOneWidget);
    });

    testWidgets('fits a small phone at large text', (tester) async {
      await _pump(tester, _Api(objects: {_regPath: _regData()}), panel(), width: 320, scale: 2);
      expect(tester.takeException(), isNull);
    });
  });

  group('where it appears', () {
    testWidgets('an approver opens on Decisions and can switch to Mine and Team', (tester) async {
      final api = _Api(objects: {_regPath: _regData()}, lists: const {'/regularizations': []});
      await _pump(tester, api, RequestListScreen(config: regularizationConfig, decisionCenter: Scaffold(body: RegularizationDecisionCenterPanel(now: _now))));
      expect(find.text('Pending decisions'), findsOneWidget);
      expect(api.listCalls.map((c) => c.path), isNot(contains('/regularizations')));
      for (final label in ['Mine', 'Decisions', 'Team']) {
        expect(find.text(label), findsOneWidget, reason: label);
      }
      await tester.tap(find.text('Team'));
      await tester.pumpAndSettle();
      expect(find.text('Pending decisions'), findsNothing);
      expect(api.listCalls.map((c) => c.path), contains('/regularizations'));
    });

    testWidgets('someone who cannot approve never sees it', (tester) async {
      final api = _Api(objects: {_regPath: _regData()}, lists: const {'/regularizations': []});
      await _pump(tester, api, RequestListScreen(config: regularizationConfig, decisionCenter: Scaffold(body: RegularizationDecisionCenterPanel(now: _now))), permissions: const [attendanceRegularizationRequest]);
      expect(find.text('Decisions'), findsNothing);
      expect(api.asked, isEmpty);
    });

    testWidgets('the company account gets Decisions and Team, never Mine', (tester) async {
      final api = _Api(objects: {_leavePath: _leaveData()}, lists: const {'/leave-applications': []});
      await _pump(tester, api, LeaveApplicationsScreen(decisionCenter: Scaffold(body: LeaveDecisionCenterPanel(now: _now))), employeeId: null);
      expect(find.text('Mine'), findsNothing);
      expect(find.text('Decisions'), findsOneWidget);
      expect(find.text('Team'), findsOneWidget);
    });

    testWidgets('all three choices fit a small phone at large text', (tester) async {
      final api = _Api(objects: {_leavePath: _leaveData()}, lists: const {'/leave-applications': []});
      await _pump(tester, api, LeaveApplicationsScreen(decisionCenter: Scaffold(body: LeaveDecisionCenterPanel(now: _now))), width: 320, scale: 2);
      expect(tester.takeException(), isNull);
      expect(find.text('Decisions'), findsOneWidget);
    });

    testWidgets('the leave screen opens on Decisions for an approver', (tester) async {
      final api = _Api(objects: {_leavePath: _leaveData()}, lists: const {'/leave-applications': []});
      await _pump(tester, api, LeaveApplicationsScreen(decisionCenter: Scaffold(body: LeaveDecisionCenterPanel(now: _now))));
      expect(find.text('Pending requests'), findsOneWidget);
      await tester.tap(find.text('Mine'));
      await tester.pumpAndSettle();
      expect(find.text('Pending requests'), findsNothing);
    });
  });
}
