import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:hrms_mobile/core/api/api_error.dart';
import 'package:hrms_mobile/core/auth/permissions.dart';
import 'package:hrms_mobile/core/providers.dart';
import 'package:hrms_mobile/core/requests/request_screens.dart';
import 'package:hrms_mobile/core/theme/app_theme.dart';
import 'package:hrms_mobile/core/widgets/employee/attendance_history.dart';
import 'package:hrms_mobile/core/widgets/employee/check_in_action.dart';
import 'package:hrms_mobile/core/widgets/employee/layout.dart';
import 'package:hrms_mobile/core/widgets/employee/today_status_panel.dart';
import 'package:hrms_mobile/features/attendance/data/attendance_repository.dart';
import 'package:hrms_mobile/features/attendance/domain/punch_location.dart';
import 'package:hrms_mobile/features/attendance/domain/today_state.dart';
import 'package:hrms_mobile/features/attendance/presentation/attendance_day_detail_screen.dart';
import 'package:hrms_mobile/features/attendance/domain/employee_calendar.dart';
import 'package:hrms_mobile/features/attendance/presentation/geofences_screen.dart';
import 'package:hrms_mobile/features/attendance/presentation/my_calendar_screen.dart';
import 'package:hrms_mobile/features/attendance/presentation/attendance_month_card.dart';
import 'package:hrms_mobile/features/attendance/presentation/face_punch_card.dart';
import 'package:hrms_mobile/features/attendance/presentation/punch_location_flow.dart';
import 'package:hrms_mobile/features/attendance/domain/request_resources.dart';

import 'support/fake_api_client.dart';
import 'support/fake_auth.dart';
import 'support/test_themes.dart';

/// Visual reference for the screens changed in the second Phase 1 slice, rendered with the real
/// Inter (Regular/Medium/SemiBold/Bold, from `test/fonts/`, OFL) registered under the family names
/// `google_fonts` uses, so the typography is the approved one. Material Icons come from the SDK.
/// Everything is date-fixed (a clock-free fixture) so the images do not change from day to day.
///
/// Regenerate: `flutter test --update-goldens test/screens_golden_test.dart`.
/// Full-screen Home/Attendance are not here: they print today's date. They are covered by widget
/// tests and the device checklist instead.
Future<bool> _loadFonts() async {
  final fonts = Directory('test/fonts');
  if (!fonts.existsSync()) return false;
  ByteData bytes(String f) => ByteData.view(File('test/fonts/$f').readAsBytesSync().buffer);
  const families = {'Inter_regular': 'Inter-400.ttf', 'Inter_500': 'Inter-500.ttf', 'Inter_600': 'Inter-600.ttf', 'Inter_700': 'Inter-700.ttf'};
  for (final e in families.entries) {
    final loader = FontLoader(e.key)..addFont(Future.value(bytes(e.value)));
    await loader.load();
  }
  final root = Platform.environment['FLUTTER_ROOT'] ?? '${Platform.environment['HOME']}/flutter';
  final icons = File('$root/bin/cache/artifacts/material_fonts/MaterialIcons-Regular.otf');
  if (!icons.existsSync()) return false;
  final loader = FontLoader('MaterialIcons')..addFont(Future.value(ByteData.view(icons.readAsBytesSync().buffer)));
  await loader.load();
  return true;
}

const _zone = 'Asia/Kolkata';
final _fixedNow = DateTime.utc(2026, 10, 15, 6, 0); // Thursday 15 Oct 2026, 11:30 IST

Map<String, dynamic> _row(String id, String date, String status, {String? firstIn, String? lastOut, int worked = 0, Map<String, dynamic> over = const {}}) => {
      'id': id,
      'employee_id': 'e-1',
      'attendance_date': date,
      'attendance_status': status,
      'timezone': _zone,
      'actual_first_in': firstIn,
      'actual_last_out': lastOut,
      'worked_minutes': worked,
      'is_locked': false,
      'calculation_version': 2,
      'calculated_at': '${date}T13:00:00Z',
      ...over,
    };

class _Repo implements AttendanceRepository {
  _Repo(this.rows, {this.face});
  final List<Map<String, dynamic>> rows;
  final FaceEnrollmentStatus? face;

  @override
  Future<List<AttendanceDay>> listAttendanceDays({String? employeeId, required String dateFrom, required String dateTo, String? attendanceStatus}) async => rows.map(AttendanceDay.fromJson).toList();

  @override
  Future<AttendanceDay> getAttendanceDay(String id) async => AttendanceDay.fromJson(rows.firstWhere((r) => r['id'] == id));

  @override
  Future<List<LeaveDayProjection>> listLeaveProjections({required String employeeId, required String dateFrom, required String dateTo}) async => const [];

