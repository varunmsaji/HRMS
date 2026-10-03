import 'package:dio/dio.dart';

import '../../../core/api/api_client.dart';

class Shift {
  Shift({required this.id, required this.name, this.code, required this.isActive, required this.version});
  final String id;
  final String name;
  final String? code;
  final bool isActive;
  final int version;

  factory Shift.fromJson(Map<String, dynamic> json) => Shift(
        id: json['id'] as String,
        name: json['name'] as String,
        code: json['code'] as String?,
        isActive: json['is_active'] as bool,
        version: json['version'] as int,
      );
}

class HolidayCalendar {
  HolidayCalendar({required this.id, required this.name, this.code, required this.kind, required this.isActive, required this.version});
  final String id;
  final String name;
  final String? code;
  final String kind;
  final bool isActive;
  final int version;

  factory HolidayCalendar.fromJson(Map<String, dynamic> json) => HolidayCalendar(
        id: json['id'] as String,
        name: json['name'] as String,
        code: json['code'] as String?,
        kind: json['kind'] as String,
        isActive: json['is_active'] as bool,
        version: json['version'] as int,
      );
}

class Holiday {
  Holiday({required this.id, required this.date, required this.name, required this.holidayType, required this.isPaid, required this.isWorking});
  final String id;
  final String date;
  final String name;
  final String holidayType;
  final bool isPaid;
  final bool isWorking;

  factory Holiday.fromJson(Map<String, dynamic> json) => Holiday(
        id: json['id'] as String,
        date: json['date'] as String,
        name: json['name'] as String,
        holidayType: json['holiday_type'] as String,
        isPaid: json['is_paid'] as bool,
        isWorking: json['is_working'] as bool,
      );
}

class WeeklyOffPattern {
  WeeklyOffPattern({required this.id, required this.name, this.code, required this.patternKind, required this.isActive, required this.version});
  final String id;
  final String name;
  final String? code;
  final String patternKind;
  final bool isActive;
  final int version;

  factory WeeklyOffPattern.fromJson(Map<String, dynamic> json) => WeeklyOffPattern(
        id: json['id'] as String,
        name: json['name'] as String,
        code: json['code'] as String?,
        patternKind: json['pattern_kind'] as String,
        isActive: json['is_active'] as bool,
        version: json['version'] as int,
      );
}

class WorkCalendar {
  WorkCalendar({required this.id, required this.name, this.description, required this.isActive, required this.version});
  final String id;
  final String name;
  final String? description;
  final bool isActive;
  final int version;

  factory WorkCalendar.fromJson(Map<String, dynamic> json) => WorkCalendar(
        id: json['id'] as String,
        name: json['name'] as String,
        description: json['description'] as String?,
        isActive: json['is_active'] as bool,
        version: json['version'] as int,
      );
}

class RegularizationRequest {
  RegularizationRequest({
    required this.id,
    required this.employeeId,
    required this.attendanceDate,
    required this.requestType,
    this.reason,
    required this.status,
    this.approvalStage,
    required this.version,
  });
  final String id;
  final String employeeId;
  final String attendanceDate;
  final String requestType;
  final String? reason;
  final String status;
  final String? approvalStage;
  final int version;

  factory RegularizationRequest.fromJson(Map<String, dynamic> json) => RegularizationRequest(
        id: json['id'] as String,
        employeeId: json['employee_id'] as String,
        attendanceDate: json['attendance_date'] as String,
        requestType: json['request_type'] as String,
        reason: json['reason'] as String?,
        status: json['status'] as String,
        approvalStage: json['approval_stage'] as String?,
        version: json['version'] as int,
      );
}

class OvertimeRecord {
  OvertimeRecord({
    required this.id,
    required this.employeeId,
    required this.attendanceDate,
    required this.minutesDetected,
    this.minutesApproved,
    required this.status,
    required this.version,
  });
  final String id;
  final String employeeId;
  final String attendanceDate;
  final int minutesDetected;
  final int? minutesApproved;
  final String status;
  final int version;

  factory OvertimeRecord.fromJson(Map<String, dynamic> json) => OvertimeRecord(
        id: json['id'] as String,
        employeeId: json['employee_id'] as String,
        attendanceDate: json['attendance_date'] as String,
        minutesDetected: json['minutes_detected'] as int,
        minutesApproved: json['minutes_approved'] as int?,
        status: json['status'] as String,
        version: json['version'] as int,
      );
}

