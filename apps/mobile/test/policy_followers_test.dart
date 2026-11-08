import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:hrms_mobile/core/auth/permissions.dart';
import 'package:hrms_mobile/core/nav/nav_entries.dart';
import 'package:hrms_mobile/core/providers.dart';
import 'package:hrms_mobile/core/time.dart';
import 'package:hrms_mobile/features/attendance/domain/policy_followers.dart';
import 'package:hrms_mobile/features/attendance/presentation/policy_followers_section.dart';

import 'support/fake_api_client.dart';
import 'support/fake_auth.dart';

/// "Who follows this" on a policy — web `policy-followers-panel.tsx` and `assign-policy-dialog.tsx`.

final _today = businessToday('Asia/Kolkata');

Map<String, dynamic> _a(String id, String scopeType, String? scopeId, {String from = '2026-01-01', String? to, bool active = true}) => {
      'id': id,
      'version': 1,
      'policy_kind': 'ATTENDANCE_POLICY',
      'policy_id': 'p-1',
      'scope_type': scopeType,
      'scope_id': scopeId,
      'effective_from': from,
      'effective_to': to,
      'is_active': active,
    };

const _policy = {'id': 'p-1', 'name': 'Standard', 'is_active': true, 'version': 3};
const _published = [
  {'id': 'v-1', 'status': 'PUBLISHED', 'effective_to': null},
];

Future<FakeApiClient> _pump(
  WidgetTester tester, {
  List<Map<String, dynamic>> followers = const [],
  List<Map<String, dynamic>> versions = _published,
  Map<String, dynamic> policy = _policy,
  String kind = 'ATTENDANCE_POLICY',
  List<String> permissions = const [attendancePolicyManage],
  Map<String, Map<String, dynamic>> objects = const {},
}) async {
  tester.view.physicalSize = const Size(420, 2400);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
  final api = FakeApiClient(lists: {
    '/policy-assignments': followers,
    '/attendance-policies/p-1/versions': versions,
    '/branches': [
      {'id': 'b-1', 'name': 'Pune'},
      {'id': 'b-2', 'name': 'Goa'},
    ],
  }, objects: {
    '/employees/e-1': {'id': 'e-1', 'first_name': 'Asha', 'middle_name': 'K', 'last_name': 'Rao'},
    ...objects,
  });
  await tester.pumpWidget(ProviderScope(
    overrides: [apiClientProvider.overrideWithValue(api), fakeAuth(permissions)],
    child: MaterialApp(
      home: Scaffold(
        body: ListView(padding: const EdgeInsets.all(16), children: [
          PolicyFollowersSection(
            kind: kind,
            policy: policy,
            manage: kind == 'WORK_CALENDAR' ? orgCalendarManage : attendancePolicyManage,
            versionsPath: kind == 'WORK_CALENDAR' ? null : '/attendance-policies/p-1/versions',
          ),
        ]),
      ),
    ),
  ));
  await tester.pumpAndSettle();
  return api;
}

