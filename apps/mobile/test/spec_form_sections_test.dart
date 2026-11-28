import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:hrms_mobile/core/forms/form_spec.dart';
import 'package:hrms_mobile/core/forms/regions.dart';
import 'package:hrms_mobile/core/forms/spec_form.dart';
import 'package:hrms_mobile/features/employees/domain/employee_forms.dart';

const _spec = FormSpec(
  name: 't',
  label: 'T',
  fields: [
    FieldSpec('sec_a', 'Alpha', kind: FieldKind.section, hint: 'First group'),
    FieldSpec('a1', 'Alpha one'),
    FieldSpec('sec_b', 'Beta', kind: FieldKind.section),
    FieldSpec('b1', 'Beta one'),
    FieldSpec('sec_c', 'Gamma', kind: FieldKind.section),
    FieldSpec('c1', 'Gamma one', required: true),
    FieldSpec('c2', 'Gamma two', showWhen: '!hide_c2'),
    FieldSpec('hide_c2', 'Hide', kind: FieldKind.toggle),
  ],
);

Widget _host(FormSpec spec, Map<String, dynamic> values, {Map<String, String> errors = const {}}) => MaterialApp(
      home: Scaffold(
        body: SingleChildScrollView(child: SpecForm(spec: spec, values: values, errors: errors, onChanged: () {})),
      ),
    );

Finder _label(String text) => find.text(text, findRichText: true);

/// A tall screen, so every section header is on screen and tappable.
void _tall(WidgetTester tester) {
  tester.view.physicalSize = const Size(800, 4000);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);
}

void main() {
  testWidgets('the first section is open, the rest are closed until tapped', (tester) async {
    _tall(tester);
    await tester.pumpWidget(_host(_spec, rowFromWire(_spec, const {})));
    expect(_label('Alpha one'), findsOneWidget);
    expect(_label('Beta one'), findsNothing);
    await tester.tap(find.byKey(const Key('section-sec_b')));
    await tester.pump();
    expect(_label('Beta one'), findsOneWidget);
    await tester.tap(find.byKey(const Key('section-sec_b')));
    await tester.pump();
    expect(_label('Beta one'), findsNothing);
  });

  testWidgets('a section holding a required field starts open', (tester) async {
    _tall(tester);
    await tester.pumpWidget(_host(_spec, rowFromWire(_spec, const {})));
    expect(find.textContaining('Gamma one', findRichText: true), findsOneWidget);
  });

  testWidgets('a new error opens its closed section and counts it in the header', (tester) async {
    _tall(tester);
    final values = rowFromWire(_spec, const {});
    await tester.pumpWidget(_host(_spec, values));
    expect(_label('Beta one'), findsNothing);
    await tester.pumpWidget(_host(_spec, values, errors: const {'b1': 'Not valid'}));
    await tester.pumpAndSettle();
    expect(_label('Beta one'), findsOneWidget);
    expect(find.text('Not valid'), findsOneWidget);
    expect(find.text('1 to fix'), findsOneWidget);
  });

  testWidgets('a value typed in a section survives collapsing it', (tester) async {
    _tall(tester);
    final values = rowFromWire(_spec, const {});
    await tester.pumpWidget(_host(_spec, values));
    await tester.enterText(find.byType(TextField).first, 'kept');
    await tester.tap(find.byKey(const Key('section-sec_a')));
    await tester.pump();
    await tester.tap(find.byKey(const Key('section-sec_a')));
    await tester.pump();
    expect(find.text('kept'), findsOneWidget);
    expect(values['a1'], 'kept');
  });

  testWidgets('a section whose fields are all hidden is not shown', (tester) async {
    _tall(tester);
    const spec = FormSpec(name: 't2', label: 'T2', fields: [
      FieldSpec('sec', 'Only', kind: FieldKind.section),
      FieldSpec('x', 'X', showWhen: 'never'),
    ]);
    await tester.pumpWidget(_host(spec, rowFromWire(spec, const {})));
    expect(find.text('Only'), findsNothing);
  });

  test('sections carry no value: never in the payload, form values or validation', () {
    final values = rowFromWire(_spec, const {'c1': 'x'});
    expect(values.keys, isNot(contains('sec_a')));
    expect(rowToPayload(_spec, values).keys, isNot(contains('sec_b')));
    expect(validateRow(_spec, values), isEmpty);
    expect(validateRow(_spec, rowFromWire(_spec, const {})).keys, ['c1']);
  });

  test('the employee form is in four sections and sends the same fields as before', () {
    final sections = [for (final f in employeeSpec.fields) if (f.kind == FieldKind.section) f.label];
    expect(sections, ['Basics', 'Address', 'Emergency contact', 'More details']);
    final payload = rowToPayload(employeeSpec, rowFromWire(employeeSpec, const {'first_name': 'Asha'}));
    expect(payload.keys.where((k) => k.startsWith('section_')), isEmpty);
    expect(payload['first_name'], 'Asha');
    expect(payload.containsKey('present_state_code'), isTrue);
    expect(payload.containsKey('blood_group'), isTrue);
    expect(validateRow(employeeSpec, rowFromWire(employeeSpec, const {})).keys, ['first_name']);
  });

  test('state and country pickers use codes the API accepts', () {
    expect(indiaStateOptions, hasLength(36));
    expect(indiaStateOptions.toSet(), indiaStateLabels.keys.toSet());
    expect(indiaStateLabels['MH'], 'Maharashtra');
    expect(countryOptions.first, 'IN');
    expect(countryOptions.every((c) => RegExp(r'^[A-Z]{2}$').hasMatch(c)), isTrue);
    expect(countryOptions.toSet(), countryLabels.keys.toSet());
  });

  testWidgets('an address saved with free text still shows it in the state picker', (tester) async {
    _tall(tester);
    final values = rowFromWire(employeeSpec, const {'first_name': 'A', 'present_state_code': 'Maha'});
    await tester.pumpWidget(_host(employeeSpec, values));
    await tester.tap(find.byKey(const Key('section-section_address')));
    await tester.pumpAndSettle();
    expect(find.text('Maha'), findsWidgets);
  });
}
