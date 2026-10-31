// Device harness (not shipped, not run by `flutter test`): the real app, router, theme and screens
// on an Android device or emulator, with the network, GPS and clock-independent data faked so every
// flow of the Attendance slice can be driven and photographed:
//
//   flutter run -t test/device/device_check_main.dart -d <device> \
//     --dart-define=PERSONA=employee|hr_admin|admin  --dart-define=FACE=required \
//     --dart-define=LOCATION=off|denied|poor|ok  --dart-define=NET_FAIL_FIRST=true
//
// What is real: the Flutter engine, rendering, text scaling, navigation, themes, the shell, every
// widget, PunchController. What is faked: the API (an in-memory repository that really records
// punches and re-calculates the day row), the GPS gateway, and the sign-in. The camera is not
// exercised: a face punch stops at the camera screen.
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:hrms_mobile/core/api/api_error.dart';
import 'package:hrms_mobile/core/auth/permissions.dart';
import 'package:hrms_mobile/core/providers.dart';
import 'package:hrms_mobile/core/time.dart';
import 'package:hrms_mobile/features/attendance/data/attendance_repository.dart';
import 'package:hrms_mobile/features/attendance/data/location_provider.dart';
import 'package:hrms_mobile/features/attendance/domain/punch_location.dart';
import 'package:hrms_mobile/main.dart';

import '../support/fake_api_client.dart';
import '../support/fake_auth.dart';

const _persona = String.fromEnvironment('PERSONA', defaultValue: 'employee');
const _face = String.fromEnvironment('FACE');
const _location = String.fromEnvironment('LOCATION', defaultValue: 'off');
const _netFailFirst = bool.fromEnvironment('NET_FAIL_FIRST');
const _latencyMs = int.fromEnvironment('LATENCY_MS', defaultValue: 700);
const _zone = 'Asia/Kolkata';

const _employeeRole = [
  employeeView, leaveApplicationSubmit, leaveBalanceView, attendancePunch, attendanceView, attendanceRegularizationRequest, payrollPayslipViewOwn,
];

class _Gateway implements LocationGateway {
  _Gateway(this.mode);
  final String mode;
  late var _granted = mode != 'denied';
  var _firstFix = true;

  @override
  Future<bool> serviceEnabled() async => true;
  @override
  Future<GatewayPermission> permission() async => _granted ? GatewayPermission.granted : GatewayPermission.deniedForever;
  @override
  Future<GatewayPermission> requestPermission() async => permission();
  @override
  Future<GpsFix> currentFix({required Duration timeout}) async {
    final poor = mode == 'poor' && _firstFix;
    _firstFix = false;
    return GpsFix(latitude: 9.9312, longitude: 76.2673, accuracyM: poor ? 400 : 9, timestamp: DateTime.now().toUtc());
  }

  // "Open settings" stands in for the employee fixing it there.
  @override
  Future<void> openAppSettings() async => _granted = true;
  @override
  Future<void> openLocationSettings() async => _granted = true;
}

class _Repo implements AttendanceRepository {
  final _punches = <Map<String, dynamic>>[];
  var _failFirst = _netFailFirst;

  String get _today => businessToday(_zone);

  Map<String, dynamic> _day(String date, String status, {String? first, String? last, int worked = 0, Map<String, dynamic> over = const {}}) => {
        'id': 'day-$date',
        'employee_id': 'e-1',
        'attendance_date': date,
        'attendance_status': status,
        'timezone': _zone,
        'actual_first_in': first,
        'actual_last_out': last,
        'worked_minutes': worked,
        'is_locked': false,
        'calculation_version': 3,
        'calculated_at': DateTime.now().toUtc().toIso8601String(),
        ...over,
      };

  List<Map<String, dynamic>> _history() => [
        for (var i = 1; i <= 10; i++)
          () {
            final d = businessDayOffset(_zone, -i);
            if (i % 7 == 6 || i % 7 == 0) return _day(d, 'NOT_EXPECTED', over: {'calendar_day_type': 'WEEKLY_OFF'});
            if (i == 3) return _day(d, 'INCOMPLETE', first: '${d}T04:05:00Z', over: {'missing_punch': true});
            if (i == 4) return _day(d, 'LEAVE');
            return _day(d, 'PRESENT', first: '${d}T04:0${i % 5}:00Z', last: '${d}T12:3$i:00Z', worked: 500 + i, over: i == 2 ? {'is_late': true, 'late_minutes': 14} : {});
          }(),
      ];

