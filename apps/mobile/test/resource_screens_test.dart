import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:hrms_mobile/core/auth/permissions.dart';
import 'package:hrms_mobile/core/providers.dart';
import 'package:hrms_mobile/core/resource/resource_screens.dart';
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
