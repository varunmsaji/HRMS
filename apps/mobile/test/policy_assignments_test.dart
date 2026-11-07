import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:hrms_mobile/core/forms/form_spec.dart';
import 'package:hrms_mobile/core/providers.dart';
import 'package:hrms_mobile/features/attendance/domain/policy_assignment_form.dart';
import 'package:hrms_mobile/features/attendance/presentation/policy_assignments_screen.dart';

import 'support/fake_api_client.dart';
import 'support/fake_auth.dart';

Map<String, dynamic> _assignment({String id = 'a1', String kind = 'ATTENDANCE_POLICY', String scope = 'BRANCH', String? scopeId = 'b1', String policyId = 'ap1', String? to, int version = 4}) => {
      'id': id,
      'policy_kind': kind,
      'policy_id': policyId,
      'leave_type_id': null,
      'scope_type': scope,
      'scope_id': scopeId,
      'effective_from': '2026-04-01',
      'effective_to': to,
      'priority': 0,
      'reason': 'Annual review',
      'version': version,
    };

FakeApiClient _api(List<Map<String, dynamic>> rows) => FakeApiClient(lists: {
      '/policy-assignments': rows,
      '/attendance-policies': [
        {'id': 'ap1', 'name': 'Standard attendance', 'is_active': true},
        {'id': 'ap2', 'name': 'Strict attendance', 'is_active': true},
      ],
      '/overtime-policies': [
        {'id': 'op1', 'name': 'OT 2x', 'is_active': true}
      ],
      '/regularization-policies': const [],
      '/leave-policies': [
        {'id': 'lp1', 'name': 'Casual policy', 'is_active': true}
      ],
      '/work-calendars': const [],
      '/weekly-off-patterns': const [],
      '/leave-types': [
        {'id': 'lt1', 'name': 'Casual Leave', 'is_active': true}
      ],
      '/legal-entities': const [],
      '/branches': [
        {'id': 'b1', 'name': 'Pune HQ', 'is_active': true},
        {'id': 'b2', 'name': 'Mumbai', 'is_active': true},
      ],
      '/departments': const [],
      '/grades': const [],
      '/designations': const [],
      '/shifts': const [],
      '/employees': const [],
    });

Future<void> _pump(WidgetTester tester, FakeApiClient api) async {
  tester.view.physicalSize = const Size(800, 5000);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
  await tester.pumpWidget(ProviderScope(overrides: [apiClientProvider.overrideWithValue(api), fakeAuth(const [])], child: const MaterialApp(home: PolicyAssignmentsScreen())));
  await tester.pumpAndSettle();
  // The screen opens on "Set policies", as on web; these tests are about the list.
  await tester.tap(find.text('All assignments'));
  await tester.pumpAndSettle();
}

Future<void> _choose(WidgetTester tester, int dropdownIndex, String label) async {
  final dd = find.byType(DropdownButtonFormField<String>).at(dropdownIndex);
  await tester.ensureVisible(dd);
  await tester.pumpAndSettle();
  await tester.tap(dd);
  await tester.pumpAndSettle();
  await tester.tap(find.text(label).last);
  await tester.pumpAndSettle();
}

