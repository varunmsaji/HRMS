import 'package:flutter_test/flutter_test.dart';
import 'package:hrms_mobile/features/profile/presentation/employee_record_sections.dart';

void main() {
  test('formats missing, boolean and money values', () {
    expect(formatRecordValue(const RecordField('x', 'x'), null), 'Not configured');
    expect(formatRecordValue(const RecordField('x', 'x'), '  '), 'Not configured');
    expect(formatRecordValue(const RecordField('x', 'x', format: RecordFormat.yesNo), true), 'Yes');
    expect(formatRecordValue(const RecordField('x', 'x', format: RecordFormat.yesNo), false), 'No');
    expect(formatRecordValue(const RecordField('x', 'x', format: RecordFormat.money), 1250000), '12500.00');
  });

  test('every section has fields and sensitive ones are permission-gated', () {
    for (final s in employeeRecordSections) {
      expect(s.fields, isNotEmpty);
    }
    final gated = employeeRecordSections.where((s) => s.permission != null).map((s) => s.title);
    expect(gated, containsAll(['Compensation', 'Statutory', 'Banking', 'Identity', 'Dependents']));
  });
}
