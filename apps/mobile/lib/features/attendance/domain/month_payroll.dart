/// One employee's month as payroll counts it (`GET /attendance/month-summary`, R-B03). The API runs
/// the code that finalizes a pay period and returns the frozen figures once the month is closed, so
/// no screen re-adds day rows to show paid, loss-of-pay or leave days.
class MonthPayroll {
  const MonthPayroll({
    required this.employeeId,
    required this.present,
    required this.absent,
    required this.leave,
    required this.holiday,
    required this.weeklyOff,
    required this.half,
    required this.lop,
    required this.onDuty,
    required this.paid,
    required this.lateCount,
    required this.overtimeApprovedMinutes,
    required this.frozen,
  });

  final String employeeId;
  final double present;
  final double absent;
  final double leave;
  final double holiday;
  final double weeklyOff;
  final double half;
  final double lop;
  final double onDuty;
  final double? paid;
  final int lateCount;
  final int overtimeApprovedMinutes;

  /// True once a closed pay period covers this month: these are the figures payroll reads.
  final bool frozen;

  /// What the HR calendar's "present" column shows: worked days, a band half day counting half.
  double get presentForGrid => present + onDuty + half / 2;

  factory MonthPayroll.fromJson(Map<String, dynamic> j) {
    double d(String key) => double.tryParse('${j[key] ?? 0}') ?? 0;
    int i(String key) => (j[key] as num?)?.toInt() ?? 0;
    return MonthPayroll(
      employeeId: j['employee_id'] as String,
      present: d('present_days'),
      absent: d('absent_days'),
      leave: d('leave_days'),
      holiday: d('holiday_days'),
      weeklyOff: d('weekly_off_days'),
      half: d('half_days'),
      lop: d('lop_days'),
      onDuty: d('on_duty_days'),
      paid: j['paid_days'] == null ? null : d('paid_days'),
      lateCount: i('late_count'),
      overtimeApprovedMinutes: i('ot_minutes_normal') + i('ot_minutes_weekly_off') + i('ot_minutes_holiday') + i('ot_minutes_night'),
      frozen: j['frozen'] == true,
    );
  }
}

/// Days as a short figure: `21`, `1.5` (never `1.50`).
String formatPayrollDays(double? value) {
  if (value == null) return '–';
  final rounded = (value * 100).round() / 100;
  return rounded == rounded.roundToDouble() ? rounded.toInt().toString() : rounded.toString();
}
