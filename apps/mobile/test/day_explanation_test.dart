import 'package:flutter_test/flutter_test.dart';
import 'package:hrms_mobile/features/attendance/domain/day_explanation.dart';

void main() {
  test('reads the API explanation as written', () {
    final e = DayExplanation.tryParse({
      'reason': 'Worked 8 h 10 m of 8 h. On time.',
      'facts': [
        {'key': 'worked', 'label': 'Worked', 'value': '8 h 10 m'},
      ],
      'pay': {'label': '1 day paid'},
      'overtime': {'found_min': 105, 'approved_min': 90, 'pending_min': 15},
      'action': {'kind': 'REQUEST_CORRECTION', 'deadline': '2026-11-30', 'consequence': 'Counts as absent (unpaid) if not fixed'},
    })!;
    expect(e.reason, 'Worked 8 h 10 m of 8 h. On time.');
    expect(e.facts, [('Worked', '8 h 10 m')]);
    expect(e.payLabel, '1 day paid');
    expect(e.overtimeLine, contains('waiting for approval'));
    expect(e.actionLine, 'Fix by 30 Nov. Counts as absent (unpaid) if not fixed.');
  });

  test('a day with nothing to fix or earn has no action or overtime line', () {
    final e = DayExplanation.tryParse({'reason': 'Weekly off. No work expected.', 'facts': [], 'pay': {'label': 'No pay effect'}, 'overtime': null, 'action': null})!;
    expect(e.actionLine, isNull);
    expect(e.overtimeLine, isNull);
  });

  test('an older API with no explanation shows nothing', () {
    expect(DayExplanation.tryParse(null), isNull);
    expect(DayExplanation.tryParse({'facts': []}), isNull);
  });
}