class ShiftRoster {
  ShiftRoster({
    required this.id,
    required this.employeeId,
    required this.rosterDate,
    this.shiftId,
    required this.isWeekOffOverride,
    required this.isHolidayWorkingOverride,
    required this.status,
    required this.version,
  });
  final String id;
  final String employeeId;
  final String rosterDate;
  final String? shiftId;
  final bool isWeekOffOverride;
  final bool isHolidayWorkingOverride;
  final String status;
  final int version;

  factory ShiftRoster.fromJson(Map<String, dynamic> json) => ShiftRoster(
        id: json['id'] as String,
        employeeId: json['employee_id'] as String,
        rosterDate: json['roster_date'] as String,
        shiftId: json['shift_id'] as String?,
        isWeekOffOverride: json['is_week_off_override'] as bool,
        isHolidayWorkingOverride: json['is_holiday_working_override'] as bool,
        status: json['status'] as String,
        version: json['version'] as int,
      );
}

class AttendancePeriod {
  AttendancePeriod({
    required this.id,
    required this.legalEntityId,
    required this.periodStart,
    required this.periodEnd,
    this.label,
    required this.status,
    required this.version,
  });
  final String id;
  final String legalEntityId;
  final String periodStart;
  final String periodEnd;
  final String? label;
  final String status;
  final int version;

  factory AttendancePeriod.fromJson(Map<String, dynamic> json) => AttendancePeriod(
        id: json['id'] as String,
        legalEntityId: json['legal_entity_id'] as String,
        periodStart: json['period_start'] as String,
        periodEnd: json['period_end'] as String,
        label: json['label'] as String?,
        status: json['status'] as String,
        version: json['version'] as int,
      );
}

/// One employee's attendance for one day — mirrors `AttendanceDayRead`. Only
/// the fields the mobile day-detail/self-overview screens show.
class AttendanceDay {
  AttendanceDay({
    required this.id,
    required this.employeeId,
    required this.attendanceDate,
    required this.attendanceStatus,
    this.timezone = 'Asia/Kolkata',
    this.actualFirstIn,
    this.actualLastOut,
    this.workedMinutes,
    this.lateMinutes,
    required this.isLocked,
    this.raw = const {},
  });
  final String id;
  final String employeeId;
  final String attendanceDate;
  final String attendanceStatus;

  /// The zone this day was computed in — every timestamp on it is shown in this zone.
  final String timezone;
  final String? actualFirstIn;
  final String? actualLastOut;
  final int? workedMinutes;
  final int? lateMinutes;
  final bool isLocked;

  /// The full `AttendanceDayRead` JSON, for the detail screen.
  final Map<String, dynamic> raw;

  factory AttendanceDay.fromJson(Map<String, dynamic> json) => AttendanceDay(
        id: json['id'] as String,
        employeeId: json['employee_id'] as String,
        attendanceDate: json['attendance_date'] as String,
        attendanceStatus: json['attendance_status'] as String,
        timezone: (json['timezone'] as String?) ?? 'Asia/Kolkata',
        actualFirstIn: json['actual_first_in'] as String?,
        actualLastOut: json['actual_last_out'] as String?,
        workedMinutes: json['worked_minutes'] as int?,
        lateMinutes: json['late_minutes'] as int?,
        isLocked: json['is_locked'] as bool,
        raw: json,
      );
}

/// `PunchRead`.
class Punch {
  Punch({required this.id, required this.employeeId, required this.punchTime, required this.direction, required this.source, this.reference});
  final String id;
  final String employeeId;
  final String punchTime;
  final String direction;
  final String source;
  final String? reference;

  factory Punch.fromJson(Map<String, dynamic> json) => Punch(
        id: json['id'] as String,
        employeeId: json['employee_id'] as String,
        punchTime: json['punch_time'] as String,
        direction: json['direction'] as String,
        source: json['source'] as String,
        reference: json['reference'] as String?,
      );
}

/// `LeaveDayProjectionRead` — approved leave published onto a calendar day (provenance only).
class LeaveDayProjection {
  LeaveDayProjection({required this.leaveApplicationId, required this.fraction, this.half, required this.isPaid, required this.status});
  final String leaveApplicationId;
  final String fraction;
  final String? half;
  final bool isPaid;
  final String status;

  factory LeaveDayProjection.fromJson(Map<String, dynamic> json) => LeaveDayProjection(
        leaveApplicationId: json['leave_application_id'] as String,
        fraction: json['fraction'].toString(),
        half: json['half'] as String?,
        isPaid: json['is_paid'] as bool,
        status: json['status'] as String,
      );
}