  @override
  Future<FaceEnrollmentStatus> getMyFaceEnrollment() async => face ?? FaceEnrollmentStatus();

  @override
  Future<GeofencePolicyMe> getMyGeofencePolicy() async => GeofencePolicyMe.disabled;

  @override
  dynamic noSuchMethod(Invocation invocation) => super.noSuchMethod(invocation);
}

Punch _p(String d, String at) => Punch.fromJson({'id': at, 'employee_id': 'e', 'punch_time': at, 'direction': d, 'source': 'MOBILE'});

TodayState _state({List<Punch>? punches = const [], AttendanceDay? day, bool dayFailed = false}) =>
    resolveTodayState(hasEmployee: true, loading: false, punches: punches, day: day, dayFailed: dayFailed, zone: _zone, today: '2026-10-15');

typedef _Variant = ({String tag, double w, double h, double scale});
const _variants = <_Variant>[
  (tag: '320', w: 320, h: 568, scale: 1.0),
  (tag: '360', w: 360, h: 800, scale: 1.0),
  (tag: '390', w: 390, h: 844, scale: 1.0),
  (tag: '320_x2', w: 320, h: 568, scale: 2.0),
];

Map<String, dynamic> _calendarFixture() {
  Map<String, dynamic> day(String date, String? type, {String? holiday, List<Map<String, dynamic>> leave = const [], bool configured = true}) =>
      {'date': date, 'configured': configured, 'day_type': type, 'holiday_name': holiday, 'is_holiday_named': holiday != null, 'weekly_off_fraction': type == 'WEEKLY_OFF' ? '1.00' : null, 'leave': leave};
  return {
    'from_date': '2026-10-26',
    'to_date': '2026-12-06',
    'configuration': 'COMPLETE',
    'leave_included': true,
    'days': [
      for (final date in datesBetween('2026-10-26', '2026-12-06'))
        switch (date) {
          '2026-11-09' => day(date, 'HOLIDAY', holiday: 'Founders Day'),
          '2026-11-10' => day(date, 'WORKING', leave: [{'status': 'APPROVED', 'fraction': '1.00'}]),
          '2026-11-11' => day(date, 'WORKING', leave: [{'status': 'PENDING', 'fraction': '0.50', 'half': 'FIRST_HALF'}]),
          '2026-11-18' => day(date, 'SPECIAL_WORKING', holiday: 'Audit day'),
          '2026-11-20' => day(date, 'SHUTDOWN', holiday: 'Plant shutdown'),
          _ => day(date, DateTime.parse('${date}T00:00:00Z').weekday == DateTime.sunday ? 'WEEKLY_OFF' : 'WORKING'),
        },
    ],
  };
}

void _golden(String name, Widget Function(_Variant v) build, {List<Override> overrides = const [], Future<void> Function(WidgetTester tester)? beforeShot, List<_Variant> variants = _variants, bool settle = true, List<String> permissions = const [attendancePunch, attendanceView, attendanceRegularizationRequest]}) {
  for (final v in variants) {
    testWidgets('$name @ ${v.tag}', (tester) async {
      if (!await tester.runAsync(_loadFonts).then((ok) => ok ?? false)) {
        markTestSkipped('Inter (test/fonts) or the SDK icon font is missing; goldens need the approved typography.');
        return;
      }
      tester.view.physicalSize = Size(v.w, v.h);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.reset);
      await tester.pumpWidget(ProviderScope(
        overrides: [fakeAuth(permissions, employeeId: 'e-1'), ...overrides],
        child: MaterialApp(
          debugShowCheckedModeBanner: false,
          theme: AppTheme.employee,
          builder: (context, child) => MediaQuery(data: MediaQuery.of(context).copyWith(textScaler: TextScaler.linear(v.scale)), child: child!),
          home: build(v),
        ),
      ));
      // A busy spinner never settles; pin it to a fixed frame instead.
      settle ? await tester.pumpAndSettle() : await tester.pump(const Duration(milliseconds: 300));
      await beforeShot?.call(tester);
      expect(tester.takeException(), isNull);
      await expectLater(find.byType(MaterialApp), matchesGoldenFile('goldens/screens/${name}_${v.tag}.png'));
    });
  }
}

Widget _page(List<Widget> children) => Scaffold(
      backgroundColor: AppTheme.employee.scaffoldBackgroundColor,
      body: SingleChildScrollView(padding: const EdgeInsets.all(16), child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [for (final c in children) Padding(padding: const EdgeInsets.only(bottom: 12), child: c)])),
    );

