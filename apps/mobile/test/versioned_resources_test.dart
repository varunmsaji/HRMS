import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:hrms_mobile/core/auth/permissions.dart';
import 'package:hrms_mobile/core/providers.dart';
import 'package:hrms_mobile/core/resource/resource_screens.dart';
import 'package:hrms_mobile/features/attendance/domain/policy_resources.dart';

import 'support/fake_api_client.dart';
import 'support/fake_auth.dart';

Map<String, dynamic> _version(int n, {String status = 'PUBLISHED', String? effectiveTo, int rowVersion = 2}) => {
      'id': 'v$n',
      'version': rowVersion,
      'status': status,
      'effective_from': '2026-0$n-01',
      'effective_to': effectiveTo,
      'grace_in_minutes': 10,
      'grace_out_minutes': 5,
      'punch_rounding': 'NONE',
      'missing_punch_behaviour': 'INCOMPLETE',
      'auto_close_uses_shift_end': true,
      'missing_shift_behaviour': 'INCOMPLETE',
      'half_day_split': 'BY_HOURS',
      'multi_punch_mode': 'PAIR_ALL',
      'duplicate_punch_window_seconds': 60,
      'core_hours_breach_behaviour': 'FLAG',
      'early_out_uses_core_end': false,
      'split_shift_block_mandatory': true,
      'split_shift_missed_block_behaviour': 'HALF_DAY',
      'split_shift_allow_hours_compensation': false,
      'wfh_requires_punch': true,
      'on_duty_requires_punch': false,
      'wfh_uses_shift_hours': true,
      'work_on_leave_behaviour': 'KEEP_LEAVE',
      'excess_break_behaviour': 'FLAG',
      'late_count_window': 'MONTH',
      'early_departure_requires_approval': false,
      'excess_break_count_window': 'MONTH',
      'incomplete_at_lock_behaviour': 'TREAT_ABSENT',
      'hour_bands': [
        {'min_minutes': 0, 'max_minutes': 240, 'result_status': 'ABSENT', 'sort_order': 0},
        {'min_minutes': 240, 'max_minutes': null, 'result_status': 'PRESENT', 'sort_order': 1},
      ],
      'late_bands': <dynamic>[],
      'early_departure_bands': <dynamic>[],
      'publish_reason': null,
    };

const _policy = {'id': 'p1', 'name': 'Standard', 'code': 'STD', 'is_active': true, 'version': 4};

Future<FakeApiClient> _pump(WidgetTester tester, List<Map<String, dynamic>> versions, List<String> permissions, {Map<String, Map<String, dynamic>> objects = const {}}) async {
  tester.view.physicalSize = const Size(800, 9000);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
  final client = FakeApiClient(lists: {'/attendance-policies/p1/versions': versions}, objects: {'/attendance-policies/p1': _policy, ...objects});
  await tester.pumpWidget(ProviderScope(
    overrides: [apiClientProvider.overrideWithValue(client), fakeAuth(permissions)],
    child: MaterialApp(home: ResourceDetailScreen(config: attendancePolicyResource, initial: _policy)),
  ));
  await tester.pumpAndSettle();
  return client;
}

void main() {
  testWidgets('shows versions newest first, labelled draft / current / past', (tester) async {
    await _pump(tester, [_version(1, effectiveTo: '2026-02-01'), _version(2), _version(3, status: 'DRAFT')], const []);
    expect(find.text('v2'), findsNWidgets(3)); // every row version here is 2
    expect(find.text('Draft'), findsOneWidget);
    expect(find.text('Current'), findsOneWidget);
    expect(find.text('Past'), findsOneWidget);
  });

  testWidgets('without the manage permission there are no draft actions', (tester) async {
    await _pump(tester, [_version(1)], const []);
    expect(find.text('Create draft'), findsNothing);
    expect(find.text('Edit'), findsNothing);
  });

  testWidgets('a version expands to every field and nested band', (tester) async {
    await _pump(tester, [_version(1)], const []);
    await tester.tap(find.text('v2'));
    await tester.pumpAndSettle();
    expect(find.text('Grace in (minutes)'), findsOneWidget);
    expect(find.text('Worked-hours bands (2)'), findsOneWidget);
    expect(find.textContaining('Result: Absent'), findsOneWidget);
  });

  testWidgets('create draft posts an empty body (the server seeds it) and opens the editor', (tester) async {
    final client = await _pump(tester, [_version(1)], [attendancePolicyManage], objects: {'/attendance-policies/p1/versions': _version(2, status: 'DRAFT', rowVersion: 1)});
    await tester.tap(find.text('Create draft'));
    await tester.pumpAndSettle();
    final call = client.calls.first;
    expect(call.method, 'POST');
    expect(call.path, '/attendance-policies/p1/versions');
    expect(call.body, isEmpty);
    expect(find.text('Edit draft'), findsWidgets); // the editor opened
  });

  testWidgets('edit draft sends only the changed field with the draft version', (tester) async {
    final client = await _pump(tester, [_version(1), _version(2, status: 'DRAFT', rowVersion: 6)], [attendancePolicyManage]);
    await tester.tap(find.widgetWithText(FilledButton, 'Edit draft'));
    await tester.pumpAndSettle();
    await tester.enterText(find.widgetWithText(TextField, '10'), '15');
    await tester.drag(find.byType(ListView).last, const Offset(0, -20000));
    await tester.pumpAndSettle();
    await tester.tap(find.widgetWithText(FilledButton, 'Save changes'));
    await tester.pumpAndSettle();
    final call = client.calls.single;
    expect(call.method, 'PATCH');
    expect(call.path, '/attendance-policies/p1/versions/v2');
    expect(call.ifMatch, '6');
    expect(call.body, {'grace_in_minutes': 15});
  });

  testWidgets('publish asks for an optional reason and carries the draft version', (tester) async {
    final client = await _pump(tester, [_version(1), _version(2, status: 'DRAFT', rowVersion: 3)], [attendancePolicyManage]);
    await tester.tap(find.widgetWithText(FilledButton, 'Publish'));
    await tester.pumpAndSettle();
    expect(find.textContaining('closes the version currently effective'), findsOneWidget);
    await tester.enterText(find.byType(TextField).last, 'Annual review');
    await tester.tap(find.widgetWithText(FilledButton, 'Publish').last);
    await tester.pumpAndSettle();
    final call = client.calls.single;
    expect(call.path, '/attendance-policies/p1/versions/v2/publish');
    expect(call.ifMatch, '3');
    expect(call.body, {'publish_reason': 'Annual review'});
  });

  testWidgets('discarding a draft deletes it with its version after confirming', (tester) async {
    final client = await _pump(tester, [_version(1), _version(2, status: 'DRAFT', rowVersion: 8)], [attendancePolicyManage]);
    await tester.tap(find.widgetWithText(OutlinedButton, 'Discard draft'));
    await tester.pumpAndSettle();
    await tester.tap(find.widgetWithText(FilledButton, 'Discard'));
    await tester.pumpAndSettle();
    final call = client.calls.single;
    expect(call.method, 'DELETE');
    expect(call.path, '/attendance-policies/p1/versions/v2');
    expect(call.ifMatch, '8');
  });

  testWidgets('with a draft open there is no second "Create draft"', (tester) async {
    await _pump(tester, [_version(1), _version(2, status: 'DRAFT')], [attendancePolicyManage]);
    expect(find.text('Create draft'), findsNothing);
  });
}