class PolicyAssignment {
  PolicyAssignment({
    required this.id,
    required this.policyKind,
    required this.policyId,
    required this.scopeType,
    this.scopeId,
    required this.effectiveFrom,
    this.effectiveTo,
    required this.isActive,
    required this.version,
  });
  final String id;
  final String policyKind;
  final String policyId;
  final String scopeType;
  final String? scopeId;
  final String effectiveFrom;
  final String? effectiveTo;
  final bool isActive;
  final int version;

  factory PolicyAssignment.fromJson(Map<String, dynamic> json) => PolicyAssignment(
        id: json['id'] as String,
        policyKind: json['policy_kind'] as String,
        policyId: json['policy_id'] as String,
        scopeType: json['scope_type'] as String,
        scopeId: json['scope_id'] as String?,
        effectiveFrom: json['effective_from'] as String,
        effectiveTo: json['effective_to'] as String?,
        isActive: json['is_active'] as bool,
        version: json['version'] as int,
      );
}

class CalendarResolution {
  CalendarResolution({required this.employeeId, required this.date, required this.configIncomplete, this.workCalendarName, this.dayType});
  final String employeeId;
  final String date;
  final bool configIncomplete;
  final String? workCalendarName;
  final Map<String, dynamic>? dayType;

  factory CalendarResolution.fromJson(Map<String, dynamic> json) => CalendarResolution(
        employeeId: json['employee_id'] as String,
        date: json['date'] as String,
        configIncomplete: json['config_incomplete'] as bool,
        workCalendarName: json['work_calendar_name'] as String?,
        dayType: json['day_type'] as Map<String, dynamic>?,
      );
}

/// Covers Shifts, Holiday Calendars/Holidays, Weekly-Off Patterns, Work
/// Calendars, Regularizations, Overtime, Shift Rosters, Attendance Periods,
/// Attendance Days, Punches, Policy Assignments and Calendar Resolution —
/// mirrors `apps/api/src/hrms/modules/{attendance,organisation}/router.py`.
/// `POST /attendance/face-punches/me` — the punch plus the scores that justified it.
class FacePunchResult {
  FacePunchResult({
    required this.punchId,
    required this.direction,
    required this.punchTime,
    required this.similarity,
    this.livenessScore,
  });

  final String punchId;
  final String direction;
  final String punchTime;
  final double similarity;
  /// Null when the server accepted the punch without a liveness score.
  final double? livenessScore;

  factory FacePunchResult.fromJson(Map<String, dynamic> json) {
    final punch = json['punch'] as Map<String, dynamic>;
    return FacePunchResult(
      punchId: punch['id'] as String,
      direction: punch['direction'] as String,
      punchTime: punch['punch_time'] as String,
      similarity: double.parse(json['similarity'].toString()),
      livenessScore: json['liveness_score'] == null ? null : double.parse(json['liveness_score'].toString()),
    );
  }
}

/// The signed-in employee's face enrollment state (`GET /attendance/face-enrollment/me`).
class FaceEnrollmentStatus {
  FaceEnrollmentStatus({this.profileStatus, this.reviewNote, this.windowExpiresAt});

  /// `PENDING_APPROVAL` | `ENROLLED` | `REJECTED` | `REVOKED`, or null if never enrolled.
  final String? profileStatus;
  final String? reviewNote;

  /// Set only while an HR-opened enrollment window is open and unexpired.
  final DateTime? windowExpiresAt;

  bool get isEnrolled => profileStatus == 'ENROLLED';
  bool get isPendingApproval => profileStatus == 'PENDING_APPROVAL';
  bool get canEnroll => windowExpiresAt != null && !isEnrolled && !isPendingApproval;

  factory FaceEnrollmentStatus.fromJson(Map<String, dynamic> json) {
    final profile = json['profile'] as Map<String, dynamic>?;
    final window = json['open_window'] as Map<String, dynamic>?;
    return FaceEnrollmentStatus(
      profileStatus: profile?['status'] as String?,
      reviewNote: profile?['review_note'] as String?,
      windowExpiresAt: window == null ? null : DateTime.parse(window['expires_at'] as String),
    );
  }
}

/// Capture order for self-enrollment; must match the server's form field names.
const faceEnrollmentAngles = ['front', 'left', 'right', 'up', 'down'];