void main() {
  group('form logic', () {
    final spec = policyAssignmentSpec;
    Map<String, dynamic> v(Map<String, dynamic> over) => rowFromWire(spec, {'policy_kind': 'ATTENDANCE_POLICY', 'policy_id': 'p', 'scope_type': 'COMPANY', 'effective_from': '2026-10-01', ...over});

    test('a company-wide assignment needs no target', () => expect(validateRow(spec, v({})), isEmpty));

    test('any other scope needs its target', () {
      expect(validateRow(spec, v({'scope_type': 'BRANCH', 'scope_id': ''})).keys, ['scope_id']);
      expect(validateRow(spec, v({'scope_type': 'BRANCH', 'scope_id': 'b1'})), isEmpty);
    });

    test('a leave policy also needs its leave type, other kinds do not', () {
      expect(validateRow(spec, v({'policy_kind': 'LEAVE_POLICY', 'leave_type_id': ''})).keys, ['leave_type_id']);
      expect(validateRow(spec, v({'policy_kind': 'LEAVE_POLICY', 'leave_type_id': 'lt1'})), isEmpty);
    });

    test('a hidden target is not sent', () {
      final p = rowToPayload(spec, v({'scope_id': 'stale'}));
      expect(p['scope_id'], isNull);
      expect(p['leave_type_id'], isNull);
    });
  });

  testWidgets('lists assignments with names, not ids', (tester) async {
    await _pump(tester, _api([_assignment(), _assignment(id: 'a2', to: '2026-03-31', policyId: 'ap2', scope: 'COMPANY', scopeId: null)]));
    expect(find.text('Attendance Policy → Branch: Pune HQ'), findsOneWidget);
    expect(find.textContaining('Standard attendance'), findsOneWidget);
    expect(find.text('Current'), findsOneWidget);
    expect(find.text('Ended 2026-03-31'), findsOneWidget);
    expect(find.text('Attendance Policy → Whole company'), findsOneWidget);
  });

  testWidgets('the kind filter is sent to the server', (tester) async {
    final api = _api([_assignment()]);
    await _pump(tester, api);
    await tester.tap(find.byType(DropdownButtonFormField<String>).first);
    await tester.pumpAndSettle();
    await tester.tap(find.text('Overtime Policy').last);
    await tester.pumpAndSettle();
    expect(api.listCalls.where((c) => c.path == '/policy-assignments').last.filters!['policy_kind'], 'OVERTIME_POLICY');
  });

  testWidgets('the policy picker follows the kind, and changing the kind clears a stale choice', (tester) async {
    final api = _api(const []);
    await _pump(tester, api);
    await tester.tap(find.text('New assignment'));
    await tester.pumpAndSettle();
    // dropdowns: kind, policy, scope  (target is hidden while the scope is the whole company)
    await _choose(tester, 1, 'Standard attendance');
    await _choose(tester, 0, 'Overtime Policy');
    // the stale attendance policy is gone and the overtime policies are offered instead
    await tester.tap(find.widgetWithText(FilledButton, 'Create'));
    await tester.pumpAndSettle();
    expect(find.text('Policy is required.'), findsOneWidget);
    await _choose(tester, 1, 'OT 2x');
    expect(find.text('OT 2x'), findsWidgets);
  });

  testWidgets('creating posts the assignment; no If-Match when nothing is open at that scope', (tester) async {
    final api = _api(const []);
    await _pump(tester, api);
    await tester.tap(find.text('New assignment'));
    await tester.pumpAndSettle();
    await _choose(tester, 1, 'Standard attendance');
    await tester.tap(find.widgetWithText(TextField, '').first);
    await tester.pumpAndSettle();
    await tester.tap(find.text('OK'));
    await tester.pumpAndSettle();
    await tester.tap(find.widgetWithText(FilledButton, 'Create'));
    await tester.pumpAndSettle();
    final call = api.calls.single;
    expect(call.path, '/policy-assignments');
    expect(call.ifMatch, isNull);
    final body = call.body as Map<String, dynamic>;
    expect(body['policy_kind'], 'ATTENDANCE_POLICY');
    expect(body['policy_id'], 'ap1');
    expect(body['scope_type'], 'COMPANY');
    expect(body.containsKey('scope_id'), isFalse);
  });

  testWidgets('replacing an open assignment at the same scope sends that assignment\'s version', (tester) async {
    final api = _api([_assignment(scope: 'COMPANY', scopeId: null, version: 9)]);
    await _pump(tester, api);
    await tester.tap(find.text('New assignment'));
    await tester.pumpAndSettle();
    await _choose(tester, 1, 'Strict attendance');
    await tester.tap(find.widgetWithText(TextField, '').first);
    await tester.pumpAndSettle();
    await tester.tap(find.text('OK'));
    await tester.pumpAndSettle();
    await tester.tap(find.widgetWithText(FilledButton, 'Create'));
    await tester.pumpAndSettle();
    final call = api.calls.single;
    expect(call.ifMatch, '9');
    expect((call.body as Map)['policy_id'], 'ap2');
  });

  testWidgets('the policy picker asks only for assignable policies, names still come from all', (tester) async {
    final api = _api([_assignment()]);
    await _pump(tester, api);
    expect(api.listCalls.any((c) => c.path == '/attendance-policies' && c.filters == null), isTrue);
    await tester.tap(find.text('New assignment'));
    await tester.pumpAndSettle();
    final asked = api.listCalls.where((c) => c.path == '/attendance-policies' && c.filters?['assignable'] == 'true');
    expect(asked, isNotEmpty);
  });

  testWidgets('ending a current group assignment sends its version and the last day', (tester) async {
    final api = _api([_assignment()]);
    await _pump(tester, api);
    await tester.tap(find.text('Attendance Policy → Branch: Pune HQ'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('OK'));
    await tester.pumpAndSettle();
    await tester.tap(find.widgetWithText(FilledButton, 'End assignment'));
    await tester.pumpAndSettle();
    final call = api.calls.single;
    expect(call.path, '/policy-assignments/a1/end');
    expect(call.ifMatch, '4');
    expect((call.body as Map)['effective_to'], matches(RegExp(r'^\d{4}-\d{2}-\d{2}$')));
  });

  testWidgets('the company-wide and ended assignments cannot be ended', (tester) async {
    final api = _api([_assignment(scope: 'COMPANY', scopeId: null), _assignment(id: 'a2', to: '2026-03-31')]);
    await _pump(tester, api);
    await tester.tap(find.text('Attendance Policy → Whole company'));
    await tester.pumpAndSettle();
    expect(find.text('OK'), findsNothing);
    await tester.tap(find.textContaining('Ended 2026-03-31'));
    await tester.pumpAndSettle();
    expect(find.text('OK'), findsNothing);
    expect(api.calls, isEmpty);
  });
}
