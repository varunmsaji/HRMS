import 'package:hrms_mobile/features/attendance/domain/attendance_insights.dart' show addDaysIso;

/// A `GET /v1/attendance/summary` response for [today] with [lastWeek] as the comparison day: today
/// e1 present (late), e2 remote, e3 absent and one employee with no record yet; last week one of
/// two attended.
Map<String, dynamic> totalsJson(String today, String lastWeek) {
  Map<String, dynamic> kpis(Map<String, int> v) => {
        for (final k in ['total_employees', 'no_record', 'present', 'remote', 'on_duty', 'absent', 'leave', 'half_day', 'holiday', 'weekly_off', 'incomplete', 'late', 'not_checked_in', 'checked_in', 'exceptions', 'overtime_employees', 'overtime_minutes_detected', 'overtime_minutes_approved', 'not_employed']) k: v[k] ?? 0,
      };
  Map<String, dynamic> group(String? id, String name, int expected, int present) =>
      {'id': id, 'name': name, 'headcount': expected == 0 ? 1 : expected, 'expected': expected, 'present': present, 'absent': expected - present, 'leave': 0, 'late': 0, 'rate': expected > 0 ? present / expected * 100 : null};
  return {
    'date_from': lastWeek,
    'date_to': today,
    'focus_date': today,
    'compare_date': lastWeek,
    'is_today': true,
    'row_count': 5,
    'daily': [
      {'date': lastWeek, 'expected': 2, 'present': 1, 'rate': 50.0, 'remote': 0, 'absent': 1, 'leave': 0, 'late': 0, 'checked_in': 1, 'worked_minutes': 480},
      for (var i = 1; i < 7; i++) {'date': addDaysIso(lastWeek, i), 'expected': 0, 'present': 0, 'rate': null, 'remote': 0, 'absent': 0, 'leave': 0, 'late': 0, 'checked_in': 0, 'worked_minutes': 0},
      {'date': today, 'expected': 3, 'present': 2, 'rate': 200 / 3, 'remote': 1, 'absent': 1, 'leave': 0, 'late': 1, 'checked_in': 2, 'worked_minutes': 900},
    ],
    'focus': kpis({'total_employees': 4, 'no_record': 1, 'present': 1, 'remote': 1, 'absent': 1, 'late': 1, 'not_checked_in': 2, 'checked_in': 2}),
    'compare': kpis({'total_employees': 2, 'present': 1, 'absent': 1, 'not_checked_in': 1, 'checked_in': 1}),
    'distribution': [
      {'bucket': 'PRESENT', 'count': 1},
      {'bucket': 'REMOTE', 'count': 1},
      {'bucket': 'ABSENT', 'count': 1},
    ],
    'punctuality': {
      'checked_in': 4, 'on_time': 3, 'late': 1, 'late_rate': 25.0, 'on_time_rate': 75.0, 'avg_late_minutes': 10.0,
      'bands': [
        {'key': '1_15', 'label': '1–15 min', 'count': 1},
        {'key': '16_30', 'label': '16–30 min', 'count': 0},
        {'key': '31_60', 'label': '31–60 min', 'count': 0},
        {'key': '60_plus', 'label': 'Over an hour', 'count': 0},
      ],
    },
    'frequent_late': [
      {'employee_id': 'e1', 'late_days': 2, 'total_late_minutes': 25},
    ],
    'weekday_absence': [
      for (final (i, l) in const ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'].indexed) {'index': i, 'label': l, 'expected': l == 'Wed' ? 5 : 0, 'absent': l == 'Wed' ? 2 : 0, 'rate': l == 'Wed' ? 40.0 : null},
    ],
    'by_department': [group('d-ops', 'Ops', 1, 0), group('d-sales', 'Sales', 2, 2), group(null, 'Unassigned', 0, 0)],
    'by_branch': [group('b-hq', 'HQ', 3, 2)],
  };
}