class AttendanceRepository {
  AttendanceRepository(this._client);
  final ApiClient _client;

  // Shifts
  Future<List<Shift>> listShifts() =>
      _client.getList('/shifts', parseItem: (d) => Shift.fromJson(d as Map<String, dynamic>)).then((e) => e.data);
  Future<Shift> createShift({required String name, String? code}) => _client.post(
        '/shifts',
        body: {'name': name, if (code != null && code.isNotEmpty) 'code': code},
        parse: (d) => Shift.fromJson(d as Map<String, dynamic>),
      );

  // Holiday calendars
  Future<List<HolidayCalendar>> listHolidayCalendars() => _client
      .getList('/holiday-calendars', parseItem: (d) => HolidayCalendar.fromJson(d as Map<String, dynamic>))
      .then((e) => e.data);
  Future<HolidayCalendar> createHolidayCalendar({required String name, String? code, required String kind}) => _client.post(
        '/holiday-calendars',
        body: {'name': name, 'kind': kind, if (code != null && code.isNotEmpty) 'code': code},
        parse: (d) => HolidayCalendar.fromJson(d as Map<String, dynamic>),
      );
  Future<List<Holiday>> listHolidays(String calendarId) => _client
      .getList('/holiday-calendars/$calendarId/holidays', parseItem: (d) => Holiday.fromJson(d as Map<String, dynamic>))
      .then((e) => e.data);
  Future<Holiday> createHoliday(String calendarId, Map<String, dynamic> body) => _client.post(
        '/holiday-calendars/$calendarId/holidays',
        body: body,
        parse: (d) => Holiday.fromJson(d as Map<String, dynamic>),
      );

  // Weekly-off patterns
  Future<List<WeeklyOffPattern>> listWeeklyOffPatterns() => _client
      .getList('/weekly-off-patterns', parseItem: (d) => WeeklyOffPattern.fromJson(d as Map<String, dynamic>))
      .then((e) => e.data);
  Future<WeeklyOffPattern> createWeeklyOffPattern(Map<String, dynamic> body) => _client.post(
        '/weekly-off-patterns',
        body: body,
        parse: (d) => WeeklyOffPattern.fromJson(d as Map<String, dynamic>),
      );

  // Work calendars
  Future<List<WorkCalendar>> listWorkCalendars() => _client
      .getList('/work-calendars', parseItem: (d) => WorkCalendar.fromJson(d as Map<String, dynamic>))
      .then((e) => e.data);
  Future<WorkCalendar> createWorkCalendar(Map<String, dynamic> body) => _client.post(
        '/work-calendars',
        body: body,
        parse: (d) => WorkCalendar.fromJson(d as Map<String, dynamic>),
      );

  // Regularizations
  Future<List<RegularizationRequest>> listRegularizations({String? employeeId}) => _client
      .getList(
        '/regularizations',
        filters: employeeId == null ? null : {'employee_id': employeeId},
        parseItem: (d) => RegularizationRequest.fromJson(d as Map<String, dynamic>),
      )
      .then((e) => e.data);
  Future<RegularizationRequest> submitRegularization(Map<String, dynamic> body) => _client.post(
        '/regularizations',
        body: body,
        parse: (d) => RegularizationRequest.fromJson(d as Map<String, dynamic>),
      );
  Future<RegularizationRequest> approveRegularization(String id, {required String ifMatch, String? comment}) => _client.post(
        '/regularizations/$id/approve',
        ifMatch: ifMatch,
        body: {if (comment != null && comment.isNotEmpty) 'reviewer_comment': comment},
        parse: (d) => RegularizationRequest.fromJson(d as Map<String, dynamic>),
      );
  Future<RegularizationRequest> rejectRegularization(String id, {required String ifMatch, String? reason}) => _client.post(
        '/regularizations/$id/reject',
        ifMatch: ifMatch,
        body: {if (reason != null && reason.isNotEmpty) 'rejection_reason': reason},
        parse: (d) => RegularizationRequest.fromJson(d as Map<String, dynamic>),
      );
  Future<RegularizationRequest> cancelRegularization(String id, {required String ifMatch}) => _client.post(
        '/regularizations/$id/cancel',
        ifMatch: ifMatch,
        parse: (d) => RegularizationRequest.fromJson(d as Map<String, dynamic>),
      );