void main() {
  setUpAll(primeThemes);

  _golden('today_panel_states', (v) {
    final inAt = '2026-10-15T04:00:00Z';
    return _page([
      TodayStatusPanel(state: _state(), zone: _zone),
      TodayStatusPanel(state: _state(day: AttendanceDay.fromJson(_row('a', '2026-10-15', 'ABSENT'))), zone: _zone, scheduleText: 'Scheduled 9:30 am – 6:00 pm IST'),
      TodayStatusPanel(
        state: _state(punches: [_p('IN', inAt)], day: AttendanceDay.fromJson(_row('b', '2026-10-15', 'INCOMPLETE', firstIn: inAt, worked: 95, over: {'calculated_at': '2026-10-15T05:50:00Z', 'is_late': true, 'late_minutes': 12}))),
        zone: _zone,
      ),
      TodayStatusPanel(state: _state(punches: [_p('OUT', '2026-10-15T12:30:00Z')], day: AttendanceDay.fromJson(_row('c', '2026-10-15', 'PRESENT', firstIn: inAt, lastOut: '2026-10-15T12:30:00Z', worked: 510, over: {'calculated_at': '2026-10-15T12:31:00Z'}))), zone: _zone),
      TodayStatusPanel(state: _state(punches: null, dayFailed: true), zone: _zone, onRetry: () {}),
    ]);
  });

  _golden('check_in_action', (v) => _page([
        CheckInAction(likely: LikelyPunch.punchIn, faceRequired: false, busy: false, ready: true, onPunch: (_) {}),
        CheckInAction(likely: LikelyPunch.punchOut, faceRequired: false, busy: false, ready: true, onPunch: (_) {}),
        CheckInAction(likely: LikelyPunch.punchOut, faceRequired: true, busy: false, ready: true, onPunch: (_) {}),
        CheckInAction(likely: LikelyPunch.equal, faceRequired: false, busy: false, ready: true, onPunch: (_) {}),
        CheckInAction(likely: LikelyPunch.punchIn, faceRequired: false, busy: true, ready: true, busyLabel: 'Recording punch…', onPunch: (_) {}),
        CheckInAction(likely: LikelyPunch.punchIn, faceRequired: false, busy: false, ready: false, onPunch: (_) {}),
      ]), settle: false);

  _golden('history_group', (v) {
    AttendanceDay d(String id, String date, String status, {String? i, String? o, int w = 0}) => AttendanceDay.fromJson(_row(id, date, status, firstIn: i, lastOut: o, worked: w));
    return _page([
      const EmployeeSectionHeaderPad('Last 14 days'),
      AttendanceHistoryGroup(today: '2026-10-15', onTap: (_) {}, days: [
        d('1', '2026-10-15', 'ABSENT'),
        d('2', '2026-10-14', 'PRESENT', i: '2026-10-14T04:00:00Z', o: '2026-10-14T12:30:00Z', w: 510),
        d('3', '2026-10-13', 'HALF_DAY', i: '2026-10-13T04:00:00Z', o: '2026-10-13T08:30:00Z', w: 270),
        d('4', '2026-10-12', 'LEAVE'),
        d('5', '2026-10-11', 'INCOMPLETE', i: '2026-10-11T04:00:00Z'),
      ]),
    ]);
  });

  _golden('month_card', (v) => Scaffold(
        body: SingleChildScrollView(padding: const EdgeInsets.all(16), child: AttendanceMonthCard(employeeId: 'e-1', zone: _zone, now: _fixedNow)),
      ),
      overrides: [
        attendanceRepositoryProvider.overrideWithValue(_Repo([
          _row('m1', '2026-10-01', 'PRESENT', firstIn: '2026-10-01T04:00:00Z', lastOut: '2026-10-01T12:30:00Z', worked: 510),
          _row('m2', '2026-10-02', 'PRESENT', firstIn: '2026-10-02T04:00:00Z', lastOut: '2026-10-02T12:30:00Z', worked: 510),
          _row('m5', '2026-10-05', 'LEAVE'),
          _row('m6', '2026-10-06', 'HALF_DAY', firstIn: '2026-10-06T04:00:00Z', lastOut: '2026-10-06T08:30:00Z', worked: 270),
          _row('m7', '2026-10-07', 'ABSENT'),
          _row('m10', '2026-10-10', 'NOT_EXPECTED', over: {'calendar_day_type': 'WEEKLY_OFF'}),
          _row('m15', '2026-10-15', 'ABSENT'),
        ])),
      ]);

  for (final spec in {
    'day_detail_complete': _row('d1', '2026-10-09', 'PRESENT', firstIn: '2026-10-09T04:05:00Z', lastOut: '2026-10-09T12:40:00Z', worked: 515, over: {
      'is_late': true, 'late_minutes': 35, 'is_overtime': true, 'ot_minutes_detected': 25, 'scheduled_start': '2026-10-09T03:30:00Z', 'scheduled_end': '2026-10-09T12:30:00Z', 'scheduled_minutes': 540,
      'unpaid_break_minutes': 20, 'paid_day_fraction': '1.0', 'breaks': [{'break_start': '2026-10-09T07:00:00Z', 'break_end': '2026-10-09T07:20:00Z', 'minutes': 20, 'is_paid': false}],
    }),
    'day_detail_incomplete': _row('d2', '2026-10-08', 'INCOMPLETE', firstIn: '2026-10-08T04:00:00Z', over: {'missing_punch': true, 'is_pending_approval': true, 'scheduled_start': '2026-10-08T03:30:00Z', 'scheduled_end': '2026-10-08T12:30:00Z'}),
    'day_detail_no_punches': _row('d3', '2026-10-07', 'ABSENT'),
  }.entries) {
    _golden(spec.key, (v) => AttendanceDayDetailScreen(dayId: spec.value['id'] as String), overrides: [attendanceRepositoryProvider.overrideWithValue(_Repo([spec.value]))]);
  }

  _golden('face_card', (v) => _page([
        FacePunchCard(showButtons: false, key: const ValueKey('f1')),
      ]), overrides: [attendanceRepositoryProvider.overrideWithValue(_Repo(const [], face: FaceEnrollmentStatus(profileStatus: 'PENDING_APPROVAL')))], variants: [_variants[0], _variants[3]]);

  _golden('face_card_enrolled', (v) => _page([FacePunchCard(showButtons: false, key: const ValueKey('f2'))]),
      overrides: [attendanceRepositoryProvider.overrideWithValue(_Repo(const [], face: FaceEnrollmentStatus(profileStatus: 'ENROLLED', faceVerificationRequired: true)))], variants: [_variants[0], _variants[3]]);

  _golden('face_card_not_set_up', (v) => _page([FacePunchCard(key: const ValueKey('f3'))]), variants: [_variants[0], _variants[3]]);

  _golden('location_dialog', (v) => _DialogHost(failure: LocationFailure.permissionDeniedForever), beforeShot: (tester) async {
    await tester.tap(find.text('show'));
    await tester.pumpAndSettle();
  });

  _golden('location_dialog_poor_accuracy', (v) => _DialogHost(failure: LocationFailure.poorAccuracy), beforeShot: (tester) async {
    await tester.tap(find.text('show'));
    await tester.pumpAndSettle();
  }, variants: [_variants[0], _variants[3]]);

  _golden('my_calendar', (v) => MyCalendarScreen(now: DateTime.utc(2026, 11, 5, 6)), overrides: [
    apiClientProvider.overrideWithValue(FakeApiClient(objects: {'/employee-calendar/me': _calendarFixture()})),
  ]);

  _golden('geofences', (v) => const GeofencesScreen(), permissions: const [attendancePolicyManage, attendanceViewAll, orgBranchManage], overrides: [
    apiClientProvider.overrideWithValue(FakeApiClient(lists: {
      '/attendance/geofences': const [
        {'branch_id': 'b-1', 'name': 'Head Office', 'code': null, 'is_active': true, 'latitude': 12.9716, 'longitude': 77.5946, 'radius_m': 150, 'configured': true, 'assigned_employee_count': 12, 'authorized_employee_count': 2},
        {'branch_id': 'b-2', 'name': 'Plant', 'code': null, 'is_active': true, 'latitude': null, 'longitude': null, 'radius_m': null, 'configured': false, 'assigned_employee_count': 4, 'authorized_employee_count': 0},
      ],
    })),
  ]);

  _golden('correction_form_shifts_denied', (v) => RequestListScreen(config: regularizationConfig), overrides: [
    apiClientProvider.overrideWithValue(FakeApiClient(
      lists: {'/regularizations': const []},
      failing: {'/shifts': ApiError(status: 403, code: 'PERMISSION_DENIED', message: 'denied')},
    )),
  ], beforeShot: (tester) async {
    await tester.tap(find.text('Regularization request'));
    await tester.pumpAndSettle();
  });
}

class EmployeeSectionHeaderPad extends StatelessWidget {
  const EmployeeSectionHeaderPad(this.title, {super.key});
  final String title;
  @override
  Widget build(BuildContext context) => Transform.translate(offset: const Offset(-16, 0), child: EmployeeSectionHeader(title));
}

class _DialogHost extends StatelessWidget {
  const _DialogHost({required this.failure});
  final LocationFailure failure;

  @override
  Widget build(BuildContext context) => Scaffold(
        body: Center(
          child: TextButton(
            onPressed: () => showLocationProblemDialog(context, failure, _NoopCapture()),
            child: const Text('show'),
          ),
        ),
      );
}

class _NoopCapture extends LocationCapture {
  _NoopCapture() : super(_NoGateway());
}

class _NoGateway implements LocationGateway {
  @override
  dynamic noSuchMethod(Invocation invocation) => super.noSuchMethod(invocation);
}
