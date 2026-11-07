/// The weekly operational schedule (`GET /rosters/weekly-schedule`) and shift-swap requests
/// (`/rosters/swap-requests`) — mirrors `apps/web/src/lib/shift-roster/schedule.ts`.
library;

class SchedulePerson {
  const SchedulePerson({required this.id, required this.name, required this.initials});
  final String id;
  final String name;
  final String initials;

  factory SchedulePerson.fromJson(Map<String, dynamic> j) => SchedulePerson(id: j['id'] as String, name: j['name'] as String, initials: (j['initials'] as String?) ?? '?');
}

class ScheduleCell {
  const ScheduleCell({required this.date, required this.count, required this.met, required this.people, required this.hasPendingSwap});
  final String date;
  final int count;

  /// Null when the shift has no staffing target.
  final bool? met;
  final List<SchedulePerson> people;
  final bool hasPendingSwap;

  /// People on the shift beyond the names the API sends.
  int get hidden => count - people.length;

  factory ScheduleCell.fromJson(Map<String, dynamic> j) => ScheduleCell(
        date: j['date'] as String,
        count: j['count'] as int,
        met: j['met'] as bool?,
        people: [for (final p in (j['people'] as List? ?? const [])) SchedulePerson.fromJson(p as Map<String, dynamic>)],
        hasPendingSwap: (j['has_pending_swap'] as bool?) ?? false,
      );
}

class ScheduleShift {
  const ScheduleShift({
    required this.id,
    required this.name,
    this.code,
    this.startTime,
    this.endTime,
    required this.isNight,
    required this.weeklyHours,
    this.minStaff,
    required this.peakStaff,
    required this.departments,
    required this.daysBelowTarget,
    required this.cells,
  });
  final String id;
  final String name;
  final String? code;
  final String? startTime;
  final String? endTime;
  final bool isNight;
  final double weeklyHours;
  final int? minStaff;
  final int peakStaff;
  final List<String> departments;
  final int daysBelowTarget;
  final List<ScheduleCell> cells;

  ScheduleCell? cellOn(String date) {
    for (final c in cells) {
      if (c.date == date) return c;
    }
    return null;
  }

  /// "09:00 – 17:00", or empty when the shift has no published timings.
  String get timeRange => (startTime == null || endTime == null) ? '' : '${_hhmm(startTime!)} – ${_hhmm(endTime!)}';

  factory ScheduleShift.fromJson(Map<String, dynamic> j) => ScheduleShift(
        id: j['id'] as String,
        name: j['name'] as String,
        code: j['code'] as String?,
        startTime: j['start_time'] as String?,
        endTime: j['end_time'] as String?,
        isNight: (j['is_night_shift'] as bool?) ?? false,
        weeklyHours: ((j['weekly_hours'] as num?) ?? 0).toDouble(),
        minStaff: j['min_staff'] as int?,
        peakStaff: (j['peak_staff'] as int?) ?? 0,
        departments: [for (final d in (j['departments'] as List? ?? const [])) d as String],
        daysBelowTarget: (j['days_below_target'] as int?) ?? 0,
        cells: [for (final c in (j['cells'] as List? ?? const [])) ScheduleCell.fromJson(c as Map<String, dynamic>)],
      );
}

class ScheduleTotals {
  const ScheduleTotals({
    required this.activeHeadcount,
    required this.rosteredStaff,
    this.coveragePct,
    required this.shiftsWithTarget,
    required this.cellsBelowTarget,
    required this.pendingSwaps,
    required this.allocatedHours,
    this.nightStaff = 0,
    this.nightShiftCount = 0,
  });
  final int activeHeadcount;
  final int rosteredStaff;

  /// Null when no shift has a target.
  final double? coveragePct;
  final int shiftsWithTarget;
  final int cellsBelowTarget;
  final int pendingSwaps;
  final double allocatedHours;

  /// People rostered on a night shift this week, and how many night shifts exist.
  final int nightStaff;
  final int nightShiftCount;

  /// Share of active headcount with a shift this week, rounded (web `scheduledPct`).
  int get scheduledPct => activeHeadcount > 0 ? (100 * rosteredStaff / activeHeadcount).round() : 0;

  factory ScheduleTotals.fromJson(Map<String, dynamic> j) => ScheduleTotals(
        activeHeadcount: (j['active_headcount'] as int?) ?? 0,
        rosteredStaff: (j['rostered_staff'] as int?) ?? 0,
        coveragePct: (j['coverage_pct'] as num?)?.toDouble(),
        shiftsWithTarget: (j['shifts_with_target'] as int?) ?? 0,
        cellsBelowTarget: (j['cells_below_target'] as int?) ?? 0,
        pendingSwaps: (j['pending_swaps'] as int?) ?? 0,
        allocatedHours: ((j['allocated_hours'] as num?) ?? 0).toDouble(),
        nightStaff: (j['night_staff'] as int?) ?? 0,
        nightShiftCount: (j['night_shift_count'] as int?) ?? 0,
      );
}

class WeeklySchedule {
  const WeeklySchedule({required this.weekStart, required this.weekEnd, required this.days, required this.shifts, required this.totals});
  final String weekStart;
  final String weekEnd;
  final List<String> days;
  final List<ScheduleShift> shifts;
  final ScheduleTotals totals;