  Map<String, dynamic>? _todayRow() {
    if (_punches.isEmpty) return _day(_today, 'ABSENT', over: {'scheduled_start': '${_today}T04:00:00Z', 'scheduled_end': '${_today}T12:30:00Z'});
    final ins = _punches.where((p) => p['direction'] == 'IN').toList();
    final outs = _punches.where((p) => p['direction'] == 'OUT').toList();
    final first = ins.isEmpty ? null : ins.last['punch_time'] as String;
    final last = outs.isEmpty ? null : outs.last['punch_time'] as String;
    final worked = (first != null && last != null) ? DateTime.parse(last).difference(DateTime.parse(first)).inMinutes.clamp(0, 1440) : 0;
    return _day(_today, last != null ? 'PRESENT' : 'INCOMPLETE', first: first, last: last, worked: worked, over: {'scheduled_start': '${_today}T04:00:00Z', 'scheduled_end': '${_today}T12:30:00Z'});
  }

  @override
  Future<List<AttendanceDay>> listAttendanceDays({String? employeeId, required String dateFrom, required String dateTo, String? attendanceStatus}) async {
    await Future<void>.delayed(const Duration(milliseconds: 300));
    return [..._history(), if (_todayRow() != null) _todayRow()!].where((d) => (d['attendance_date'] as String).compareTo(dateFrom) >= 0 && (d['attendance_date'] as String).compareTo(dateTo) <= 0).map(AttendanceDay.fromJson).toList();
  }

  @override
  Future<List<Punch>> listPunches({required String employeeId, required String dateFrom, required String dateTo}) async =>
      [for (final p in _punches.reversed) Punch.fromJson(p)];

  @override
  Future<AttendanceDay> getAttendanceDay(String id) async {
    final all = [..._history(), if (_todayRow() != null) _todayRow()!];
    return AttendanceDay.fromJson(all.firstWhere((d) => d['id'] == id));
  }

  @override
  Future<List<LeaveDayProjection>> listLeaveProjections({required String employeeId, required String dateFrom, required String dateTo}) async => const [];

  @override
  Future<FaceEnrollmentStatus> getMyFaceEnrollment() async =>
      _face == 'required' ? FaceEnrollmentStatus(profileStatus: 'ENROLLED', faceVerificationRequired: true) : FaceEnrollmentStatus();

  @override
  Future<GeofencePolicyMe> getMyGeofencePolicy() async =>
      _location == 'off' ? GeofencePolicyMe.disabled : const GeofencePolicyMe(mode: 'REQUIRED', maxAccuracyM: 50, maxAgeSeconds: 30);

  @override
  Future<void> punchMe({required String direction, String? reference, String? idempotencyKey, PunchLocation? location, LocationFailure? locationError}) async {
    await Future<void>.delayed(const Duration(milliseconds: _latencyMs));
    if (_failFirst) {
      _failFirst = false;
      throw ApiError(status: 0, code: 'NETWORK_ERROR', message: 'No connection. Check your network and try again.');
    }
    _punches.add({'id': 'p${_punches.length}', 'employee_id': 'e-1', 'punch_time': DateTime.now().toUtc().toIso8601String(), 'direction': direction, 'source': 'MOBILE'});
  }

  @override
  dynamic noSuchMethod(Invocation invocation) => super.noSuchMethod(invocation);
}

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  initTimeZones();
  final perms = switch (_persona) {
    'admin' => [dashboardCompanyView, ..._employeeRole, employeeViewAll, attendanceViewAll, settingsUserManage, orgShiftManage, payrollRunView],
    'hr_admin' => [dashboardCompanyView, ..._employeeRole, employeeViewAll, attendanceViewAll],
    _ => _employeeRole,
  };
  final api = FakeApiClient(
    objects: {
      '/employees/e-1': {'id': 'e-1', 'employee_code': 'EMP-007', 'first_name': 'Asha', 'last_name': 'Nair', 'status': 'ACTIVE', 'is_active': true, 'version': 1},
    },
    lists: {
      '/leave-balances': [
        {'employee_id': 'e-1', 'leave_type_id': 'lt-1', 'leave_type_code': 'CL', 'leave_type_name': 'Casual leave', 'balance': '8.5', 'reserved_balance': '1'},
        {'employee_id': 'e-1', 'leave_type_id': 'lt-2', 'leave_type_code': 'SL', 'leave_type_name': 'Sick leave', 'balance': '12', 'reserved_balance': '0'},
      ],
      '/leave-applications': [
        {'id': 'a-1', 'employee_id': 'e-1', 'leave_type_id': 'lt-1', 'start_date': businessDayOffset(_zone, 5), 'end_date': businessDayOffset(_zone, 6), 'total_days': '2', 'status': 'SUBMITTED', 'version': 1},
      ],
      '/regularizations': const [],
    },
    failing: {'/shifts': ApiError(status: 403, code: 'PERMISSION_DENIED', message: 'denied')},
  );
  runApp(ProviderScope(
    overrides: [
      fakeAuth(perms, employeeId: 'e-1'),
      apiClientProvider.overrideWithValue(api),
      attendanceRepositoryProvider.overrideWithValue(_Repo()),
      locationCaptureProvider.overrideWithValue(LocationCapture(_Gateway(_location))),
    ],
    child: const HrmsApp(),
  ));
}
