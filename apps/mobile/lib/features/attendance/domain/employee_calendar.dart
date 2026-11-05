/// `GET /employee-calendar/me` (`apps/api/.../organisation/employee_calendar.py`), and the same
/// labels as the web's `presentDay` and `presentLeave`. The app never decides what kind of day it
/// is; it only labels what the server said.
class EmployeeCalendarLeave {
  const EmployeeCalendarLeave({required this.status, required this.fraction, this.half});

  factory EmployeeCalendarLeave.fromJson(Map<String, dynamic> json) => EmployeeCalendarLeave(
        status: json['status'] as String,
        fraction: double.tryParse('${json['fraction']}') ?? 1,
        half: json['half'] as String?,
      );

  final String status;
  final double fraction;
  final String? half;

  bool get isApproved => status == 'APPROVED';

  String get label {
    final part = switch (half) {
      'FIRST_HALF' => ' (first half)',
      'SECOND_HALF' => ' (second half)',
      _ => fraction < 1 ? ' (half day)' : '',
    };
    return '${isApproved ? 'Approved' : 'Pending'} leave$part';
  }
}

enum CalendarDayKind { working, weeklyOff, holiday, specialWorking, shutdown, notSetUp }

class EmployeeCalendarDay {
  const EmployeeCalendarDay({
    required this.date,
    required this.configured,
    this.dayType,
    this.holidayName,
    this.holidayOnWeeklyOff = false,
    this.isHolidayNamed = false,
    this.optionalHolidayName,
    this.restrictedHolidayName,
    this.weeklyOffFraction,
    this.leave = const [],
  });

  factory EmployeeCalendarDay.fromJson(Map<String, dynamic> json) => EmployeeCalendarDay(
        date: json['date'] as String,
        configured: json['configured'] as bool,
        dayType: json['day_type'] as String?,
        holidayName: json['holiday_name'] as String?,
        holidayOnWeeklyOff: json['holiday_on_weekly_off'] as bool? ?? false,
        isHolidayNamed: json['is_holiday_named'] as bool? ?? false,
        optionalHolidayName: json['optional_holiday_name'] as String?,
        restrictedHolidayName: json['restricted_holiday_name'] as String?,
        weeklyOffFraction: json['weekly_off_fraction'] == null ? null : double.tryParse('${json['weekly_off_fraction']}'),
        leave: [for (final l in (json['leave'] as List? ?? const [])) EmployeeCalendarLeave.fromJson(l as Map<String, dynamic>)],
      );

  final String date;
  final bool configured;
  final String? dayType;
  final String? holidayName;
  final bool holidayOnWeeklyOff;
  final bool isHolidayNamed;
  final String? optionalHolidayName;
  final String? restrictedHolidayName;
  final double? weeklyOffFraction;
  final List<EmployeeCalendarLeave> leave;

  /// An unresolved date is never treated as a working day.
  CalendarDayKind get kind {
    if (!configured || dayType == null) return CalendarDayKind.notSetUp;
    return switch (dayType) {
      'SHUTDOWN' => CalendarDayKind.shutdown,
      'HOLIDAY' => CalendarDayKind.holiday,
      'WEEKLY_OFF' => CalendarDayKind.weeklyOff,
      'SPECIAL_WORKING' => CalendarDayKind.specialWorking,
      _ => CalendarDayKind.working,
    };
  }

  String get label => switch (kind) {
        CalendarDayKind.notSetUp => 'Not set up',
        CalendarDayKind.shutdown => 'Shutdown',
        CalendarDayKind.holiday => 'Holiday',
        CalendarDayKind.weeklyOff => weeklyOffFraction != null && weeklyOffFraction! < 1 ? 'Half-day weekly off' : 'Weekly off',
        CalendarDayKind.specialWorking => 'Special working day',
        CalendarDayKind.working => 'Working',
      };