  /// Shifts that have at least one person on [date], most staffed first.
  List<({ScheduleShift shift, ScheduleCell cell})> onDay(String date) {
    final out = <({ScheduleShift shift, ScheduleCell cell})>[];
    for (final s in shifts) {
      final c = s.cellOn(date);
      if (c != null && c.count > 0) out.add((shift: s, cell: c));
    }
    out.sort((a, b) => b.cell.count.compareTo(a.cell.count));
    return out;
  }

  factory WeeklySchedule.fromJson(Map<String, dynamic> j) => WeeklySchedule(
        weekStart: j['week_start'] as String,
        weekEnd: j['week_end'] as String,
        days: [for (final d in (j['days'] as List? ?? const [])) d as String],
        shifts: [for (final s in (j['shifts'] as List? ?? const [])) ScheduleShift.fromJson(s as Map<String, dynamic>)],
        totals: ScheduleTotals.fromJson(j['totals'] as Map<String, dynamic>),
      );
}

class SwapParty {
  const SwapParty({required this.employeeId, required this.name, required this.code, this.department, required this.shiftName, this.shiftStart, this.shiftEnd});
  final String employeeId;
  final String name;
  final String code;
  final String? department;
  final String shiftName;
  final String? shiftStart;
  final String? shiftEnd;

  String get shiftLabel => (shiftStart == null || shiftEnd == null) ? shiftName : '$shiftName (${_hhmm(shiftStart!)}–${_hhmm(shiftEnd!)})';

  factory SwapParty.fromJson(Map<String, dynamic> j) => SwapParty(
        employeeId: j['employee_id'] as String,
        name: j['name'] as String,
        code: (j['code'] as String?) ?? '',
        department: j['department'] as String?,
        shiftName: j['shift_name'] as String,
        shiftStart: j['shift_start'] as String?,
        shiftEnd: j['shift_end'] as String?,
      );
}

class SwapRequest {
  const SwapRequest({
    required this.id,
    required this.reference,
    required this.swapDate,
    required this.status,
    this.reason,
    required this.counterpartConsented,
    required this.coverageOk,
    required this.requester,
    required this.counterpart,
    this.decisionNote,
  });
  final String id;
  final String reference;
  final String swapDate;
  final String status;
  final String? reason;
  final bool counterpartConsented;
  final bool coverageOk;
  final SwapParty requester;
  final SwapParty counterpart;
  final String? decisionNote;

  bool get isPending => status == 'PENDING';
  bool isRequester(String? employeeId) => employeeId != null && requester.employeeId == employeeId;
  bool isCounterpart(String? employeeId) => employeeId != null && counterpart.employeeId == employeeId;

  /// The colleague still has to agree and it is [employeeId] who must answer.
  bool needsAnswerFrom(String? employeeId) => isPending && !counterpartConsented && isCounterpart(employeeId);

  factory SwapRequest.fromJson(Map<String, dynamic> j) => SwapRequest(
        id: j['id'] as String,
        reference: j['reference'] as String,
        swapDate: j['swap_date'] as String,
        status: j['status'] as String,
        reason: j['reason'] as String?,
        counterpartConsented: (j['counterpart_consented'] as bool?) ?? false,
        coverageOk: (j['coverage_ok'] as bool?) ?? true,
        requester: SwapParty.fromJson(j['requester'] as Map<String, dynamic>),
        counterpart: SwapParty.fromJson(j['counterpart'] as Map<String, dynamic>),
        decisionNote: j['decision_note'] as String?,
      );
}

/// A colleague the caller could swap with on one day (`GET /rosters/swap-candidates`).
class SwapCandidate {
  const SwapCandidate({required this.employeeId, required this.name, required this.code, this.department, required this.shiftName});
  final String employeeId;
  final String name;
  final String code;
  final String? department;
  final String shiftName;

  factory SwapCandidate.fromJson(Map<String, dynamic> j) => SwapCandidate(
        employeeId: j['employee_id'] as String,
        name: j['name'] as String,
        code: (j['code'] as String?) ?? '',
        department: j['department'] as String?,
        shiftName: j['shift_name'] as String,
      );
}

String _hhmm(String t) => t.length >= 5 ? t.substring(0, 5) : t;

const _weekdays = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
const _months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

/// "Mon" for an ISO date.
String weekdayShort(String iso) => _weekdays[DateTime.parse(iso).weekday - 1];

/// "10 Nov" for an ISO date.
String dayMonth(String iso) {
  final d = DateTime.parse(iso);
  return '${d.day} ${_months[d.month - 1]}';
}

/// "Mon 10 Nov".
String longDay(String iso) => '${weekdayShort(iso)} ${dayMonth(iso)}';

/// "10 Nov – 16 Nov".
String weekRangeLabel(String start, String end) => '${dayMonth(start)} – ${dayMonth(end)}';

/// The Monday on or before [iso].
String mondayOf(String iso) => addDaysIso(iso, -(DateTime.parse(iso).weekday - 1));

String addDaysIso(String iso, int days) {
  final d = DateTime.utc(DateTime.parse(iso).year, DateTime.parse(iso).month, DateTime.parse(iso).day).add(Duration(days: days));
  return '${d.year.toString().padLeft(4, '0')}-${d.month.toString().padLeft(2, '0')}-${d.day.toString().padLeft(2, '0')}';
}
