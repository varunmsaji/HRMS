/// `GET /leave-applications/decision-center` (`apps/api/.../leave/decision_center.py`). Every figure
/// is the backend's.
class LeaveColleague {
  const LeaveColleague(this.name);
  factory LeaveColleague.fromJson(Map<String, dynamic> json) => LeaveColleague(json['name'] as String);
  final String name;
}

class LeaveDecisionItem {
  const LeaveDecisionItem({
    required this.id,
    required this.employeeId,
    required this.employeeName,
    required this.employeeCode,
    required this.leaveType,
    required this.startDate,
    required this.endDate,
    required this.totalDays,
    required this.lopDays,
    required this.status,
    required this.submittedAt,
    this.designation,
    this.department,
    this.reason,
    this.currentBalance,
    this.postApprovalBalance,
    this.departmentSize,
    this.colleaguesAway = const [],
  });

  factory LeaveDecisionItem.fromJson(Map<String, dynamic> j) => LeaveDecisionItem(
        id: j['id'] as String,
        employeeId: j['employee_id'] as String,
        employeeName: j['employee_name'] as String,
        employeeCode: j['employee_code'] as String,
        designation: j['designation'] as String?,
        department: j['department'] as String?,
        leaveType: j['leave_type'] as String,
        startDate: j['start_date'] as String,
        endDate: j['end_date'] as String,
        totalDays: double.parse('${j['total_days']}'),
        lopDays: double.parse('${j['lop_days']}'),
        reason: j['reason'] as String?,
        status: j['status'] as String,
        submittedAt: j['submitted_at'] as String,
        currentBalance: j['current_balance'] == null ? null : double.parse('${j['current_balance']}'),
        postApprovalBalance: j['post_approval_balance'] == null ? null : double.parse('${j['post_approval_balance']}'),
        departmentSize: j['department_size'] as int?,
        colleaguesAway: [for (final c in (j['colleagues_away'] as List? ?? const [])) LeaveColleague.fromJson(c as Map<String, dynamic>)],
      );

  final String id;
  final String employeeId;
  final String employeeName;
  final String employeeCode;
  final String? designation;
  final String? department;
  final String leaveType;
  final String startDate;
  final String endDate;
  final double totalDays;
  final double lopDays;
  final String? reason;
  final String status;
  final String submittedAt;
  final double? currentBalance;
  final double? postApprovalBalance;
  final int? departmentSize;
  final List<LeaveColleague> colleaguesAway;

  bool get isPending => status == 'SUBMITTED';

  /// Whether teammates are also away, in one line. Same wording as the web `clashSummary`.
  ({bool clash, String text}) get clash {
    final names = colleaguesAway.map((c) => c.name).toSet().toList();
    final where = department ?? 'the same department';
    if (names.isEmpty) return (clash: false, text: 'No one else in $where is away during this period.');
    final shown = names.take(3).join(', ') + (names.length > 3 ? ' and ${names.length - 3} more' : '');
    final of = departmentSize == null ? '' : ' of $departmentSize';
    return (clash: true, text: '${names.length}$of in $where also away: $shown.');
  }
}

class LeaveDecisionCenter {
  const LeaveDecisionCenter({
    required this.pendingCount,
    required this.onLeaveToday,
    required this.onLeaveTodayByType,
    required this.activeStaff,
    required this.upcomingStarts7d,
    required this.peakDayAway,
    required this.counts,
    required this.items,
    this.oldestPendingAt,
    this.availablePct,
    this.peakDay,
  });

  factory LeaveDecisionCenter.fromJson(Map<String, dynamic> j) {
    final s = j['summary'] as Map<String, dynamic>;
    return LeaveDecisionCenter(
      pendingCount: s['pending_count'] as int,
      oldestPendingAt: s['oldest_pending_at'] as String?,
      onLeaveToday: s['on_leave_today'] as int,
      onLeaveTodayByType: [for (final t in (s['on_leave_today_by_type'] as List? ?? const [])) ((t as List)[0] as String, t[1] as int)],
      activeStaff: s['active_staff'] as int,
      availablePct: (s['available_pct'] as num?)?.toDouble(),
      upcomingStarts7d: s['upcoming_starts_7d'] as int,
      peakDay: s['peak_day'] as String?,
      peakDayAway: s['peak_day_away'] as int,
      counts: (j['counts'] as Map<String, dynamic>).cast<String, int>(),
      items: [for (final i in (j['items'] as List? ?? const [])) LeaveDecisionItem.fromJson(i as Map<String, dynamic>)],
    );
  }

  final int pendingCount;
  final String? oldestPendingAt;
  final int onLeaveToday;
  final List<(String, int)> onLeaveTodayByType;
  final int activeStaff;
  final double? availablePct;
  final int upcomingStarts7d;
  final String? peakDay;
  final int peakDayAway;
  final Map<String, int> counts;
  final List<LeaveDecisionItem> items;
}

/// A day count without trailing zeros: 6, 2.5.
String formatDays(double? value) {
  if (value == null) return '—';
  return value == value.roundToDouble() ? value.toInt().toString() : value.toString();
}