  String? get detail {
    switch (kind) {
      case CalendarDayKind.notSetUp:
        return null;
      case CalendarDayKind.shutdown:
      case CalendarDayKind.holiday:
      case CalendarDayKind.specialWorking:
        return holidayName;
      case CalendarDayKind.weeklyOff:
        return holidayOnWeeklyOff ? '${holidayName ?? 'Holiday'} (on weekly off)' : null;
      case CalendarDayKind.working:
        if (optionalHolidayName != null) return 'Optional holiday: $optionalHolidayName (still a working day)';
        if (restrictedHolidayName != null) return 'Restricted holiday: $restrictedHolidayName (still a working day)';
        if (isHolidayNamed) return '$holidayName (working holiday)';
        return null;
    }
  }
}

class EmployeeCalendar {
  const EmployeeCalendar({required this.fromDate, required this.toDate, required this.configuration, required this.leaveIncluded, required this.days});

  factory EmployeeCalendar.fromJson(Map<String, dynamic> json) => EmployeeCalendar(
        fromDate: json['from_date'] as String,
        toDate: json['to_date'] as String,
        configuration: json['configuration'] as String,
        leaveIncluded: json['leave_included'] as bool,
        days: [for (final d in (json['days'] as List? ?? const [])) EmployeeCalendarDay.fromJson(d as Map<String, dynamic>)],
      );

  final String fromDate;
  final String toDate;

  /// COMPLETE, PARTIAL or INCOMPLETE.
  final String configuration;
  final bool leaveIncluded;
  final List<EmployeeCalendarDay> days;
}

/// The counts above the grid, for the days of [monthKey] (`YYYY-MM`) only.
({int working, int nonWorking, int approvedLeave, int pendingLeave}) summariseCalendarMonth(EmployeeCalendar calendar, String monthKey) {
  final inMonth = calendar.days.where((d) => d.date.startsWith(monthKey));
  bool off(EmployeeCalendarDay d) => d.dayType == 'WEEKLY_OFF' || d.dayType == 'HOLIDAY' || d.dayType == 'SHUTDOWN';
  return (
    working: inMonth.where((d) => d.configured && !off(d)).length,
    nonWorking: inMonth.where(off).length,
    approvedLeave: inMonth.where((d) => d.leave.any((l) => l.isApproved)).length,
    pendingLeave: inMonth.where((d) => d.leave.any((l) => !l.isApproved)).length,
  );
}

String _iso(DateTime d) => '${d.year.toString().padLeft(4, '0')}-${d.month.toString().padLeft(2, '0')}-${d.day.toString().padLeft(2, '0')}';

/// [delta] months from a `YYYY-MM` key.
String shiftMonthKey(String monthKey, int delta) {
  final parts = monthKey.split('-').map(int.parse).toList();
  return _iso(DateTime.utc(parts[0], parts[1] + delta)).substring(0, 7);
}

/// The Monday-first weeks covering a month: from the Monday on or before the 1st to the Sunday on
/// or after the last day. All in UTC, so a device's timezone can never move a date.
({String from, String to}) monthGridRange(String monthKey) {
  final parts = monthKey.split('-').map(int.parse).toList();
  final first = DateTime.utc(parts[0], parts[1]);
  final last = DateTime.utc(parts[0], parts[1] + 1, 0);
  return (
    from: _iso(first.subtract(Duration(days: first.weekday - 1))),
    to: _iso(last.add(Duration(days: 7 - last.weekday))),
  );
}

/// Every date from [from] to [to], inclusive.
List<String> datesBetween(String from, String to) {
  final end = DateTime.parse('${to}T00:00:00Z');
  return [for (var d = DateTime.parse('${from}T00:00:00Z'); !d.isAfter(end); d = d.add(const Duration(days: 1))) _iso(d)];
}

const _months = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'];
const _weekdays = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'];

/// "October 2026".
String formatMonthKey(String monthKey) {
  final parts = monthKey.split('-').map(int.parse).toList();
  return '${_months[parts[1] - 1]} ${parts[0]}';
}

/// "Wednesday, 9 September 2026".
String formatLongIsoDate(String iso) {
  final d = DateTime.parse('${iso}T00:00:00Z');
  return '${_weekdays[d.weekday - 1]}, ${d.day} ${_months[d.month - 1]} ${d.year}';
}
