import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:hrms_mobile/core/api/api_error.dart';
import 'package:hrms_mobile/core/auth/permissions.dart';
import 'package:hrms_mobile/core/providers.dart';
import 'package:hrms_mobile/features/payroll/presentation/employee_salary_panel.dart';
import 'package:hrms_mobile/features/payroll/presentation/salary_setup_screen.dart';

import 'support/fake_api_client.dart';
import 'support/fake_auth.dart';

Map<String, dynamic> _component(String id, String code, String name) =>
    {'id': id, 'code': code, 'name': name, 'component_type': 'EARNING', 'is_active': true};

Map<String, dynamic> _line(String componentId, String code, String calc, String? pct, {String? base}) => {
      'id': 'l-$code', 'salary_component_id': componentId, 'component_code': code, 'component_name': code,
      'component_type': 'EARNING', 'calculation_type': calc, 'percentage': pct, 'amount_monthly_minor': null,
      'base_salary_component_id': base, 'max_monthly_minor': null, 'applies_when': 'ALWAYS', 'display_order': 10,
    };

final _templateLines = [
  _line('c-basic', 'BASIC', 'PERCENTAGE_OF_GROSS', '50'),
  _line('c-hra', 'HRA', 'PERCENTAGE_OF_COMPONENT', '40', base: 'c-basic'),
  _line('c-sa', 'SPECIAL_ALLOWANCE', 'BALANCING', null),
];

final _standard = {
  'id': 'st-1', 'code': 'STANDARD', 'name': 'Standard', 'is_active': true,
  'versions': [
    {'id': 'v-1', 'status': 'PUBLISHED', 'effective_from': '2026-01-01', 'effective_to': null, 'lines': _templateLines},
  ],
};

Map<String, dynamic> _breakupLine(String code, int monthly) =>
    {'component_code': code, 'component_name': code, 'component_type': 'EARNING', 'monthly_minor': monthly, 'annual_minor': monthly * 12, 'basis': ''};

/// ₹12,00,000 a year → gross ₹1,00,000 a month; Basic 50% = ₹50,000; HRA 40% of Basic = ₹20,000.
final _preview = {
  'pf_applicable': false,
  'esi_applicable': false,
  'breakup': {
    'annual_ctc_minor': 120000000, 'monthly_ctc_minor': 10000000, 'gross_monthly_minor': 10000000,
    'employer_contributions_monthly_minor': 0,
    'lines': [_breakupLine('BASIC', 5000000), _breakupLine('HRA', 2000000), _breakupLine('SPECIAL_ALLOWANCE', 3000000)],
  },
};

final _createdDraft = {
  'id': 'st-2', 'code': 'SENIOR_ENGINEER', 'name': 'Senior engineer', 'is_active': true,
  'versions': [
    {'id': 'v-9', 'status': 'DRAFT', 'version': 3, 'effective_from': null, 'effective_to': null, 'lines': _templateLines},
  ],
};
final _createdPublished = {
  'id': 'st-2', 'code': 'SENIOR_ENGINEER', 'name': 'Senior engineer', 'is_active': true,
  'versions': [
    {'id': 'v-9', 'status': 'PUBLISHED', 'version': 4, 'effective_from': '2000-01-01', 'effective_to': null, 'lines': _templateLines},
  ],
};

/// Fails only the create POST: the same path is also the structures list the screen loads.
class _CreateFails extends FakeApiClient {
  _CreateFails({super.lists, super.objects});

  @override
  Future<T> post<T>(String path, {dynamic body, required T Function(dynamic) parse, bool authenticated = true, String? ifMatch, Map<String, String>? headers}) {
    if (path == '/payroll/salary-structures') throw ApiError(status: 409, code: 'DUPLICATE', message: 'That code is taken.');
    return super.post(path, body: body, parse: parse, ifMatch: ifMatch);
  }
}

FakeApiClient _api({String payBasis = 'MONTHLY', Map<String, dynamic> setup = const {}, bool createFails = false}) => (createFails ? _CreateFails.new : FakeApiClient.new)(
      lists: {
        '/payroll/salary-structures': [_standard],
        '/payroll/salary-components': [_component('c-basic', 'BASIC', 'Basic'), _component('c-hra', 'HRA', 'HRA'), _component('c-sa', 'SPECIAL_ALLOWANCE', 'Special Allowance')],
      },
      objects: {
        '/employees/emp-1/salary/setup': {
          'employee_id': 'emp-1', 'as_of': '2026-09-24', 'pay_basis': payBasis, 'annual_ctc_minor': 120000000,
          'pf_applicable': false, 'esi_applicable': false, 'assignment': null, 'salary_structure_id': null,
          'salary_structure_name': null, 'template_structure_id': null, 'is_customised': false, 'lines': <dynamic>[],
          ...setup,
        },
        '/employees/emp-1/salary/setup/preview': _preview,
        '/payroll/salary-structures': _createdDraft,
        '/payroll/salary-structures/st-2/versions/v-9/publish': _createdPublished,
      },
    );

