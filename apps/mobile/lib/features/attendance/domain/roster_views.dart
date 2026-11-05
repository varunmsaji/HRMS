/// Pure helpers for the Shift board and the Workforce roster, with the same rules as the web's
/// `rosters/board`, `rosters/grid` and `lib/shift-roster/coverage.ts`.
class RosterEntry {
  const RosterEntry({required this.id, required this.employeeId, required this.date, required this.status, required this.version, required this.isWeekOff, required this.isHolidayWorking, required this.raw, this.shiftId});

  factory RosterEntry.fromJson(Map<String, dynamic> j) => RosterEntry(
        id: j['id'] as String,
        employeeId: j['employee_id'] as String,
        date: j['roster_date'] as String,
        shiftId: j['shift_id'] as String?,
        isWeekOff: j['is_week_off_override'] as bool? ?? false,
        isHolidayWorking: j['is_holiday_working_override'] as bool? ?? false,
        status: j['status'] as String,
        version: j['version'] as int,
        raw: j,
      );

  final String id;
  final String employeeId;
  final String date;
  final String? shiftId;
  final bool isWeekOff;
  final bool isHolidayWorking;
  final String status;
  final int version;

  /// The row as the API sent it, for the edit form.
  final Map<String, dynamic> raw;

  bool get isDraft => status == 'DRAFT';
}

class RosterShift {
  const RosterShift({required this.id, required this.name, this.code, this.isNight = false});

  factory RosterShift.fromJson(Map<String, dynamic> j) => RosterShift(
        id: j['id'] as String,
        name: j['name'] as String,
        code: j['code'] as String?,
        isNight: j['is_night_shift'] as bool? ?? false,
      );

  final String id;
  final String name;
  final String? code;
  final bool isNight;

  String get shortLabel => code ?? name;

  /// A stable index per shift, so a pattern reads at a glance. Same hash as the web.
  int toneIndex(int tones) {
    var h = 0;
    for (final c in id.codeUnits) {
      h = (h * 31 + c) & 0xffffffff;
    }
    return h % tones;
  }
}

/// No roster entry for the day: the employee's default shift applies.
const unassignedColumn = '__unassigned__';
const weekOffColumn = '__week_off__';

String boardColumnOf(RosterEntry? entry) {
  if (entry == null) return unassignedColumn;
  if (entry.isWeekOff) return weekOffColumn;
  return entry.shiftId ?? unassignedColumn;
}

/// "OFF", a shift's short label, or that label with a star on a working holiday.
String rosterCellLabel(RosterEntry entry, Map<String, RosterShift> shifts) {
  if (entry.isWeekOff) return 'OFF';
  final shift = entry.shiftId == null ? null : shifts[entry.shiftId];
  final name = shift?.shortLabel ?? '—';
  return entry.isHolidayWorking ? '$name*' : name;
}

class CoverageRow {
  CoverageRow({required this.key, required this.label, required this.isOff});
  final String key;
  final String label;
  final bool isOff;
  final byDate = <String, int>{};
  final _who = <String>{};

  /// Distinct employees on this row anywhere in the range.
  int get people => _who.length;
}

/// Headcount per shift per day, straight from the entries. An entry with neither a shift nor a
/// week-off override has nothing to count and is skipped.
List<CoverageRow> buildRosterCoverage(List<RosterEntry> entries, List<String> dates, Map<String, RosterShift> shifts) {
  final inRange = dates.toSet();
  final rows = <String, CoverageRow>{};
  for (final e in entries) {
    if (!inRange.contains(e.date)) continue;
    if (!e.isWeekOff && e.shiftId == null) continue;
    final key = e.isWeekOff ? 'OFF' : e.shiftId!;
    final row = rows.putIfAbsent(key, () => CoverageRow(key: key, label: e.isWeekOff ? 'Week off' : (shifts[key]?.name ?? 'Unknown shift'), isOff: e.isWeekOff));
    row.byDate[e.date] = (row.byDate[e.date] ?? 0) + 1;
    row._who.add(e.employeeId);
  }
  return rows.values.toList()
    ..sort((a, b) {
      if (a.isOff != b.isOff) return a.isOff ? 1 : -1;
      final people = b.people.compareTo(a.people);
      return people != 0 ? people : a.label.compareTo(b.label);
    });
}

String _iso(DateTime d) => '${d.year.toString().padLeft(4, '0')}-${d.month.toString().padLeft(2, '0')}-${d.day.toString().padLeft(2, '0')}';

/// All in UTC, so a device's timezone can never move a date.
String addDaysIso(String iso, int days) => _iso(DateTime.parse('${iso}T00:00:00Z').add(Duration(days: days)));

String mondayOfIso(String iso) => addDaysIso(iso, 1 - DateTime.parse('${iso}T00:00:00Z').weekday);

const _months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
const _days = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];

/// "5 Nov 2026".
String formatShortDate(String iso) {
  final d = DateTime.parse('${iso}T00:00:00Z');
  return '${d.day} ${_months[d.month - 1]} ${d.year}';
}

/// "Thu 5/11", for a column heading.
({String weekday, String date, bool weekend}) gridDayHeading(String iso) {
  final d = DateTime.parse('${iso}T00:00:00Z');
  return (weekday: _days[d.weekday - 1], date: '${d.day}/${d.month}', weekend: d.weekday >= DateTime.saturday);
}
