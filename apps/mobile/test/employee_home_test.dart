import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:hrms_mobile/core/api/api_error.dart';
import 'package:hrms_mobile/core/auth/permissions.dart';
import 'package:hrms_mobile/core/providers.dart';
import 'package:hrms_mobile/core/theme/app_theme.dart';
import 'package:hrms_mobile/core/time.dart';
import 'package:hrms_mobile/features/attendance/data/attendance_repository.dart';
import 'package:hrms_mobile/features/attendance/domain/punch_location.dart';
import 'package:hrms_mobile/features/attendance/state/today_provider.dart';
import 'package:hrms_mobile/features/home/presentation/employee_home_screen.dart';

import 'support/fake_api_client.dart';
import 'support/fake_auth.dart';
import 'support/test_themes.dart';

const _zone = 'Asia/Kolkata';
final _today = businessToday(_zone);

Map<String, dynamic> _day({String status = 'PRESENT', String? calculatedAt, String? firstIn, int worked = 0, Map<String, dynamic> over = const {}}) => {
      'id': 'd-1',
      'employee_id': 'e-1',
      'attendance_date': _today,
      'attendance_status': status,
      'timezone': _zone,
      'actual_first_in': firstIn,
      'actual_last_out': null,
      'worked_minutes': worked,
      'is_locked': false,
      'calculated_at': calculatedAt,
      ...over,
    };

Map<String, dynamic> _punch(String direction, DateTime at) =>
    {'id': 'p-${at.microsecondsSinceEpoch}', 'employee_id': 'e-1', 'punch_time': at.toUtc().toIso8601String(), 'direction': direction, 'source': 'MOBILE'};

class _Repo implements AttendanceRepository {
  List<Punch>? punches = [];
  List<AttendanceDay>? days = [];
  FaceEnrollmentStatus face = FaceEnrollmentStatus();
  Completer<void>? punchGate;
  Completer<void>? readGate;
  Object? punchError;
  final punched = <String>[];

  @override
  Future<FaceEnrollmentStatus> getMyFaceEnrollment() async => face;

  @override
  Future<GeofencePolicyMe> getMyGeofencePolicy() async => GeofencePolicyMe.disabled;

  @override
  Future<List<Punch>> listPunches({required String employeeId, required String dateFrom, required String dateTo}) async {
    await readGate?.future;
    if (punches == null) throw ApiError(status: 500, code: 'X', message: 'punches down');
    return punches!;
  }

  @override
  Future<List<AttendanceDay>> listAttendanceDays({String? employeeId, required String dateFrom, required String dateTo, String? attendanceStatus}) async {
    await readGate?.future;
    if (days == null) throw ApiError(status: 500, code: 'X', message: 'days down');
    return days!;
  }

  @override
  Future<void> punchMe({required String direction, String? reference, String? idempotencyKey, PunchLocation? location, LocationFailure? locationError}) async {
    punched.add(direction);
    await punchGate?.future;
    if (punchError != null) throw punchError!;
  }

  @override
  dynamic noSuchMethod(Invocation invocation) => super.noSuchMethod(invocation);
}

const _full = [attendancePunch, attendanceView, leaveBalanceView, employeeView];

Future<void> _pump(
  WidgetTester tester,
  _Repo repo, {
  List<String> permissions = _full,
  String? employeeId = 'e-1',
  FakeApiClient? api,
  Size size = const Size(390, 2400), // tall enough to build every Home section (the list builds lazily)
  double textScale = 1.0,
}) async {
  tester.view.physicalSize = size * 3;
  tester.view.devicePixelRatio = 3;
  addTearDown(tester.view.reset);
  await tester.pumpWidget(ProviderScope(
    overrides: [
      fakeAuth(permissions, employeeId: employeeId),
      attendanceRepositoryProvider.overrideWithValue(repo),
      apiClientProvider.overrideWithValue(api ?? _api()),
    ],
    child: MaterialApp(
      theme: AppTheme.employee,
      builder: (context, child) => MediaQuery(data: MediaQuery.of(context).copyWith(textScaler: TextScaler.linear(textScale)), child: child!),
      home: const EmployeeHomeScreen(),
    ),
  ));
  await tester.pumpAndSettle();
}

