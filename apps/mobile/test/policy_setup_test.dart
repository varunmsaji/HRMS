import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:hrms_mobile/core/forms/form_spec.dart';
import 'package:hrms_mobile/core/providers.dart';
import 'package:hrms_mobile/features/attendance/domain/attendance_setup_configs.dart';
import 'package:hrms_mobile/features/attendance/domain/policy_setup_config.dart';
import 'package:hrms_mobile/features/attendance/presentation/policy_setup_screen.dart';
import 'package:hrms_mobile/features/leave/domain/leave_setup_config.dart';

import 'support/fake_api_client.dart';
import 'support/fake_auth.dart';

FakeApiClient _api({List<Map<String, dynamic>> companyWide = const []}) => FakeApiClient(lists: {
      '/policy-assignments': companyWide,
      '/leave-types': [
        {'id': 'lt1', 'name': 'Casual Leave', 'is_active': true}
      ],
      '/weekly-off-patterns': const [],
      '/legal-entities': const [],
      '/branches': [
        {'id': 'b1', 'name': 'Pune HQ', 'is_active': true}
      ],
      '/departments': const [],
      '/grades': const [],
      '/designations': const [],
      '/shifts': const [],
      '/employees': const [],
    });

Future<void> _pump(WidgetTester tester, FakeApiClient api, PolicySetupConfig config) async {
  tester.view.physicalSize = const Size(800, 6000);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
  await tester.pumpWidget(ProviderScope(overrides: [apiClientProvider.overrideWithValue(api), fakeAuth(const [])], child: MaterialApp(home: PolicySetupScreen(config: config))));
  await tester.pumpAndSettle();
}

Future<void> _publishFlow(WidgetTester tester) async {
  await tester.tap(find.text('Save & publish…'));
  await tester.pumpAndSettle();
}

Map<String, dynamic> _setupBody(FakeApiClient api) => api.calls.singleWhere((c) => c.path.endsWith('/setup')).body as Map<String, dynamic>;

