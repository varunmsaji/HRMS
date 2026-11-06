/// `GET /regularizations/decision-center`
/// (`apps/api/.../attendance/regularization_decision_center.py`). Every figure is the backend's.
class RegularizationDecisionItem {
  const RegularizationDecisionItem({
    required this.id,
    required this.employeeId,
    required this.employeeName,
    required this.employeeCode,
    required this.attendanceDate,
    required this.requestType,
    required this.status,
    required this.submittedAt,
    this.designation,
    this.department,
    this.timezone,
    this.shiftName,
    this.approvalStage,
    this.reason,
    this.recordedFirstIn,
    this.recordedLastOut,
    this.recordedWorkedMinutes,
    this.recordedLateMinutes,
    this.recordedStatus,
    this.requestedPunches = const [],
    this.requestedSpanMinutes,
  });

  factory RegularizationDecisionItem.fromJson(Map<String, dynamic> j) => RegularizationDecisionItem(
        id: j['id'] as String,
        employeeId: j['employee_id'] as String,
        employeeName: j['employee_name'] as String,
        employeeCode: j['employee_code'] as String,
        designation: j['designation'] as String?,
        department: j['department'] as String?,
        attendanceDate: j['attendance_date'] as String,
        timezone: j['timezone'] as String?,
        shiftName: j['shift_name'] as String?,
        requestType: j['request_type'] as String,
        status: j['status'] as String,
        approvalStage: j['approval_stage'] as String?,
        submittedAt: j['submitted_at'] as String,
        reason: j['reason'] as String?,
        recordedFirstIn: j['recorded_first_in'] as String?,
        recordedLastOut: j['recorded_last_out'] as String?,
        recordedWorkedMinutes: j['recorded_worked_minutes'] as int?,
        recordedLateMinutes: j['recorded_late_minutes'] as int?,
        recordedStatus: j['recorded_status'] as String?,
        requestedPunches: [for (final p in (j['requested_punches'] as List? ?? const [])) (direction: (p as Map<String, dynamic>)['direction'] as String, time: p['time'] as String)],
        requestedSpanMinutes: j['requested_span_minutes'] as int?,
      );

  final String id;
  final String employeeId;
  final String employeeName;
  final String employeeCode;
  final String? designation;
  final String? department;
  final String attendanceDate;
  final String? timezone;
  final String? shiftName;
  final String requestType;
  final String status;
  final String? approvalStage;
  final String submittedAt;
  final String? reason;
  final String? recordedFirstIn;
  final String? recordedLastOut;
  final int? recordedWorkedMinutes;
  final int? recordedLateMinutes;
  final String? recordedStatus;
  final List<({String direction, String time})> requestedPunches;
  final int? requestedSpanMinutes;

  bool get isPending => status == 'SUBMITTED';

  String get stageLabel => switch (approvalStage) {
        'HR' => 'Pending HR review',
        'MANAGER' => 'Pending manager review',
        _ => 'Pending review',
      };

  /// The earliest requested IN or latest requested OUT; null if the employee didn't ask for one.
  String? requestedTime(String direction) {
    String? best;
    for (final p in requestedPunches.where((p) => p.direction == direction)) {
      if (best == null || (direction == 'IN' ? p.time.compareTo(best) < 0 : p.time.compareTo(best) > 0)) best = p.time;
    }
    return best;
  }
}

class RegularizationDecisionCenter {
  const RegularizationDecisionCenter({
    required this.pendingCount,
    required this.windowRegularizedDays,
    required this.windowExpectedDays,
    required this.counts,
    required this.items,
    this.oldestPendingAt,
    this.windowRatePct,
  });

  factory RegularizationDecisionCenter.fromJson(Map<String, dynamic> j) {
    final s = j['summary'] as Map<String, dynamic>;
    return RegularizationDecisionCenter(
      pendingCount: s['pending_count'] as int,
      oldestPendingAt: s['oldest_pending_at'] as String?,
      windowRegularizedDays: s['window_regularized_days'] as int,
      windowExpectedDays: s['window_expected_days'] as int,
      windowRatePct: s['window_rate_pct'] as num?,
      counts: (j['counts'] as Map<String, dynamic>).cast<String, int>(),
      items: [for (final i in (j['items'] as List? ?? const [])) RegularizationDecisionItem.fromJson(i as Map<String, dynamic>)],
    );
  }

  final int pendingCount;
  final String? oldestPendingAt;
  final int windowRegularizedDays;
  final int windowExpectedDays;
  final num? windowRatePct;
  final Map<String, int> counts;
  final List<RegularizationDecisionItem> items;
}
