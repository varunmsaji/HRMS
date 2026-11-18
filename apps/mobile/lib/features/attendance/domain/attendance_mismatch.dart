import '../data/attendance_repository.dart';
import '../presentation/attendance_summary.dart' show attendanceBucketOf;
import 'attendance_insights.dart' show isLate, workOnLeaveUnresolved;

/// What is wrong with a day that HR can act on. Informational flags (late, early out, overtime)
/// are not mismatches: nothing needs fixing, only noting. Mirrors web
/// `apps/web/src/lib/attendance/mismatch.ts`.
enum MismatchKind { configError, workOnLeave, missingOut, missingIn, noPunches, incomplete, pendingApproval }

class Mismatch {
  const Mismatch(this.kind, this.reason);
  final MismatchKind kind;

  /// One plain-language line for the list.
  final String reason;
}

/// The single most important problem with a day, or null when the day is fine. Order matters: a
/// day that cannot be calculated or conflicts with leave must be settled before its punches are.
Mismatch? mismatchOf(AttendanceDay d) {
  if (attendanceBucketOf(d) == 'CONFIG_ERROR') {
    return const Mismatch(MismatchKind.configError, "Can't be calculated: the shift or policy is missing.");
  }
  if (workOnLeaveUnresolved(d)) {
    return const Mismatch(MismatchKind.workOnLeave, 'Punched in on a day of approved leave.');
  }
  final incomplete = d.attendanceStatus == 'INCOMPLETE';
  if (d.raw['missing_punch'] == true || incomplete) {
    final hasIn = d.actualFirstIn != null;
    final hasOut = d.actualLastOut != null;
    if (!hasIn && !hasOut) return const Mismatch(MismatchKind.noPunches, 'Nothing was punched on a working day.');
    if (hasIn && !hasOut) return const Mismatch(MismatchKind.missingOut, 'Checked in but never checked out.');
    if (!hasIn && hasOut) return const Mismatch(MismatchKind.missingIn, 'Checked out with no check-in.');
    return const Mismatch(MismatchKind.incomplete, "Punches don't add up to a full day.");
  }
  if (d.raw['is_pending_approval'] == true) return const Mismatch(MismatchKind.pendingApproval, 'Waiting for an approval.');
  return null;
}

/// Lower sorts first: days HR has to fix or chase come before days that are simply fine.
int attentionRank(AttendanceDay d) {
  if (mismatchOf(d) case final m? when m.kind != MismatchKind.pendingApproval) return 0;
  if (d.attendanceStatus == 'ABSENT') return 1;
  if (isLate(d) || d.raw['is_early_out'] == true || d.raw['is_pending_approval'] == true) return 2;
  return 3;
}