void main() {
  group('rules', () {
    test('live followers: ended ones dropped, widest scope first, then by start', () {
      final rows = liveFollowers([
        _a('1', 'EMPLOYEE', 'e-1'),
        _a('2', 'BRANCH', 'b-2', from: '2026-03-01'),
        _a('3', 'COMPANY', null),
        _a('4', 'BRANCH', 'b-1'),
        _a('5', 'DEPARTMENT', 'd-1', to: '2020-01-01'),
        _a('6', 'GRADE', 'g-1', active: false),
      ], '2026-06-01');
      expect(rows.map((r) => r['id']), ['3', '4', '2', '1']);
    });

    test('permissions per kind match the server', () {
      expect(assignmentPermissionsFor('WEEKLY_OFF'), [orgCalendarManage]);
      expect(assignmentPermissionsFor('OVERTIME_POLICY'), [attendancePolicyManage]);
      expect(assignmentPermissionsFor('LEAVE_POLICY'), [orgCalendarManage, attendancePolicyManage]);
    });

    test('why nobody new can follow it', () {
      expect(cannotAssignReason(kind: 'WORK_CALENDAR', isActive: false, hasPublishedRules: true), startsWith('This calendar is inactive'));
      expect(cannotAssignReason(kind: 'LEAVE_POLICY', isActive: true, hasPublishedRules: false), startsWith('Publish the rules first'));
      expect(cannotAssignReason(kind: 'WEEKLY_OFF', isActive: true, hasPublishedRules: false), isNull, reason: 'calendars have no versions');
    });

    test('the add checks match web', () {
      expect(assignError(own: null, policyId: 'p-1', effectiveFrom: '2026-01-01'), isNull);
      expect(assignError(own: {'policy_id': 'p-1', 'effective_from': '2026-01-01'}, policyId: 'p-1', effectiveFrom: '2026-05-01'), 'They already follow this policy.');
      expect(assignError(own: {'policy_id': 'p-9', 'effective_from': '2026-05-01'}, policyId: 'p-1', effectiveFrom: '2026-05-01'), startsWith('Must be after 1 May 2026'));
    });
  });

  group('section', () {
    testWidgets('lists who follows it with names, and End only where it can be ended', (tester) async {
      final api = await _pump(tester, followers: [
        _a('c', 'COMPANY', null),
        _a('b', 'BRANCH', 'b-1'),
        _a('e', 'EMPLOYEE', 'e-1', from: '2099-01-01'),
      ]);
      final call = api.listCalls.firstWhere((c) => c.path == '/policy-assignments');
      expect(call.filters, {'policy_kind': 'ATTENDANCE_POLICY', 'policy_id': 'p-1'});
      expect(find.text('Whole company'), findsOneWidget);
      expect(find.text('Branch: Pune'), findsOneWidget);
      expect(find.text('Employee: Asha K Rao'), findsOneWidget);
      expect(find.text('Starts later'), findsOneWidget);
      expect(find.text('End'), findsNWidgets(2), reason: 'the whole-company row is the fallback');
      expect(find.textContaining("can't be ended here"), findsOneWidget);
    });

    testWidgets('empty: says so and offers to add', (tester) async {
      await _pump(tester);
      expect(find.text('Nobody follows this policy yet'), findsOneWidget);
      expect(find.text('Add who follows it'), findsOneWidget);
    });

    testWidgets('no published rules: explains, no add button', (tester) async {
      await _pump(tester, versions: const [
        {'id': 'v-1', 'status': 'DRAFT', 'effective_to': null},
      ]);
      expect(find.textContaining('Publish the rules first'), findsOneWidget);
      expect(find.text('Add who follows it'), findsNothing);
    });

    testWidgets('without the assignment permission: read only', (tester) async {
      await _pump(tester, followers: [_a('b', 'BRANCH', 'b-1')], permissions: const [attendanceView]);
      expect(find.text('Branch: Pune'), findsOneWidget);
      expect(find.text('End'), findsNothing);
      expect(find.text('Add who follows it'), findsNothing);
    });

    testWidgets('adding a branch saves through the batch, replacing what it follows now', (tester) async {
      final api = await _pump(tester, objects: {
        '/policy-assignments/coverage': {
          'rows': [
            {'policy_kind': 'ATTENDANCE_POLICY', 'own': {'policy_id': 'p-9', 'version': 7, 'effective_from': '2020-01-01'}},
          ],
        },
      });
      await tester.tap(find.text('Add who follows it'));
      await tester.pumpAndSettle();
      expect(find.text('Add who follows Standard'), findsOneWidget);
      await tester.tap(find.byType(DropdownButtonFormField<String>).at(1));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Pune').last);
      await tester.pumpAndSettle();
      await tester.tap(find.text('Assign'));
      await tester.pumpAndSettle();
      final post = api.calls.singleWhere((c) => c.path == '/policy-assignments/batch');
      expect(post.body['scope_type'], 'BRANCH');
      expect(post.body['scope_id'], 'b-1');
      expect(post.body['effective_from'], _today);
      expect(post.body['changes'], [
        {'policy_kind': 'ATTENDANCE_POLICY', 'policy_id': 'p-1', 'leave_type_id': null, 'expected_version': 7},
      ]);
    });

    testWidgets('a group that already follows it is refused, nothing is saved', (tester) async {
      final api = await _pump(tester, objects: {
        '/policy-assignments/coverage': {
          'rows': [
            {'policy_kind': 'ATTENDANCE_POLICY', 'own': {'policy_id': 'p-1', 'version': 2, 'effective_from': '2020-01-01'}},
          ],
        },
      });
      await tester.tap(find.text('Add who follows it'));
      await tester.pumpAndSettle();
      await tester.tap(find.byType(DropdownButtonFormField<String>).at(1));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Pune').last);
      await tester.pumpAndSettle();
      await tester.tap(find.text('Assign'));
      await tester.pumpAndSettle();
      expect(find.text('They already follow this policy.'), findsOneWidget);
      expect(api.calls, isEmpty);
    });

    testWidgets('a work calendar previews instead of saving, and is never ended here', (tester) async {
      await _pump(tester, kind: 'WORK_CALENDAR', permissions: const [orgCalendarManage], followers: [
        {..._a('b', 'BRANCH', 'b-1'), 'policy_kind': 'WORK_CALENDAR'},
      ]);
      expect(find.text('End'), findsNothing);
      expect(find.textContaining('Calendar changes are replaced rather than ended'), findsOneWidget);
      await tester.tap(find.text('Add who follows it'));
      await tester.pumpAndSettle();
      expect(find.text('Preview changes'), findsOneWidget);
    });
  });

  test("the settings menu follows web's sections and names", () {
    final all = visibleNavGroups(const [
      orgCompanyManage, orgLegalEntityManage, orgBranchManage, orgDepartmentManage, orgDesignationManage, orgGradeManage, //
      orgShiftManage, orgCalendarManage, orgHolidayManage, attendancePolicyManage, attendanceLock, attendanceView, attendanceRosterManage,
      leaveTypeManage, leavePolicyManage, leaveYearSettingManage, leaveCombinationRuleManage, leaveStatutoryMinimumManage,
      settingsUserManage,
    ], payroll: false);
    final settings = all.skip(1).map((g) => g.label).toList();
    expect(settings, ['Company', 'People structure', 'When people work', 'Where people punch', 'Attendance rules', 'Closing the month', 'Leave types and rules', 'Access & setup', 'Who follows what']);
    final labels = [for (final g in all) for (final e in g.items) e.label];
    expect(labels, containsAll(['Correction Policies', 'Rules by Group', "Check a Person's Rules"]));
    expect(labels, isNot(contains('Policy Assignments')));
  });
}
