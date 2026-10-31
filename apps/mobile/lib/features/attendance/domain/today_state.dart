import '../../../core/time.dart';
import '../data/attendance_repository.dart';

/// What "today" looks like for an employee, decided from the two existing reads (their recent
/// punches and today's calculated day, if any). Pure: no network, no clock, no device zone.
///
/// The rules are docs/design/employee-mobile/EMPLOYEE_MOBILE_FINAL_API_AND_PERMISSION_MATRIX.md
/// §5.3. The invariant behind all of them: **never invent a status from missing data.** A day row
/// is created only by a punch, the 09:30 IST sweep or HR, so "no row" is not "absent", and a row
/// the sweep wrote before the employee punched is provisional.
enum TodayStateKind {
  /// 0. The account has no employee record.
  noEmployee,

  /// 1. Nothing has loaded yet.
  loading,

  /// 2. Punches loaded and empty, and no day row: nothing recorded yet.
  noData,

  /// 3. Not punched in yet. Any `ABSENT`/`INCOMPLETE` row for today is provisional and not shown.
  notPunchedIn,

  /// 4. Newest punch is IN and the day row has caught up with it.
  punchedIn,

  /// 5. Newest punch is OUT and the day row has caught up with it.
  punchedOut,

  /// 6. A punch exists but the day row is missing or older than that punch.
  calculating,

  /// 7. The engine reported `CONFIG_ERROR`.
  calculationFailed,

  /// 8. Holiday or weekly off (`NOT_EXPECTED`).
  notWorkingDay,

  /// 9. Approved leave.
  onLeave,

  /// 10. Neither read worked.
  unavailable,

  /// 11. Punches could not be read but a day row exists: its facts, no direction hint.
  partial,

  /// 12. A definite status with no punch behind it (on duty, WFH, regularized, or a locked day).
  recorded,

  /// 13. `NOT_JOINED` / `EXITED`.
  notEmployed,
}

/// Which punch the screen should make primary. Both directions stay reachable regardless: the
/// server accepts either, and a forgotten punch-out must not trap the employee.
enum LikelyPunch { punchIn, punchOut, equal }

class TodayState {
  const TodayState({
    required this.kind,
    required this.likely,
    this.lastPunch,
    this.lastPunchDay = PunchDay.today,
    this.day,
    this.showRowStatus = false,
    this.showWorked = false,
  });

  final TodayStateKind kind;
  final LikelyPunch likely;

  /// The newest punch in the window (any date), if the punch read worked.
  final Punch? lastPunch;
  final PunchDay lastPunchDay;

  /// Today's day row when it is usable for display; null when it must not be shown.
  final AttendanceDay? day;

  /// Whether the row's status chip may be shown (never for provisional or stale rows).
  final bool showRowStatus;

  /// Whether the row's `worked_minutes` is current (the row is not older than the last punch).
  final bool showWorked;
}

/// When the newest punch happened relative to the business date.
enum PunchDay { today, yesterday, earlier }

