/// Pure logic for the two calendar views web has and mobile lacked: a work calendar's month of day
/// types (web `components/work-calendar/day-grid.tsx`) and a holiday calendar's year (web
/// `components/holiday-calendar/holiday-year-calendar.tsx`). Both only show what the server
/// already classified; nothing here decides what kind of day a date is.
library;

typedef Rec = Map<String, dynamic>;

DateTime _utc(String iso) => DateTime.utc(int.parse(iso.substring(0, 4)), int.parse(iso.substring(5, 7)), int.parse(iso.substring(8, 10)));

String isoOf(DateTime d) => '${d.year.toString().padLeft(4, '0')}-${d.month.toString().padLeft(2, '0')}-${d.day.toString().padLeft(2, '0')}';

/// How one day of a work calendar is shown (web `presentDay`).
class DayPresentation {
  const DayPresentation(this.key, this.glyph, this.label, this.detail);

  /// SHUTDOWN, HOLIDAY, WEEKLY_OFF, SPECIAL_WORKING, WORKING, WORKING_OPTIONAL,
  /// WORKING_RESTRICTED or WORKING_HOLIDAY.
  final String key;
  final String glyph;
  final String label;
  final String? detail;
}

/// A named optional or restricted holiday on a WORKING day is shown as working, matching the
/// server's resolver.
DayPresentation presentDay(Rec day) {
  final type = day['day_type'];
  final holiday = day['holiday_name'] as String?;
  if (type == 'SHUTDOWN') return DayPresentation('SHUTDOWN', '✕', 'Shutdown', holiday);
  if (type == 'HOLIDAY') return DayPresentation('HOLIDAY', '★', 'Holiday', holiday);
  if (type == 'WEEKLY_OFF') {
    final fraction = double.tryParse('${day['weekly_off_fraction']}');
    final half = fraction != null && fraction < 1;
    return DayPresentation('WEEKLY_OFF', '○', half ? 'Half-day weekly off' : 'Weekly off', day['holiday_on_weekly_off'] == true ? '${holiday ?? 'Holiday'} (on weekly off)' : null);
  }
  if (type == 'SPECIAL_WORKING') return DayPresentation('SPECIAL_WORKING', '◆', 'Special working day', holiday);
  final optional = day['optional_holiday_name'] as String?;
  final restricted = day['restricted_holiday_name'] as String?;
  final named = optional ?? restricted ?? holiday;
  if (optional != null) return DayPresentation('WORKING_OPTIONAL', '·', 'Working', 'Optional holiday: $named (still a working day)');
  if (restricted != null) return DayPresentation('WORKING_RESTRICTED', '·', 'Working', 'Restricted holiday: $named (still a working day)');
  if (day['is_holiday_named'] == true) return DayPresentation('WORKING_HOLIDAY', '·', 'Working', '$named (working holiday)');
  return const DayPresentation('WORKING', '·', 'Working', null);
}

/// Web's legend, in order: glyph, label, and the presentation key it stands for.
const dayLegend = [
  ('·', 'Working day', 'WORKING'),
  ('○', 'Weekly off', 'WEEKLY_OFF'),
  ('★', 'Holiday (non-working)', 'HOLIDAY'),
  ('◆', 'Special working day', 'SPECIAL_WORKING'),
  ('✕', 'Shutdown', 'SHUTDOWN'),
];

/// Whole Monday-first weeks around a month: what web asks `/work-calendars/{id}/days` for (at
/// most 42 days, one request).
({String from, String to}) monthGridRange(int year, int month) {
  final first = DateTime.utc(year, month, 1);
  final last = DateTime.utc(year, month + 1, 0);
  return (from: isoOf(first.subtract(Duration(days: first.weekday - 1))), to: isoOf(last.add(Duration(days: 7 - last.weekday))));
}

/// Whole Monday-first weeks covering [first]..[last] (web `DayGrid`'s grid bounds).
({String from, String to}) weekRange(String first, String last) {
  final a = _utc(first);
  final b = _utc(last);
  return (from: isoOf(a.subtract(Duration(days: a.weekday - 1))), to: isoOf(b.add(Duration(days: 7 - b.weekday))));
}

/// Every date from [from] to [to] (both whole weeks), in order.
List<String> gridDates(String from, String to) {
  final out = <String>[];
  for (var d = _utc(from); !d.isAfter(_utc(to)); d = d.add(const Duration(days: 1))) {
    out.add(isoOf(d));
  }
  return out;
}

const monthNames = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'];

/// One month of a year view: leading blanks (null) for a Monday-first week, then each day.
List<int?> yearMonthCells(int year, int month) {
  final offset = DateTime.utc(year, month, 1).weekday - 1;
  final days = DateTime.utc(year, month + 1, 0).day;
  return [for (var i = 0; i < offset; i++) null, for (var d = 1; d <= days; d++) d];
}

/// Active holidays by date; inactive ones are not shown (web drops `is_active: false`).
Map<String, List<Rec>> holidaysByDate(List<Rec> holidays) {
  final out = <String, List<Rec>>{};
  for (final h in holidays) {
    if (h['is_active'] == false) continue;
    out.putIfAbsent('${h['date']}', () => []).add(h);
  }
  return out;
}