Future<void> _pump(WidgetTester tester, FakeApiClient api, Widget home, [List<String> permissions = const []]) async {
  tester.view.physicalSize = const Size(800, 4000);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
  await tester.pumpWidget(ProviderScope(overrides: [apiClientProvider.overrideWithValue(api), fakeAuth(permissions)], child: MaterialApp(home: home)));
  await tester.pumpAndSettle();
}

void main() {
  testWidgets('fills in each component amount and marks a changed percentage as customised', (tester) async {
    final api = _api();
    await _pump(tester, api, const SalarySetupScreen(employeeId: 'emp-1', today: '2026-09-24'));
    await tester.pump(const Duration(milliseconds: 500));
    await tester.pumpAndSettle();

    expect(find.text('₹50,000'), findsOneWidget);
    expect(find.text('50% of gross'), findsOneWidget);
    expect(find.text('₹20,000'), findsOneWidget);
    expect(find.text('₹1,00,000'), findsWidgets, reason: 'CTC a month and the cost-to-company total');
    expect(find.text('Same as Standard'), findsOneWidget);
    final preview = api.calls.where((c) => c.path == '/employees/emp-1/salary/setup/preview').last;
    expect((preview.body as Map)['annual_ctc_minor'], 120000000);

    await tester.tap(find.text('Basic'));
    await tester.pumpAndSettle();
    await tester.enterText(find.byKey(const ValueKey('pct-c-basic')), '40');
    await tester.pump(const Duration(milliseconds: 500));
    await tester.pumpAndSettle();
    expect(find.text('Customised for this employee'), findsOneWidget);
    final sent = (api.calls.where((c) => c.path == '/employees/emp-1/salary/setup/preview').last.body as Map)['lines'] as List;
    expect((sent.firstWhere((l) => l['salary_component_id'] == 'c-basic') as Map)['percentage'], '40');
  });

  testWidgets('saves the new CTC with the lines from one effective date', (tester) async {
    final api = _api();
    await _pump(tester, api, const SalarySetupScreen(employeeId: 'emp-1', today: '2026-09-24'));

    await tester.enterText(find.widgetWithText(TextField, 'Annual CTC (₹)'), '1500000');
    await tester.tap(find.text('Basic'));
    await tester.pumpAndSettle();
    await tester.enterText(find.byKey(const ValueKey('pct-c-basic')), '45');
    await tester.enterText(find.widgetWithText(TextField, 'Reason'), 'Annual review');
    await tester.pump(const Duration(milliseconds: 500));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Save salary'));
    await tester.pumpAndSettle();

    final save = api.calls.singleWhere((c) => c.path == '/employees/emp-1/salary/setup');
    final body = save.body as Map;
    expect(body['annual_ctc_minor'], 150000000);
    expect(body['revision_type'], 'ANNUAL');
    expect(body['template_structure_id'], 'st-1');
    expect(body['effective_from'], '2026-09-24');
    expect(((body['lines'] as List).firstWhere((l) => l['salary_component_id'] == 'c-basic') as Map)['percentage'], '45');
  });

  testWidgets('Save as new structure creates and publishes a structure from the lines, then selects it', (tester) async {
    final api = _api();
    await _pump(tester, api, const SalarySetupScreen(employeeId: 'emp-1', today: '2026-09-24'));
    await tester.tap(find.byKey(const Key('save-as-new-structure')));
    await tester.pumpAndSettle();
    await tester.enterText(find.widgetWithText(TextField, 'Name'), 'Senior engineer');
    await tester.tap(find.text('Create structure'));
    await tester.pumpAndSettle();

    final create = api.calls.firstWhere((c) => c.path == '/payroll/salary-structures');
    final body = create.body as Map;
    expect(body['code'], 'SENIOR_ENGINEER');
    expect(body['name'], 'Senior engineer');
    expect((body['lines'] as List).length, 3);
    final publish = api.calls.singleWhere((c) => c.path == '/payroll/salary-structures/st-2/versions/v-9/publish');
    expect((publish.body as Map)['effective_from'], '2000-01-01');
    expect(publish.ifMatch, '3');
    // The employee's own salary is untouched, and the new structure is the one selected.
    expect(api.calls.where((c) => c.path == '/employees/emp-1/salary/setup'), isEmpty);
    expect(find.text('Senior engineer'), findsWidgets);
    expect(find.text('Save as new structure'), findsOneWidget);
  });

  testWidgets('Save as new structure needs a name and shows the server error in the dialog', (tester) async {
    final api = _api(createFails: true);
    await _pump(tester, api, const SalarySetupScreen(employeeId: 'emp-1', today: '2026-09-24'));
    await tester.tap(find.byKey(const Key('save-as-new-structure')));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Create structure'));
    await tester.pumpAndSettle();
    expect(find.text('Enter a name for the structure.'), findsOneWidget);
    expect(api.calls.where((c) => c.path == '/payroll/salary-structures'), isEmpty);
    await tester.enterText(find.widgetWithText(TextField, 'Name'), 'Senior engineer');
    await tester.tap(find.text('Create structure'));
    await tester.pumpAndSettle();
    expect(find.text('That code is taken.'), findsOneWidget);
    expect(find.text('Create structure'), findsOneWidget);
  });

  test('structureCodeFromName matches web', () {
    expect(structureCodeFromName('Senior engineer'), 'SENIOR_ENGINEER');
    expect(structureCodeFromName('  --Ops & Admin (L2)  '), 'OPS_ADMIN_L2');
    expect(structureCodeFromName('x' * 40).length, 30);
  });

  testWidgets('says what is missing instead of silently refusing to save', (tester) async {
    final api = _api();
    await _pump(tester, api, const SalarySetupScreen(employeeId: 'emp-1', today: '2026-09-24'));
    await tester.enterText(find.widgetWithText(TextField, 'Annual CTC (₹)'), '1500000');
    await tester.pump(const Duration(milliseconds: 500));
    await tester.pumpAndSettle();

    final save = find.widgetWithText(FilledButton, 'Save salary');
    expect(tester.widget<FilledButton>(save).onPressed, isNotNull);
    await tester.tap(save);
    await tester.pumpAndSettle();

    expect(find.text('Before saving, add a reason.'), findsOneWidget);
    expect(find.text('Required'), findsOneWidget);
    expect(api.calls.where((c) => c.path == '/employees/emp-1/salary/setup'), isEmpty);

    // The warning goes away as soon as the missing field is filled in.
    await tester.enterText(find.widgetWithText(TextField, 'Reason'), 'Annual review');
    await tester.pumpAndSettle();
    expect(find.textContaining('Before saving'), findsNothing);
    expect(find.text('Required'), findsNothing);
  });

  testWidgets('says when there is nothing to save', (tester) async {
    // Already on Standard with its exact lines: nothing differs until HR edits something.
    final api = _api(setup: {'template_structure_id': 'st-1', 'lines': _templateLines});
    await _pump(tester, api, const SalarySetupScreen(employeeId: 'emp-1', today: '2026-09-24'));
    await tester.enterText(find.widgetWithText(TextField, 'Reason'), 'Annual review');
    await tester.pumpAndSettle();

    await tester.tap(find.widgetWithText(FilledButton, 'Save salary'));
    await tester.pumpAndSettle();

    expect(find.textContaining('Nothing has changed yet'), findsOneWidget);
    expect(api.calls.where((c) => c.path == '/employees/emp-1/salary/setup'), isEmpty);
  });

  testWidgets('a daily-wage employee is pointed to the daily rate instead', (tester) async {
    await _pump(tester, _api(payBasis: 'DAILY_WAGE'), const SalarySetupScreen(employeeId: 'emp-1', today: '2026-09-24'));
    expect(find.textContaining('daily-wage employee'), findsOneWidget);
    expect(find.text('Save salary'), findsNothing);
  });

  testWidgets('the Salary tab offers the editor with both permissions', (tester) async {
    await _pump(tester, _api(), const Scaffold(body: EmployeeSalaryPanel(employeeId: 'emp-1')), const [payrollSetupManage, employeeUpdateCompensation]);
    expect(find.text('Edit salary & structure'), findsOneWidget);
  });

  testWidgets('without the compensation permission the Salary tab has no editor', (tester) async {
    await _pump(tester, _api(), const Scaffold(body: EmployeeSalaryPanel(employeeId: 'emp-1')), const [payrollSetupManage]);
    expect(find.text('Edit salary & structure'), findsNothing);
    expect(find.text('Assign'), findsOneWidget);
  });
}