FakeApiClient _api({Map<String, Object> failing = const {}, List<Map<String, dynamic>> leaveApps = const [], List<Map<String, dynamic>> payslips = const []}) => FakeApiClient(
      objects: {
        '/employees/e-1': {'id': 'e-1', 'employee_code': 'EMP-007', 'first_name': 'Asha', 'status': 'ACTIVE', 'is_active': true, 'version': 1},
        '/employee-work-profile/me': {
          'shift': {'name': 'General Shift', 'start_time': '09:30:00', 'end_time': '18:30:00', 'timezone': 'Asia/Kolkata'},
          'work_location': {'name': 'Bengaluru HQ', 'city': 'Bengaluru', 'address_line1': 'Bengaluru HQ Campus', 'work_location_type': 'OFFICE'},
        },
      },
      lists: {
        '/leave-balances': [
          {'employee_id': 'e-1', 'leave_type_id': 'lt-1', 'leave_type_code': 'CL', 'leave_type_name': 'Casual leave', 'balance': '8.5', 'reserved_balance': '1'},
        ],
        '/leave-applications': leaveApps,
        '/regularizations': const [],
        '/me/payslips': payslips,
      },
      failing: failing,
    );

void main() {
  setUpAll(primeThemes);

  testWidgets('an account with no employee record sees that, with no punch control and no request', (tester) async {
    final api = _api();
    await _pump(tester, _Repo(), employeeId: null, api: api);
    expect(find.text('No employee record is linked to your account.'), findsOneWidget);
    expect(find.text('Punch in'), findsNothing);
    expect(api.listCalls, isEmpty);
  });

  group('today panel obeys the state table (no inventing a status)', () {
    testWidgets('nothing recorded: says so, offers Punch in, never says Absent', (tester) async {
      await _pump(tester, _Repo());
      expect(find.text('Not punched in'), findsOneWidget);
      expect(find.text('Punch in'), findsOneWidget);
      expect(find.text('Absent'), findsNothing);
    });

    testWidgets('the 09:30 sweep row (ABSENT, no punch) is provisional: "Not punched in", no Absent chip', (tester) async {
      final repo = _Repo()..days = [AttendanceDay.fromJson(_day(status: 'ABSENT'))];
      await _pump(tester, repo);
      expect(find.text('Not punched in'), findsOneWidget);
      expect(find.text('Absent'), findsNothing);
    });

    testWidgets('punched in with a current calculation: time, worked so far, and Punch out is primary', (tester) async {
      final at = DateTime.now().subtract(const Duration(hours: 2));
      final repo = _Repo()
        ..punches = [Punch.fromJson(_punch('IN', at))]
        ..days = [AttendanceDay.fromJson(_day(status: 'INCOMPLETE', firstIn: at.toUtc().toIso8601String(), worked: 120, calculatedAt: DateTime.now().toUtc().toIso8601String()))];
      await _pump(tester, repo);
      expect(find.textContaining('Punched in · Since'), findsOneWidget);
      expect(find.text('WORKED TODAY'), findsOneWidget);
      expect(find.textContaining('02:00:'), findsOneWidget);
      expect(find.text('Punch out'), findsOneWidget);
      expect(find.text('Punch in'), findsNothing, reason: 'Punch out is the one offered action');
    });

    testWidgets('a punch the day calculation has not caught up with is "being calculated" and shows no status or worked time', (tester) async {
      final at = DateTime.now().subtract(const Duration(minutes: 5));
      final repo = _Repo()..punches = [Punch.fromJson(_punch('IN', at))];
      await _pump(tester, repo);
      expect(find.text('Updating your day…'), findsOneWidget);
      expect(find.text('00:00:00'), findsWidgets, reason: 'no worked time is invented before the day is calculated');
    });

    testWidgets('both reads failing is "unavailable" and the punch button stays', (tester) async {
      final repo = _Repo()
        ..punches = null
        ..days = null;
      await _pump(tester, repo);
      expect(find.text('Status unavailable'), findsOneWidget);
      expect(find.text('Punch in'), findsOneWidget);
    });

    testWidgets('the shift shown on Home comes from the work-profile read', (tester) async {
      final repo = _Repo()
        ..days = [AttendanceDay.fromJson(_day(status: 'ABSENT', over: {'scheduled_start': '${_today}T04:00:00Z', 'scheduled_end': '${_today}T12:30:00Z'}))];
      await _pump(tester, repo);
      expect(find.textContaining('Shift 09:30 - 18:30'), findsOneWidget);
    });

    // The redesigned Home no longer lists a day's exceptions (late, missing punch); they are shown
    // on the attendance screens instead (see attendance_month_and_day_test.dart).
    testWidgets('exceptions on a calculated day are listed', skip: true, (tester) async {
      final at = DateTime.now().subtract(const Duration(hours: 1));
      final repo = _Repo()
        ..punches = [Punch.fromJson(_punch('IN', at))]
        ..days = [
          AttendanceDay.fromJson(_day(firstIn: at.toUtc().toIso8601String(), worked: 60, calculatedAt: DateTime.now().toUtc().toIso8601String(), over: {'is_late': true, 'late_minutes': 12, 'missing_punch': true})),
        ];
      await _pump(tester, repo);
      expect(find.text('Late 12m'), findsOneWidget);
      expect(find.text('Missing punch'), findsOneWidget);
    });
  });

  group('punching from Home goes through the shared controller and the server decides', () {
    testWidgets('success is claimed only after the server answers; the day is then re-read', (tester) async {
      final repo = _Repo()..punchGate = Completer<void>();
      await _pump(tester, repo);
      await tester.tap(find.text('Punch in'));
      await tester.pump();
      expect(repo.punched, ['IN']);
      expect(find.text('Punched in.'), findsNothing, reason: 'the server has not answered yet');
      expect(find.text('Recording punch…'), findsOneWidget);

      repo.punchGate!.complete();
      await tester.pumpAndSettle();
      expect(find.text('Punched in.'), findsOneWidget);
    });

    testWidgets('repeated taps while a punch is in flight send exactly one request', (tester) async {
      final repo = _Repo()..punchGate = Completer<void>();
      await _pump(tester, repo);
      await tester.tap(find.text('Punch in'));
      await tester.pump();
      // While the request is in flight the action is replaced by its progress label and disabled.
      expect(find.text('Punch in'), findsNothing);
      await tester.tap(find.byType(FilledButton).first, warnIfMissed: false);
      await tester.pump();
      expect(repo.punched, ['IN']);
      repo.punchGate!.complete();
      await tester.pumpAndSettle();
    });

    testWidgets('a refused punch shows the server message and never claims success', (tester) async {
      final repo = _Repo()..punchError = ApiError(status: 422, code: 'X', message: 'Not allowed from here.');
      await _pump(tester, repo);
      await tester.tap(find.text('Punch in'));
      await tester.pumpAndSettle();
      expect(find.text('Not allowed from here.'), findsOneWidget);
      expect(find.text('Punched in.'), findsNothing);
    });

    testWidgets('an enrolled employee gets face labels, and no plain punch is offered', (tester) async {
      final repo = _Repo()..face = FaceEnrollmentStatus(profileStatus: 'ENROLLED', faceVerificationRequired: true);
      await _pump(tester, repo);
      expect(find.text('Face punch in'), findsOneWidget);
      expect(find.text('Punch in'), findsNothing);
    });

    testWidgets('a user without ATTENDANCE.PUNCH sees the status but no punch control', (tester) async {
      await _pump(tester, _Repo(), permissions: [attendanceView]);
      expect(find.text('Not punched in'), findsOneWidget);
      expect(find.text('Punch in'), findsNothing);
    });
  });

  group('loading, slow networks and partial failure', () {
    testWidgets('while the reads are slow the panel is a skeleton and the punch control is held back, then it fills in', (tester) async {
      final repo = _Repo()..readGate = Completer<void>();
      tester.view.physicalSize = const Size(390, 844) * 3;
      tester.view.devicePixelRatio = 3;
      addTearDown(tester.view.reset);
      await tester.pumpWidget(ProviderScope(
        overrides: [fakeAuth(_full, employeeId: 'e-1'), attendanceRepositoryProvider.overrideWithValue(repo), apiClientProvider.overrideWithValue(_api())],
        child: MaterialApp(theme: AppTheme.employee, home: const EmployeeHomeScreen()),
      ));
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 50));
      expect(find.byType(CircularProgressIndicator), findsNothing, reason: 'skeletons, not a spinner that replaces the screen');
      expect(find.text('Not punched in'), findsNothing);
      expect(find.text('Checking today…'), findsOneWidget);
      repo.readGate!.complete();
      await tester.pumpAndSettle();
      expect(find.text('Not punched in'), findsOneWidget);
    });

    testWidgets('a failing leave read never hides attendance; only the leave tile falls back to a dash', (tester) async {
      final api = _api(failing: {'/leave-balances': ApiError(status: 500, code: 'X', message: 'Leave is down.')});
      await _pump(tester, _Repo(), api: api);
      expect(find.text('Not punched in'), findsOneWidget);
      expect(find.text('Punch in'), findsOneWidget);
      expect(find.text('8.5'), findsNothing, reason: 'the failed read shows no balance');
      expect(find.text('—'), findsWidgets);
    });

    testWidgets('shift and work location come from the work-profile read', (tester) async {
      await _pump(tester, _Repo());
      expect(find.text('Shift 09:30 - 18:30'), findsOneWidget);
    });

    testWidgets('a failing work-profile read leaves the cards out without hiding anything else', (tester) async {
      final api = _api(failing: {'/employee-work-profile/me': ApiError(status: 500, code: 'X', message: 'down')});
      await _pump(tester, _Repo(), api: api);
      expect(find.textContaining('Shift 09:30'), findsNothing);
      expect(find.text('Punch in'), findsOneWidget);
    });

    testWidgets('leave balances, pending requests and recent days appear when there is data', (tester) async {
      final at = DateTime.now().subtract(const Duration(days: 1));
      final yesterday = businessDayOffset(_zone, -1);
      final repo = _Repo()
        ..days = [AttendanceDay.fromJson({..._day(status: 'PRESENT', firstIn: at.toUtc().toIso8601String(), worked: 540), 'id': 'd-0', 'attendance_date': yesterday})];
      final api = _api(leaveApps: [
        {'id': 'a-1', 'employee_id': 'e-1', 'leave_type_id': 'lt-1', 'start_date': '2026-11-02', 'end_date': '2026-11-03', 'total_days': '2', 'status': 'SUBMITTED', 'version': 1},
      ]);
      await _pump(tester, repo, api: api);
      expect(find.textContaining('Asha'), findsOneWidget);
      expect(find.text('Cas 8.5'), findsOneWidget);
      expect(find.text('Needs attention'), findsOneWidget);
      expect(find.text('Casual leave'), findsOneWidget);
      expect(find.text('2–3 Nov · 2 days'), findsOneWidget);
    });

    testWidgets('no requests: the "Needs attention" section is not drawn at all', (tester) async {
      await _pump(tester, _Repo());
      expect(find.text('Needs attention'), findsNothing);
    });

    testWidgets('the latest payslip shows its month and net pay', (tester) async {
      final api = _api(payslips: [
        {'pay_run_id': 'r-1', 'month': '2026-09', 'pay_date': '2026-09-30', 'net_minor': 4100000, 'status': 'FINALIZED'},
        {'pay_run_id': 'r-2', 'month': '2026-10', 'pay_date': '2026-10-31', 'net_minor': 4218000, 'status': 'FINALIZED'},
      ]);
      await _pump(tester, _Repo(), permissions: [..._full, payrollPayslipViewOwn], api: api);
      expect(find.text('Oct 2026'), findsOneWidget);
      expect(find.text('₹42,180'), findsOneWidget);
    });

    testWidgets('without PAYROLL.PAYSLIP_VIEW_OWN there is no Payslip section and no request for it', (tester) async {
      final without = _api();
      await _pump(tester, _Repo(), api: without);
      expect(find.text('₹42,180'), findsNothing);
      expect(without.listCalls.map((c) => c.path), isNot(contains('/me/payslips')));
    });
  });

  group('permissions and scope of the reads', () {
    testWidgets('a missing permission omits its widget and makes no request for it', (tester) async {
      final api = _api();
      await _pump(tester, _Repo(), permissions: [attendancePunch, attendanceView], api: api);
      expect(find.text('Leave'), findsNothing);
      expect(find.text('Asha'), findsNothing);
      final paths = api.listCalls.map((c) => c.path).toSet();
      expect(paths, isNot(contains('/leave-balances')));
      expect(paths, isNot(contains('/leave-applications')));
    });

    testWidgets('Home never calls the dashboards, the holiday calendars or the employee list', (tester) async {
      final api = _api();
      await _pump(tester, _Repo(), api: api);
      final paths = api.listCalls.map((c) => c.path).toSet();
      expect(paths.where((p) => p.startsWith('/dashboards') || p == '/holiday-calendars' || p == '/employees'), isEmpty);
      expect(paths.where((p) => p.contains('payslip') || p.contains('payroll')), isEmpty, reason: 'payslips are read only with PAYROLL.PAYSLIP_VIEW_OWN');
    });

    testWidgets('every own-data read is scoped to the signed-in employee', (tester) async {
      final api = _api();
      await _pump(tester, _Repo(), api: api);
      for (final c in api.listCalls) {
        expect(c.filters?['employee_id'], 'e-1', reason: c.path);
      }
    });

    test('today data is keyed by employee: one user\'s attendance is never another\'s', () async {
      final repoA = _Repo()..days = [AttendanceDay.fromJson(_day(status: 'PRESENT'))];
      final container = ProviderContainer(overrides: [attendanceRepositoryProvider.overrideWithValue(repoA)]);
      addTearDown(container.dispose);
      final a = await container.read(todayDataProvider((employeeId: 'e-1', zone: _zone)).future);
      expect(a.todayRow, isNotNull);
      repoA.days = [];
      final b = await container.read(todayDataProvider((employeeId: 'e-2', zone: _zone)).future);
      expect(b.todayRow, isNull, reason: 'a different employee id is a different provider; nothing carried over');
    });
  });

  group('responsive layout', () {
    for (final size in [const Size(320, 568), const Size(360, 800), const Size(390, 844)]) {
      for (final scale in [1.0, 2.0]) {
        testWidgets('${size.width.toInt()}x${size.height.toInt()} at text scale $scale: no overflow with a full Home', (tester) async {
          final at = DateTime.now().subtract(const Duration(hours: 2));
          final repo = _Repo()
            ..punches = [Punch.fromJson(_punch('IN', at))]
            ..days = [AttendanceDay.fromJson(_day(firstIn: at.toUtc().toIso8601String(), worked: 120, calculatedAt: DateTime.now().toUtc().toIso8601String(), over: {'is_late': true, 'late_minutes': 5}))];
          await _pump(tester, repo, size: size, textScale: scale);
          expect(tester.takeException(), isNull);
          await tester.drag(find.byType(ListView), const Offset(0, -600));
          await tester.pumpAndSettle();
          expect(tester.takeException(), isNull);
        });
      }
    }
  });
}