void main() {
  group('configs', () {
    final all = {
      'attendance': attendancePolicySetup,
      'overtime': overtimePolicySetup,
      'regularization': regularizationPolicySetup,
      'leave': leavePolicySetup,
      'shift': shiftSetup,
    };

    test('every everyday field exists in the rules form, and no rule has a start date', () {
      all.forEach((name, c) {
        final keys = c.rules.fields.map((f) => f.key).toSet();
        expect(keys.containsAll(c.everydayKeys), isTrue, reason: '$name: ${c.everydayKeys.where((k) => !keys.contains(k))}');
        expect(keys.contains('effective_from'), isFalse, reason: name);
      });
    });

    test('every template validates against its rules form once named', () {
      all.forEach((name, c) {
        final spec = FormSpec(name: 'x', label: 'x', fields: [const FieldSpec('name', 'Name', required: true), ...c.rules.fields]);
        for (final t in c.templates.where((t) => t.key != 'blank')) {
          final values = rowFromWire(spec, {...c.base, ...t.values, 'name': t.defaultName});
          expect(validateRow(spec, values), isEmpty, reason: '$name / ${t.key}');
        }
      });
    });
  });

  test('conditions joined with && must all hold', () {
    const f = FieldSpec('x', 'X', showWhen: 'a!=NO&&a!=ALL');
    expect(fieldVisible(f, {'a': 'BRANCH'}), isTrue);
    expect(fieldVisible(f, {'a': 'NO'}), isFalse);
    expect(fieldVisible(f, {'a': 'ALL'}), isFalse);
  });

  testWidgets('publishing the first template assigns it to the whole company in one request', (tester) async {
    final api = _api();
    await _pump(tester, api, attendancePolicySetup);
    expect(find.widgetWithText(TextField, 'Standard office'), findsOneWidget);
    await _publishFlow(tester);
    await tester.tap(find.widgetWithText(FilledButton, 'Publish'));
    await tester.pumpAndSettle();

    expect(api.calls, hasLength(1));
    final body = _setupBody(api);
    expect(api.calls.single.path, '/attendance-policies/setup');
    expect(body['name'], 'Standard office');
    expect(body['publish'], true);
    expect(body['assign'], {'scope_type': 'COMPANY', 'scope_id': null, 'expected_version': null});
    final rules = body['rules'] as Map<String, dynamic>;
    expect(rules['grace_in_minutes'], 10);
    expect(rules['effective_from'], matches(RegExp(r'^\d{4}-\d{2}-\d{2}$')));
    expect((rules['hour_bands'] as List).map((b) => (b as Map)['result_status']), ['ABSENT', 'HALF_DAY', 'PRESENT']);
  });

  testWidgets('a company that already has a company-wide policy defaults to nobody and sends no assignment', (tester) async {
    final api = _api(companyWide: [
      {'id': 'a1', 'policy_kind': 'ATTENDANCE_POLICY', 'scope_type': 'COMPANY', 'scope_id': null, 'leave_type_id': null, 'effective_to': null, 'version': 3}
    ]);
    await _pump(tester, api, attendancePolicySetup);
    await _publishFlow(tester);
    await tester.tap(find.widgetWithText(FilledButton, 'Publish'));
    await tester.pumpAndSettle();
    expect(_setupBody(api).containsKey('assign'), isFalse);
  });

  testWidgets('saving a draft publishes and assigns nothing', (tester) async {
    final api = _api();
    await _pump(tester, api, attendancePolicySetup);
    await tester.tap(find.text('Save as draft'));
    await tester.pumpAndSettle();
    final body = _setupBody(api);
    expect(body['publish'], false);
    expect(body.containsKey('assign'), isFalse);
    expect((body['rules'] as Map).containsKey('effective_from'), isFalse);
  });

  testWidgets('switching template keeps a name the user typed but replaces the rules', (tester) async {
    final api = _api();
    await _pump(tester, api, attendancePolicySetup);
    await tester.enterText(find.widgetWithText(TextField, 'Standard office'), 'Head office');
    await tester.tap(find.text('Flexible hours'));
    await tester.pumpAndSettle();
    expect(find.widgetWithText(TextField, 'Head office'), findsOneWidget);
    await tester.tap(find.text('Save as draft'));
    await tester.pumpAndSettle();
    expect(_setupBody(api)['name'], 'Head office');
    expect((_setupBody(api)['rules'] as Map)['grace_in_minutes'], 30);
  });

  testWidgets('a name left as the suggestion follows the template', (tester) async {
    await _pump(tester, _api(), attendancePolicySetup);
    await tester.tap(find.text('Strict attendance'));
    await tester.pumpAndSettle();
    expect(find.widgetWithText(TextField, 'Strict attendance'), findsOneWidget);
  });

  testWidgets('a name is required', (tester) async {
    final api = _api();
    await _pump(tester, api, attendancePolicySetup);
    await tester.enterText(find.widgetWithText(TextField, 'Standard office'), '');
    await tester.tap(find.text('Save as draft'));
    await tester.pumpAndSettle();
    expect(find.text('Name is required.'), findsOneWidget);
    expect(api.calls, isEmpty);
  });

  testWidgets('a regularization policy needs a kind of correction before it can be published', (tester) async {
    final api = _api();
    await _pump(tester, api, regularizationPolicySetup);
    await tester.tap(find.text('Start from scratch'));
    await tester.pumpAndSettle();
    await tester.enterText(find.widgetWithText(TextField, '').first, 'Corrections');
    await _publishFlow(tester);
    expect(find.text('Choose at least one kind of correction before publishing.'), findsOneWidget);
    expect(api.calls, isEmpty);
  });

  testWidgets('a leave policy needs a leave type and sends it with the assignment', (tester) async {
    final api = _api();
    await _pump(tester, api, leavePolicySetup);
    await tester.tap(find.text('Save as draft'));
    await tester.pumpAndSettle();
    expect(find.text('Leave type is required.'), findsOneWidget);
    expect(api.calls, isEmpty);

    await tester.tap(find.byType(DropdownButtonFormField<String>).first);
    await tester.pumpAndSettle();
    await tester.tap(find.text('Casual Leave').last);
    await tester.pumpAndSettle();
    await tester.tap(find.text('Earned leave'));
    await tester.pumpAndSettle();
    await _publishFlow(tester);
    await tester.tap(find.widgetWithText(FilledButton, 'Publish'));
    await tester.pumpAndSettle();

    final body = _setupBody(api);
    expect(body['leave_type_id'], 'lt1');
    expect(body['name'], 'Earned leave');
    expect((body['assign'] as Map)['scope_type'], 'COMPANY');
    final rules = body['rules'] as Map;
    expect(rules['accrual_frequency'], 'MONTHLY');
    expect(rules['accrual_rate_per_cycle'], 1.5);
    expect(rules['max_carry_forward_days'], 30);
  });

  testWidgets('the accrual amount only appears once days are credited', (tester) async {
    await _pump(tester, _api(), leavePolicySetup);
    await tester.tap(find.text('Start from scratch'));
    await tester.pumpAndSettle();
    expect(find.textContaining('Accrual per cycle', findRichText: true), findsNothing);
    await tester.tap(find.text('Casual leave'));
    await tester.pumpAndSettle();
    expect(find.textContaining('Accrual per cycle', findRichText: true), findsOneWidget);
  });

  testWidgets('a night shift template is published as a shift with no assignment', (tester) async {
    final api = _api();
    await _pump(tester, api, shiftSetup);
    await tester.tap(find.text('Night (10 to 6)'));
    await tester.pumpAndSettle();
    expect(find.widgetWithText(TextField, 'Night shift'), findsOneWidget);
    await _publishFlow(tester);
    await tester.tap(find.widgetWithText(FilledButton, 'Publish'));
    await tester.pumpAndSettle();
    final body = _setupBody(api);
    expect(api.calls.single.path, '/shifts/setup');
    expect(body.containsKey('assign'), isFalse);
    final rules = body['rules'] as Map;
    expect(rules['shift_type'], 'FIXED');
    expect(rules['start_time'], '22:00');
    expect(rules['end_time'], '06:00');
    expect(rules['is_night_shift'], true);
    expect(rules.containsKey('window_start'), isFalse);
  });
}
