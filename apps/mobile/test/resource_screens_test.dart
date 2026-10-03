import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:hrms_mobile/core/auth/permissions.dart';
import 'package:hrms_mobile/core/providers.dart';
import 'package:hrms_mobile/core/resource/resource_screens.dart';
import 'package:hrms_mobile/features/leave/domain/leave_resources.dart';
import 'package:hrms_mobile/features/organisation/domain/org_resources.dart';

import 'support/fake_api_client.dart';
import 'support/fake_auth.dart';

Map<String, dynamic> _dept(String id, String name, {bool active = true, String? branchId, int version = 3}) =>
    {'id': id, 'name': name, 'code': 'D$id', 'branch_id': branchId, 'parent_id': null, 'head_employee_id': null, 'is_active': active, 'version': version};

FakeApiClient _client({List<Map<String, dynamic>>? departments, Map<String, Map<String, dynamic>> objects = const {}}) => FakeApiClient(
      lists: {
        '/departments': departments ?? [_dept('1', 'Engineering', branchId: 'b1'), _dept('2', 'Old Ops', active: false)],
        '/branches': [
          {'id': 'b1', 'name': 'Pune HQ', 'is_active': true}
        ],
        '/employees': const [],
      },
      objects: objects,
    );

Future<void> _pump(WidgetTester tester, FakeApiClient client, List<String> permissions, Widget home) async {
  tester.view.physicalSize = const Size(800, 3000);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
  await tester.pumpWidget(ProviderScope(
    overrides: [apiClientProvider.overrideWithValue(client), fakeAuth(permissions)],
    child: MaterialApp(home: home),
  ));
  await tester.pumpAndSettle();
}

void main() {
  hardDeleteTests();
  weeklyOffTests();
  group('list', () {
    testWidgets('shows active records and hides inactive ones until asked', (tester) async {
      await _pump(tester, _client(), const [], ResourceListScreen(config: departmentResource));
      expect(find.text('Engineering'), findsOneWidget);
      expect(find.text('Old Ops'), findsNothing);
      await tester.tap(find.text('Show inactive (1)'));
      await tester.pumpAndSettle();
      expect(find.text('Old Ops'), findsOneWidget);
      expect(find.text('Inactive'), findsOneWidget);
    });

    testWidgets('the create button needs the manage permission', (tester) async {
      await _pump(tester, _client(), const [], ResourceListScreen(config: departmentResource));
      expect(find.text('New department'), findsNothing);
    });

    testWidgets('create sends only what was filled in — no nulls, no edit-only flag', (tester) async {
      final client = _client();
      await _pump(tester, client, [orgDepartmentManage], ResourceListScreen(config: departmentResource));
      await tester.tap(find.text('New department'));
      await tester.pumpAndSettle();
      await tester.tap(find.widgetWithText(FilledButton, 'Create'));
      await tester.pumpAndSettle();
      expect(find.text('Name is required.'), findsOneWidget);
      expect(client.calls, isEmpty);

      await tester.enterText(find.widgetWithText(TextField, '').first, 'Finance');
      await tester.tap(find.widgetWithText(FilledButton, 'Create'));
      await tester.pumpAndSettle();
      final call = client.calls.single;
      expect(call.method, 'POST');
      expect(call.path, '/departments');
      expect(call.body, {'name': 'Finance'});
    });
  });

  group('detail', () {
    Future<FakeApiClient> pumpDetail(WidgetTester tester, Map<String, dynamic> row, List<String> permissions) async {
      final client = _client(objects: {'/departments/${row['id']}': row});
      await _pump(tester, client, permissions, ResourceDetailScreen(config: departmentResource, initial: row));
      return client;
    }

    testWidgets('shows the fields with related records by name, not id', (tester) async {
      await pumpDetail(tester, _dept('1', 'Engineering', branchId: 'b1'), const []);
      expect(find.text('Pune HQ'), findsOneWidget);
      expect(find.text('Active'), findsOneWidget);
      expect(find.text('Edit'), findsNothing);
    });

    testWidgets('edit sends only the changed field, with the record version', (tester) async {
      final client = await pumpDetail(tester, _dept('1', 'Engineering', branchId: 'b1', version: 7), [orgDepartmentManage]);
      await tester.tap(find.text('Edit'));
      await tester.pumpAndSettle();
      await tester.enterText(find.widgetWithText(TextField, 'Engineering'), 'Platform');
      await tester.tap(find.widgetWithText(FilledButton, 'Save changes'));
      await tester.pumpAndSettle();
      final call = client.calls.single;
      expect(call.method, 'PATCH');
      expect(call.path, '/departments/1');
      expect(call.ifMatch, '7');
      expect(call.body, {'name': 'Platform'});
    });

    testWidgets('saving without a change says so and sends nothing', (tester) async {
      final client = await pumpDetail(tester, _dept('1', 'Engineering', branchId: 'b1'), [orgDepartmentManage]);
      await tester.tap(find.text('Edit'));
      await tester.pumpAndSettle();
      await tester.tap(find.widgetWithText(FilledButton, 'Save changes'));
      await tester.pumpAndSettle();
      expect(find.text('No changes to save.'), findsOneWidget);
      expect(client.calls, isEmpty);
    });

    testWidgets('deactivate is a soft DELETE carrying the version', (tester) async {
      final client = await pumpDetail(tester, _dept('1', 'Engineering', version: 4), [orgDepartmentManage]);
      await tester.tap(find.widgetWithText(OutlinedButton, 'Deactivate'));
      await tester.pumpAndSettle();
      await tester.tap(find.widgetWithText(FilledButton, 'Deactivate'));
      await tester.pumpAndSettle();
      final call = client.calls.single;
      expect(call.method, 'DELETE');
      expect(call.path, '/departments/1');
      expect(call.ifMatch, '4');
    });

    testWidgets('reactivate patches is_active back on', (tester) async {
      final client = await pumpDetail(tester, _dept('2', 'Old Ops', active: false, version: 9), [orgDepartmentManage]);
      expect(find.text('Inactive'), findsOneWidget);
      await tester.tap(find.widgetWithText(OutlinedButton, 'Reactivate'));
      await tester.pumpAndSettle();
      await tester.tap(find.widgetWithText(FilledButton, 'Reactivate'));
      await tester.pumpAndSettle();
      final call = client.calls.single;
      expect(call.method, 'PATCH');
      expect(call.body, {'is_active': true});
      expect(call.ifMatch, '9');
    });
  });
}

