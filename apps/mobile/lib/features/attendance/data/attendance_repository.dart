import 'package:dio/dio.dart';

import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api/api_client.dart';
import '../../../core/providers.dart';

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

final attendanceRepositoryProvider = Provider<AttendanceRepository>((ref) => AttendanceRepository(ref.watch(apiClientProvider)));

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
  // Overtime records
  // Shift rosters
  // Attendance periods
  // Attendance days + punches
  /// Pages through every result (capped at 50 pages) so day-level summaries are not truncated.
  Future<List<AttendanceDay>> listAttendanceDays({String? employeeId, required String dateFrom, required String dateTo, String? attendanceStatus}) async {
    final all = <AttendanceDay>[];
    for (var page = 1; page <= 50; page++) {
      final env = await _client.getList(
        '/attendance/days',
        query: PageQuery(page: page, perPage: 100),
        filters: {
          if (employeeId != null) 'employee_id': employeeId,
          'date_from': dateFrom,
          'date_to': dateTo,
          if (attendanceStatus != null) 'attendance_status': attendanceStatus,
        },
        parseItem: (d) => AttendanceDay.fromJson(d as Map<String, dynamic>),
      );
      all.addAll(env.data);
      if (env.pagination == null || !env.pagination!.hasNext) break;
    }
    return all;
  }

  /// [idempotencyKey]: pass the same key when retrying after a failure with no response
  /// (timeout, network) — the server then replays the original punch instead of recording a
  /// second one. Use a new key for a new punch.
  Future<void> punchMe({required String direction, String? reference, String? idempotencyKey}) => _client.post(
        '/attendance/punches/me',
        body: {
          'direction': direction,
          if (reference != null) 'reference': reference,
          'idempotency_key': idempotencyKey ?? ApiClient.newIdempotencyKey(),
        },
        parse: (_) {},
      );

  /// Self punch gated on a live selfie: the server checks liveness and matches it against
  /// the caller's enrolled face before recording a punch (server-timed, source `FACE`).
  ///
  /// [idempotencyKey]: pass the same key when retrying after a failure with no response (the
  /// punch may have been recorded); the server then returns the original punch instead of a
  /// second one. A fresh key is generated when omitted.
  Future<FacePunchResult> facePunchMe({required String direction, required List<int> photoJpeg, String? idempotencyKey}) {
    final key = idempotencyKey ?? ApiClient.newIdempotencyKey();
    return _client.postMultipart(
      '/attendance/face-punches/me',
      buildForm: () => FormData.fromMap({
        'direction': direction,
        'idempotency_key': key,
        'photo': MultipartFile.fromBytes(photoJpeg, filename: 'selfie.jpg', contentType: DioMediaType('image', 'jpeg')),
      }),
      parse: (d) => FacePunchResult.fromJson(d as Map<String, dynamic>),
    );
  }

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

  // ---- HR face-enrollment admin (`/attendance/face-profiles/{employee_id}`) --------------------
  String _face(String employeeId) => '/attendance/face-profiles/$employeeId';

  Future<Map<String, dynamic>> getFaceProfileStatus(String employeeId) =>
      _client.get('${_face(employeeId)}/enrollment', parse: (d) => d as Map<String, dynamic>);
  Future<void> openFaceEnrollmentWindow(String employeeId) => _client.post('${_face(employeeId)}/enrollment-window', parse: (_) {});
  Future<void> cancelFaceEnrollmentWindow(String employeeId) => _client.delete('${_face(employeeId)}/enrollment-window', parse: (_) {});
  Future<void> approveFaceProfile(String employeeId) => _client.post('${_face(employeeId)}/approve', parse: (_) {});
  Future<void> rejectFaceProfile(String employeeId, {String? note}) =>
      _client.post('${_face(employeeId)}/reject', body: {'note': (note == null || note.isEmpty) ? null : note}, parse: (_) {});
  Future<void> revokeFaceProfile(String employeeId) => _client.delete(_face(employeeId), parse: (_) {});

  /// The photo under review, fetched through the API (auth + no-store) — it never has a URL of its own.
  Future<DownloadedFile> downloadFaceReviewPhoto(String employeeId) => _client.download('${_face(employeeId)}/review-photo');

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
}
