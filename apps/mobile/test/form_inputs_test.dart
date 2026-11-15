import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:hrms_mobile/core/forms/form_spec.dart';
import 'package:hrms_mobile/core/forms/spec_form_screen.dart';
import 'package:hrms_mobile/core/theme/app_theme.dart';

import 'support/test_themes.dart';

/// Audit MOB-UX-025 and 027: the right keyboard for each field, and a long form that can always be
/// submitted and shows where it went wrong.

const _contact = FormSpec(name: 'c', label: 'C', fields: [
  FieldSpec('phone', 'Phone', kind: FieldKind.phone),
  FieldSpec('pin', 'PIN code', kind: FieldKind.pincode),
  FieldSpec('amount', 'Amount', kind: FieldKind.money),
  FieldSpec('note', 'Note', kind: FieldKind.multiline),
]);

FormSpec _long() => FormSpec(name: 'l', label: 'L', fields: [
      const FieldSpec('first', 'First field', required: true),
      for (var i = 0; i < 20; i++) FieldSpec('f$i', 'Field $i'),
    ]);

Future<List<Map<String, dynamic>>> _pump(WidgetTester tester, FormSpec spec) async {
  final sent = <Map<String, dynamic>>[];
  tester.view.physicalSize = const Size(360, 640);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
  await tester.pumpWidget(MaterialApp(
    theme: AppTheme.light,
    home: SpecFormScreen(title: 'Form', spec: spec, submitLabel: 'Submit request', onSubmit: (payload, _) async => sent.add(payload)),
  ));
  await tester.pumpAndSettle();
  return sent;
}

TextField _field(WidgetTester tester, String label) =>
    tester.widget<TextField>(find.descendant(of: find.ancestor(of: find.text(label, findRichText: true), matching: find.byType(Column)).first, matching: find.byType(TextField)));

void main() {
  setUpAll(primeThemes);

  group('rules', () {
    Map<String, String> check(Map<String, dynamic> v) => validateRow(_contact, {'phone': '', 'pin': '', 'amount': '', 'note': '', ...v});

    test('phone numbers: digits with the usual separators', () {
      expect(check({'phone': '+91 98765 43210'}), isEmpty);
      expect(check({'phone': '(080) 2345-6789'}), isEmpty);
      expect(check({'phone': '12345'}).keys, ['phone']);
      expect(check({'phone': 'call me'}).keys, ['phone']);
    });

    test('a PIN code is six digits, not starting with 0', () {
      expect(check({'pin': '560001'}), isEmpty);
      expect(check({'pin': '56001'})['pin'], 'Enter a 6-digit PIN code.');
      expect(check({'pin': '060001'}).keys, ['pin']);
    });
  });

  testWidgets('each field gets its keyboard; amounts have no minus key; notes start sentences', (tester) async {
    await _pump(tester, _contact);
    expect(_field(tester, 'Phone').keyboardType, TextInputType.phone);
    expect(_field(tester, 'Phone').autofillHints, contains(AutofillHints.telephoneNumber));
    expect(_field(tester, 'PIN code').keyboardType, TextInputType.number);
    expect(_field(tester, 'Amount').keyboardType, const TextInputType.numberWithOptions(decimal: true));
    expect(_field(tester, 'Note').textCapitalization, TextCapitalization.sentences);
    expect(_field(tester, 'Phone').textInputAction, TextInputAction.next);
  });

  testWidgets('a PIN code cannot be typed longer than six digits or with letters', (tester) async {
    await _pump(tester, _contact);
    await tester.enterText(find.byWidget(_field(tester, 'PIN code')), '56a00123');
    expect(find.text('560012'), findsOneWidget);
  });

  testWidgets('Submit stays on screen on a long form, and a failed submit shows the first error', (tester) async {
    final sent = await _pump(tester, _long());
    final submit = find.widgetWithText(FilledButton, 'Submit request');
    expect(tester.getRect(submit).bottom, lessThanOrEqualTo(640), reason: 'pinned, not at the end of the scroll');

    await tester.drag(find.byType(SingleChildScrollView), const Offset(0, -2000));
    await tester.pumpAndSettle();
    expect(find.text('First field', findRichText: true), findsNothing, reason: 'scrolled away');

    await tester.tap(submit);
    await tester.pumpAndSettle();
    expect(sent, isEmpty);
    expect(find.text('First field is required.'), findsOneWidget);
    expect(tester.getRect(find.text('First field is required.')).top, greaterThanOrEqualTo(0), reason: 'brought into view');
  });
}