// ---- weekly-off patterns (rows + integer selects) --------------------------------------------

void weeklyOffTests() {
  testWidgets('a pattern shows its rules, and edits send the whole rule list with integer weekdays', (tester) async {
    tester.view.physicalSize = const Size(800, 5000);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.reset);
    final row = {
      'id': 'w1',
      'name': 'Sat-Sun',
      'code': 'SS',
      'pattern_kind': 'FIXED_WEEKDAYS',
      'is_active': true,
      'version': 2,
      'rules': [
        {'id': 'r1', 'weekday': 5, 'nth_in_month': null, 'cycle_start_date': null, 'off_fraction': '1.00', 'week_parity': null},
        {'id': 'r2', 'weekday': 6, 'nth_in_month': null, 'cycle_start_date': null, 'off_fraction': '1.00', 'week_parity': null},
      ],
    };
    final client = FakeApiClient(objects: {'/weekly-off-patterns/w1': row});
    await tester.pumpWidget(ProviderScope(
      overrides: [apiClientProvider.overrideWithValue(client), fakeAuth([orgCalendarManage])],
      child: MaterialApp(home: ResourceDetailScreen(config: weeklyOffPatternResource, initial: row)),
    ));
    await tester.pumpAndSettle();
    expect(find.text('Rules (2)'), findsOneWidget);
    expect(find.textContaining('Weekday: Saturday'), findsOneWidget);
    expect(find.textContaining('Day off: Full day'), findsNWidgets(2));

    await tester.tap(find.text('Edit'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Add rule'));
    await tester.pumpAndSettle();
    expect(find.text('Rule 3'), findsOneWidget);
    // change the new rule's weekday: the new rule defaults to Sunday (6); pick Friday
    // dropdown order: pattern kind, then four per rule (weekday, which, day off, parity)
    final weekday = find.byType(DropdownButtonFormField<String>).at(1 + 4 * 2);
    await tester.ensureVisible(weekday);
    await tester.pumpAndSettle();
    await tester.tap(weekday);
    await tester.pumpAndSettle();
    await tester.tap(find.text('Friday').last);
    await tester.pumpAndSettle();
    await tester.drag(find.byType(ListView).last, const Offset(0, -20000));
    await tester.pumpAndSettle();
    await tester.tap(find.widgetWithText(FilledButton, 'Save changes'));
    await tester.pumpAndSettle();
    final call = client.calls.single;
    expect(call.method, 'PATCH');
    expect(call.ifMatch, '2');
    final rules = (call.body as Map)['rules'] as List;
    expect(rules.length, 3);
    expect(rules.map((r) => r['weekday']), [5, 6, 4]); // integers, in order
    expect(rules.last['off_fraction'], '1.00');
  });
}

// ---- create-and-delete-only records (hard delete, no edit) ------------------------------------

void hardDeleteTests() {
  testWidgets('a combination rule offers Delete — not Edit or Deactivate — and removes it', (tester) async {
    tester.view.physicalSize = const Size(800, 3000);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.reset);
    final row = {'id': 'c1', 'leave_type_id_a': 'a', 'leave_type_id_b': 'b', 'allowed': false, 'reason': 'Clash', 'version': null};
    final client = FakeApiClient(
      lists: {
        '/leave-types': [
          {'id': 'a', 'name': 'Casual', 'is_active': true},
          {'id': 'b', 'name': 'Sick', 'is_active': true},
        ],
      },
      objects: {'/leave-combination-rules/c1': row},
    );
    await tester.pumpWidget(ProviderScope(
      overrides: [apiClientProvider.overrideWithValue(client), fakeAuth(['LEAVE.COMBINATION_RULE_MANAGE'])],
      child: MaterialApp(home: ResourceDetailScreen(config: leaveCombinationRuleResource, initial: row)),
    ));
    await tester.pumpAndSettle();
    expect(find.text('Casual'), findsOneWidget);
    expect(find.text('Sick'), findsOneWidget);
    expect(find.text('Edit'), findsNothing);
    expect(find.text('Deactivate'), findsNothing);
    await tester.tap(find.widgetWithText(OutlinedButton, 'Delete'));
    await tester.pumpAndSettle();
    await tester.tap(find.widgetWithText(FilledButton, 'Delete'));
    await tester.pumpAndSettle();
    final call = client.calls.single;
    expect(call.method, 'DELETE');
    expect(call.path, '/leave-combination-rules/c1');
  });
}