  // Overtime records
  Future<List<OvertimeRecord>> listOvertimeRecords({String? employeeId}) => _client
      .getList(
        '/overtime',
        filters: employeeId == null ? null : {'employee_id': employeeId},
        parseItem: (d) => OvertimeRecord.fromJson(d as Map<String, dynamic>),
      )
      .then((e) => e.data);
  Future<OvertimeRecord> approveOvertime(String id, {required String ifMatch, String? comment}) => _client.post(
        '/overtime/$id/approve',
        ifMatch: ifMatch,
        body: {if (comment != null && comment.isNotEmpty) 'reviewer_comment': comment},
        parse: (d) => OvertimeRecord.fromJson(d as Map<String, dynamic>),
      );
  Future<OvertimeRecord> rejectOvertime(String id, {required String ifMatch, String? reason}) => _client.post(
        '/overtime/$id/reject',
        ifMatch: ifMatch,
        body: {if (reason != null && reason.isNotEmpty) 'rejection_reason': reason},
        parse: (d) => OvertimeRecord.fromJson(d as Map<String, dynamic>),
      );

  // Shift rosters
  Future<List<ShiftRoster>> listRosters({String? employeeId, String? dateFrom, String? dateTo}) => _client
      .getList(
        '/rosters',
        filters: {
          if (employeeId != null) 'employee_id': employeeId,
          if (dateFrom != null) 'date_from': dateFrom,
          if (dateTo != null) 'date_to': dateTo,
        },
        parseItem: (d) => ShiftRoster.fromJson(d as Map<String, dynamic>),
      )
      .then((e) => e.data);
  Future<ShiftRoster> createRoster(Map<String, dynamic> body) => _client.post(
        '/rosters',
        body: body,
        parse: (d) => ShiftRoster.fromJson(d as Map<String, dynamic>),
      );

  // Attendance periods
  Future<List<AttendancePeriod>> listAttendancePeriods() => _client
      .getList('/attendance-periods', parseItem: (d) => AttendancePeriod.fromJson(d as Map<String, dynamic>))
      .then((e) => e.data);
  Future<AttendancePeriod> createAttendancePeriod(Map<String, dynamic> body) => _client.post(
        '/attendance-periods',
        body: body,
        parse: (d) => AttendancePeriod.fromJson(d as Map<String, dynamic>),
      );
  Future<Map<String, dynamic>> validateAttendancePeriod(String id) => _client.post(
        '/attendance-periods/$id/validate',
        parse: (d) => d as Map<String, dynamic>,
      );
  Future<AttendancePeriod> finalizeAttendancePeriod(String id, {required String ifMatch}) => _client.post(
        '/attendance-periods/$id/finalize',
        ifMatch: ifMatch,
        parse: (d) => AttendancePeriod.fromJson(d as Map<String, dynamic>),
      );
  Future<AttendancePeriod> reopenAttendancePeriod(String id, {required String ifMatch, required String reason}) => _client.post(
        '/attendance-periods/$id/reopen',
        ifMatch: ifMatch,
        body: {'reason': reason},
        parse: (d) => AttendancePeriod.fromJson(d as Map<String, dynamic>),
      );

  // Attendance days + punches
  Future<List<AttendanceDay>> listAttendanceDays({String? employeeId, required String dateFrom, required String dateTo, String? attendanceStatus}) =>
      _client
          .getList(
            '/attendance/days',
            query: PageQuery(perPage: 100),
            filters: {
              if (employeeId != null) 'employee_id': employeeId,
              'date_from': dateFrom,
              'date_to': dateTo,
              if (attendanceStatus != null) 'attendance_status': attendanceStatus,
            },
            parseItem: (d) => AttendanceDay.fromJson(d as Map<String, dynamic>),
          )
          .then((e) => e.data);
  Future<void> punchMe({required String direction, String? reference}) => _client.post(
        '/attendance/punches/me',
        body: {'direction': direction, if (reference != null) 'reference': reference},
        parse: (_) {},
      );

  /// Self punch gated on a live selfie: the server checks liveness and matches it against
  /// the caller's enrolled face before recording a punch (server-timed, source `FACE`).
  Future<FacePunchResult> facePunchMe({required String direction, required List<int> photoJpeg}) =>
      _client.postMultipart(
        '/attendance/face-punches/me',
        buildForm: () => FormData.fromMap({
          'direction': direction,
          'photo': MultipartFile.fromBytes(photoJpeg, filename: 'selfie.jpg', contentType: DioMediaType('image', 'jpeg')),
        }),
        parse: (d) => FacePunchResult.fromJson(d as Map<String, dynamic>),
      );

