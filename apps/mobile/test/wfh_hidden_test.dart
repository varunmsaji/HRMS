import 'package:flutter_test/flutter_test.dart';
import 'package:hrms_mobile/features/attendance/domain/request_resources.dart';

void main() {
  test('asking for a correction does not offer work from home (R-B05)', () {
    final type = regularizationSpec(false).fields.firstWhere((f) => f.key == 'request_type');
    expect(type.options, isNot(contains('WFH')));
    expect(type.options, contains('MISSING_PUNCH'));
  });
}
