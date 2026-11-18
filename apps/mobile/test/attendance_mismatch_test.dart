import 'package:flutter_test/flutter_test.dart';
import 'package:hrms_mobile/features/attendance/data/attendance_repository.dart';
import 'package:hrms_mobile/features/attendance/domain/attendance_mismatch.dart';

AttendanceDay _day(String status, {String? firstIn = '2026-11-18T04:00:00Z', String? lastOut = '2026-11-18T12:30:00Z', Map<String, dynamic> over = const {}}) => AttendanceDay.fromJson({
  'id': 'd1',
  'employee_id': 'e1',
  'attendance_date': '2026-11-18',
  'attendance_status': status,
  'is_locked': false,
  'actual_first_in': firstIn,
  'actual_last_out': lastOut,
  ...over,
});

void main() {
  group('mismatchOf', () {
    test('is null for a fine day and for flags that only inform', () {
      expect(mismatchOf(_day('PRESENT')), isNull);
      expect(mismatchOf(_day('PRESENT', over: {'is_late': true, 'late_minutes': 20, 'is_early_out': true, 'is_overtime': true})), isNull);
      // Nothing punched and not flagged is "not checked in", handled by Mark present.
      expect(mismatchOf(_day('ABSENT', firstIn: null, lastOut: null)), isNull);
    });

    test('names a check-in with no check-out, and the reverse', () {
      final out = mismatchOf(_day('INCOMPLETE', lastOut: null, over: {'missing_punch': true}));
      expect(out?.kind, MismatchKind.missingOut);
      expect(out?.reason, 'Checked in but never checked out.');
      expect(mismatchOf(_day('INCOMPLETE', firstIn: null, over: {'missing_punch': true}))?.kind, MismatchKind.missingIn);
    });

    test('says nothing was punched when an incomplete day has no punches at all', () {
      final m = mismatchOf(_day('INCOMPLETE', firstIn: null, lastOut: null, over: {'missing_punch': true}));
      expect(m?.kind, MismatchKind.noPunches);
      expect(m?.reason, 'Nothing was punched on a working day.');
    });

    test('calls an incomplete day with both punches incomplete', () {
      expect(mismatchOf(_day('INCOMPLETE'))?.kind, MismatchKind.incomplete);
    });

    test('flags work on approved leave only until HR has decided', () {
      expect(mismatchOf(_day('PRESENT', over: {'work_on_leave_flagged': true, 'work_on_leave_resolution': null}))?.kind, MismatchKind.workOnLeave);
      expect(mismatchOf(_day('PRESENT', over: {'work_on_leave_flagged': true, 'work_on_leave_resolution': 'KEEP_LEAVE'})), isNull);
    });

    test('flags a config error and a day waiting on approval', () {
      expect(mismatchOf(_day('CONFIG_ERROR'))?.kind, MismatchKind.configError);
      expect(mismatchOf(_day('PRESENT', over: {'is_pending_approval': true}))?.kind, MismatchKind.pendingApproval);
    });

    test('puts what blocks calculation ahead of the punches', () {
      expect(mismatchOf(_day('CONFIG_ERROR', lastOut: null, over: {'missing_punch': true}))?.kind, MismatchKind.configError);
    });
  });

  group('attentionRank', () {
    test('orders fix, chase, note, fine', () {
      final fix = attentionRank(_day('INCOMPLETE', lastOut: null, over: {'missing_punch': true}));
      final chase = attentionRank(_day('ABSENT', firstIn: null, lastOut: null));
      final note = attentionRank(_day('PRESENT', over: {'is_late': true, 'late_minutes': 5}));
      final fine = attentionRank(_day('PRESENT'));
      expect([fix, chase, note, fine], [0, 1, 2, 3]);
    });

    test('a day only waiting on approval is noted, not a fix-first row', () {
      expect(attentionRank(_day('PRESENT', over: {'is_pending_approval': true})), 2);
    });
  });
}