/// [punches] is null when the punch read failed; [day] is today's row (null if there is none).
/// [dayFailed] says the day read failed (so "no row" would be a guess).
TodayState resolveTodayState({
  required bool hasEmployee,
  required bool loading,
  required List<Punch>? punches,
  required AttendanceDay? day,
  required bool dayFailed,
  required String zone,
  required String today,
}) {
  if (!hasEmployee) return const TodayState(kind: TodayStateKind.noEmployee, likely: LikelyPunch.equal);
  if (loading) return const TodayState(kind: TodayStateKind.loading, likely: LikelyPunch.equal);

  final punchesOk = punches != null;
  final last = _newest(punches);
  final likely = !punchesOk ? LikelyPunch.equal : (last?.direction == 'IN' ? LikelyPunch.punchOut : LikelyPunch.punchIn);
  final lastDate = last == null ? null : dateInZone(last.punchTime, zone);
  final lastDay = _punchDay(lastDate, today);

  TodayState state(TodayStateKind kind, {AttendanceDay? row, bool status = false, bool worked = false}) =>
      TodayState(kind: kind, likely: likely, lastPunch: last, lastPunchDay: lastDay, day: row, showRowStatus: status, showWorked: worked);

  // The engine's own verdicts come first: they are explicit, not inferred.
  if (day != null) {
    switch (day.attendanceStatus) {
      case 'CONFIG_ERROR':
        return state(TodayStateKind.calculationFailed, row: day, status: true);
      case 'NOT_JOINED':
      case 'EXITED':
        return state(TodayStateKind.notEmployed, row: day);
      case 'NOT_EXPECTED':
        return state(TodayStateKind.notWorkingDay, row: day, status: true);
      case 'LEAVE':
        return state(TodayStateKind.onLeave, row: day, status: true);
    }
  }

  if (!punchesOk) {
    if (day != null) return state(TodayStateKind.partial, row: day, status: true, worked: true);
    return state(TodayStateKind.unavailable);
  }

  // An OUT from an earlier date is yesterday's closed day, not a punch today. An IN is always
  // "open", whatever its date (overnight shift, or a punch-out that was forgotten).
  final hasOpenOrTodayPunch = last != null && (last.direction == 'IN' || lastDay == PunchDay.today);

  if (hasOpenOrTodayPunch) {
    // An IN from an earlier date has no row of ours to compare with (today's row belongs to a
    // different attendance date): report the open punch and claim nothing about calculation.
    if (last.direction == 'IN' && lastDay != PunchDay.today) return state(TodayStateKind.punchedIn);
    final fresh = day != null && _calculatedAtOrAfter(day, last);
    if (!fresh) return state(TodayStateKind.calculating);
    return last.direction == 'IN'
        ? state(TodayStateKind.punchedIn, row: day, worked: true)
        : state(TodayStateKind.punchedOut, row: day, status: true, worked: true);
  }

  // No punch today.
  if (day == null) {
    // Without a row this is a fact about missing data, not about the employee. If the day read
    // itself failed we cannot even say that.
    return dayFailed ? state(TodayStateKind.unavailable) : state(TodayStateKind.noData);
  }
  final provisional = (day.attendanceStatus == 'ABSENT' || day.attendanceStatus == 'INCOMPLETE') && day.actualFirstIn == null && !day.isLocked;
  if (provisional) return state(TodayStateKind.notPunchedIn);
  return state(TodayStateKind.recorded, row: day, status: true, worked: true);
}

Punch? _newest(List<Punch>? punches) {
  if (punches == null || punches.isEmpty) return null;
  Punch? best;
  DateTime? bestAt;
  for (final p in punches) {
    final at = DateTime.tryParse(p.punchTime);
    if (at == null) continue;
    if (bestAt == null || at.isAfter(bestAt)) {
      best = p;
      bestAt = at;
    }
  }
  return best;
}

PunchDay _punchDay(String? punchDate, String today) {
  if (punchDate == null || punchDate == today) return PunchDay.today;
  final t = DateTime.tryParse(today);
  final p = DateTime.tryParse(punchDate);
  if (t == null || p == null) return PunchDay.earlier;
  return t.difference(p).inDays == 1 ? PunchDay.yesterday : PunchDay.earlier;
}

/// Both are server timestamps; this compares them, it does not calculate attendance.
bool _calculatedAtOrAfter(AttendanceDay day, Punch last) {
  final calculated = DateTime.tryParse((day.raw['calculated_at'] as String?) ?? '');
  final punched = DateTime.tryParse(last.punchTime);
  if (calculated == null || punched == null) return false;
  return !calculated.isBefore(punched);
}

/// The `date_from`/`date_to` for `GET /attendance/punches` that surely covers "now" and an open
/// overnight punch. The API filters on **UTC** calendar days, not the company zone, so the window
/// is widened one day each way; the resolver then works in the company zone. (A future-dated
/// punch cannot exist: self punches carry server time.)
({String from, String to}) todayPunchWindow(String zone, {DateTime? now}) => (from: businessDayOffset(zone, -1, now: now), to: businessDayOffset(zone, 1, now: now));
