import 'package:flutter_test/flutter_test.dart';
import 'package:hrms_mobile/core/time.dart' show initTimeZones;
import 'package:hrms_mobile/features/attendance/data/attendance_repository.dart';
import 'package:hrms_mobile/features/attendance/presentation/raise_correction.dart';

AttendanceDay _day({String status = 'PRESENT', Map<String, dynamic> over = const {}}) => AttendanceDay.fromJson({
      'id': 'd-1',
      'employee_id': 'e-1',
      'attendance_date': '2026-11-10',
      'attendance_status': status,
      'timezone': 'Asia/Kolkata',
      'actual_first_in': '2026-11-10T03:32:00Z',
      'actual_last_out': null,
      'worked_minutes': 0,
      'is_locked': false,
      ...over,
    });

void main() {
  setUpAll(initTimeZones);

  test('a missing punch or an incomplete day suggests "missed a punch"', () {
    expect(suggestedCorrectionType(_day(over: {'missing_punch': true})), 'MISSING_PUNCH');
    expect(suggestedCorrectionType(_day(status: 'INCOMPLETE')), 'MISSING_PUNCH');
  });

  test('a late arrival or early exit suggests "a punch time is wrong"', () {
    expect(suggestedCorrectionType(_day(over: {'is_late': true})), 'WRONG_PUNCH');
    expect(suggestedCorrectionType(_day(over: {'is_early_out': true})), 'WRONG_PUNCH');
  });

  test('an unflagged day suggests nothing; the employee chooses', () {
    expect(suggestedCorrectionType(_day()), isNull);
    expect(correctionDefaultsFor(_day()), {'attendance_date': '2026-11-10'});
  });

  test('defaults carry the date and type, never punch times', () {
    final d = correctionDefaultsFor(_day(over: {'missing_punch': true}));
    expect(d, {'attendance_date': '2026-11-10', 'request_type': 'MISSING_PUNCH'});
  });

  test('the note shows what was recorded, in the company zone', () {
    expect(recordedPunchesNote(_day(), 'Asia/Kolkata'), startsWith('Recorded for this day: in 09:02 · out —.'));
  });
}
