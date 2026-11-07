import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:hrms_mobile/core/api/api_error.dart';
import 'package:hrms_mobile/core/api/envelope.dart';
import 'package:hrms_mobile/core/auth/permissions.dart';
import 'package:hrms_mobile/core/providers.dart';
import 'package:hrms_mobile/core/resource/resource_screens.dart';
import 'package:hrms_mobile/features/attendance/domain/policy_resources.dart';
import 'package:hrms_mobile/features/attendance/presentation/shift_delete_screen.dart';

import 'support/fake_api_client.dart';
import 'support/fake_auth.dart';

const _shift = {'id': 's1', 'name': 'Night A', 'code': 'NA', 'version': 7, 'is_active': true};
const _checkPath = '/shifts/s1/deletion-check';
const _deletePath = '/shifts/s1/delete';

/// Hosts the delete screen and records what it resolved with.
Future<List<bool?>> _open(WidgetTester tester, FakeApiClient api) async {
  tester.view.physicalSize = const Size(800, 1600);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
  final results = <bool?>[];
  await tester.pumpWidget(ProviderScope(
    overrides: [apiClientProvider.overrideWithValue(api)],
    child: MaterialApp(
      home: Builder(builder: (context) => TextButton(onPressed: () async => results.add(await openShiftDelete(context, _shift)), child: const Text('open'))),
    ),
  ));
  await tester.tap(find.text('open'));
  await tester.pumpAndSettle();
  return results;
}

FilledButton _deleteButton(WidgetTester tester) => tester.widget<FilledButton>(find.widgetWithText(FilledButton, 'Delete permanently'));

Future<void> _fill(WidgetTester tester, {String name = 'Night A', String reason = 'Created by mistake', bool ack = true}) async {
  await tester.enterText(find.widgetWithText(TextField, 'Type “Night A” to confirm'), name);
  await tester.enterText(find.widgetWithText(TextField, 'Reason for deletion'), reason);
  if (ack) await tester.tap(find.text('I understand this cannot be undone from the app.'));
  await tester.pumpAndSettle();
}

ApiError _conflict(String code, [List<ErrorDetail> details = const []]) => ApiError(status: 409, code: code, message: 'conflict', details: details);

void main() {
  testWidgets('a shift in use lists the blockers and cannot be deleted', (tester) async {
    await _open(tester, FakeApiClient(objects: {
      _checkPath: {
        'can_delete': false,
        'blockers': [
          {'code': 'ASSIGNED', 'message': 'Assigned to 3 employees.', 'count': 3},
          {'code': 'ROSTERED', 'message': 'Used in 12 roster entries.', 'count': 12},
        ],
        'published_version_count': 1,
        'draft_version_count': 0,
      },
    }));
    expect(find.text('This shift can’t be deleted yet'), findsOneWidget);
    expect(find.text('• Assigned to 3 employees.'), findsOneWidget);
    expect(find.text('• Used in 12 roster entries.'), findsOneWidget);
    expect(find.byType(TextField), findsNothing);
    expect(_deleteButton(tester).onPressed, isNull);
  });

  testWidgets('every safeguard must be met before Delete is enabled; then it posts with If-Match', (tester) async {
    final api = FakeApiClient(objects: {
      _checkPath: {'can_delete': true, 'blockers': [], 'published_version_count': 2, 'draft_version_count': 1},
    });
    final results = await _open(tester, api);
    expect(find.textContaining('2 published schedule version(s) and 1 draft(s) will be removed with it.'), findsOneWidget);

    await _fill(tester, name: 'night a');
    expect(_deleteButton(tester).onPressed, isNull, reason: 'the name must match exactly');
    await tester.enterText(find.widgetWithText(TextField, 'Type “Night A” to confirm'), 'Night A');
    await tester.enterText(find.widgetWithText(TextField, 'Reason for deletion'), 'too short');
    await tester.pumpAndSettle();
    expect(_deleteButton(tester).onPressed, isNull, reason: 'the reason needs 10 characters');
    await tester.enterText(find.widgetWithText(TextField, 'Reason for deletion'), '  Created by mistake  ');
    await tester.pumpAndSettle();
    expect(_deleteButton(tester).onPressed, isNotNull);

    await tester.tap(find.text('Delete permanently'));
    await tester.pumpAndSettle();
    final call = api.calls.single;
    expect((call.method, call.path, call.ifMatch), ('POST', _deletePath, '7'));
    expect(call.body, {'confirm_name': 'Night A', 'reason': 'Created by mistake', 'acknowledge_irreversible': true});
    expect(results, [true]);
  });

  testWidgets('without the acknowledgement Delete stays disabled', (tester) async {
    await _open(tester, FakeApiClient(objects: {_checkPath: {'can_delete': true, 'blockers': []}}));
    await _fill(tester, ack: false);
    expect(_deleteButton(tester).onPressed, isNull);
  });

  testWidgets('if the shift was put to use meanwhile, the new blockers replace the form', (tester) async {
    final api = FakeApiClient(
      objects: {_checkPath: {'can_delete': true, 'blockers': []}},
      failing: {_deletePath: _conflict('SHIFT_DELETE_BLOCKED', [ErrorDetail(code: 'ASSIGNED', message: 'Assigned to 1 employee.')])},
    );
    final results = await _open(tester, api);
    await _fill(tester);
    await tester.tap(find.text('Delete permanently'));
    await tester.pumpAndSettle();
    expect(find.text('• Assigned to 1 employee.'), findsOneWidget);
    expect(find.byType(TextField), findsNothing);
    expect(results, isEmpty, reason: 'the screen stays open');
  });

  testWidgets('a stale shift closes the screen so the detail reloads', (tester) async {
    final api = FakeApiClient(objects: {_checkPath: {'can_delete': true, 'blockers': []}}, failing: {_deletePath: _conflict('STALE_RESOURCE')});
    final results = await _open(tester, api);
    await _fill(tester);
    await tester.tap(find.text('Delete permanently'));
    await tester.pumpAndSettle();
    expect(results, [false]);
  });

  testWidgets('a failed check says so', (tester) async {
    await _open(tester, FakeApiClient(failing: {_checkPath: ApiError(status: 403, code: 'FORBIDDEN', message: 'Not allowed.')}));
    expect(find.text('Not allowed.'), findsOneWidget);
    expect(_deleteButton(tester).onPressed, isNull);
  });

  group('on the shift detail', () {
    Future<void> detail(WidgetTester tester, List<String> perms) async {
      tester.view.physicalSize = const Size(800, 2400);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.reset);
      await tester.pumpWidget(ProviderScope(
        overrides: [
          apiClientProvider.overrideWithValue(FakeApiClient(objects: {'/shifts/s1': _shift, _checkPath: {'can_delete': true, 'blockers': []}})),
          fakeAuth(perms),
        ],
        child: MaterialApp(home: ResourceDetailScreen(config: shiftResource(), initial: _shift)),
      ));
      await tester.pumpAndSettle();
    }

    testWidgets('a shift manager gets Delete, which opens the guarded delete', (tester) async {
      await detail(tester, const [orgShiftManage]);
      await tester.tap(find.widgetWithText(OutlinedButton, 'Delete'));
      await tester.pumpAndSettle();
      expect(find.text('Delete shift “Night A”?'), findsOneWidget);
    });

    testWidgets('without the shift grant there is no Delete', (tester) async {
      await detail(tester, const []);
      expect(find.widgetWithText(OutlinedButton, 'Delete'), findsNothing);
    });
  });
}