  Future<AttendanceDay> getAttendanceDay(String id) =>
      _client.get('/attendance/days/$id', parse: (d) => AttendanceDay.fromJson(d as Map<String, dynamic>));

  /// `POST /attendance/days/{id}/recompute` — privileged (`ATTENDANCE.RECOMPUTE`), refused on a locked day.
  Future<AttendanceDay> recomputeAttendanceDay(String id) =>
      _client.post('/attendance/days/$id/recompute', parse: (d) => AttendanceDay.fromJson(d as Map<String, dynamic>));

  /// BUS-012 — HR confirms an approved full-day leave stands over punches on the same day.
  Future<AttendanceDay> keepLeaveOverPunches(String id, {required String reason}) => _client.post(
        '/attendance/days/$id/work-on-leave/keep-leave',
        body: {'reason': reason},
        parse: (d) => AttendanceDay.fromJson(d as Map<String, dynamic>),
      );

  /// Calculates the employee's attendance for the *business* "today" — the date is deliberately
  /// not sent; the server defaults it (a client-computed date would use the device's zone).
  Future<void> calculateToday(String employeeId) => _client.post('/attendance/days/calculate?employee_id=$employeeId', parse: (_) {});

  Future<List<Punch>> listPunches({required String employeeId, required String dateFrom, required String dateTo}) => _client
      .getList('/attendance/punches', filters: {'employee_id': employeeId, 'date_from': dateFrom, 'date_to': dateTo}, parseItem: (d) => Punch.fromJson(d as Map<String, dynamic>))
      .then((e) => e.data);

  /// `POST /attendance/punches` (`ATTENDANCE.PUNCH_ON_BEHALF`) — [punchTimeUtcIso] is the UTC instant.
  Future<Punch> createPunchOnBehalf({required String employeeId, required String direction, required String punchTimeUtcIso, required String reference}) => _client.post(
        '/attendance/punches',
        body: {'employee_id': employeeId, 'punch_time': punchTimeUtcIso, 'direction': direction, 'reference': reference},
        parse: (d) => Punch.fromJson(d as Map<String, dynamic>),
      );

  Future<List<LeaveDayProjection>> listLeaveProjections({required String employeeId, required String dateFrom, required String dateTo}) => _client
      .getList('/leave-projections', filters: {'employee_id': employeeId, 'date_from': dateFrom, 'date_to': dateTo}, parseItem: (d) => LeaveDayProjection.fromJson(d as Map<String, dynamic>))
      .then((e) => e.data);

  Future<FaceEnrollmentStatus> getMyFaceEnrollment() => _client.get(
        '/attendance/face-enrollment/me',
        parse: (d) => FaceEnrollmentStatus.fromJson(d as Map<String, dynamic>),
      );

  /// Submits the five captures (keyed by [faceEnrollmentAngles]) inside an open window. The
  /// result waits for HR approval before it can be used to punch.
  Future<void> submitFaceEnrollment({required Map<String, List<int>> photos, required bool consentConfirmed}) =>
      _client.postMultipart(
        '/attendance/face-enrollment/me',
        buildForm: () => FormData.fromMap({
          'consent_confirmed': consentConfirmed ? 'true' : 'false',
          for (final angle in faceEnrollmentAngles)
            angle: MultipartFile.fromBytes(photos[angle]!, filename: '$angle.jpg', contentType: DioMediaType('image', 'jpeg')),
        }),
        parse: (_) {},
      );

  // Policy assignments
  Future<List<PolicyAssignment>> listPolicyAssignments({String? policyKind}) => _client
      .getList(
        '/policy-assignments',
        filters: policyKind == null ? null : {'policy_kind': policyKind},
        parseItem: (d) => PolicyAssignment.fromJson(d as Map<String, dynamic>),
      )
      .then((e) => e.data);
  Future<PolicyAssignment> createPolicyAssignment(Map<String, dynamic> body) => _client.post(
        '/policy-assignments',
        body: body,
        parse: (d) => PolicyAssignment.fromJson(d as Map<String, dynamic>),
      );

  Future<CalendarResolution> resolveCalendar({required String employeeId, required String date}) => _client.get(
        '/calendar-resolution?${Uri(queryParameters: {'employee_id': employeeId, 'date': date}).query}',
        parse: (d) => CalendarResolution.fromJson(d as Map<String, dynamic>),
      );
}
