import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:hrms_mobile/core/auth/permissions.dart';
import 'package:hrms_mobile/core/providers.dart';
import 'package:hrms_mobile/core/theme/app_theme.dart';
import 'package:hrms_mobile/features/attendance/data/attendance_repository.dart';
import 'package:hrms_mobile/features/attendance/domain/day_timeline.dart';
import 'package:hrms_mobile/features/attendance/presentation/attendance_day_detail_screen.dart';
import 'package:hrms_mobile/features/profile/data/employee_repository.dart';
import 'package:hrms_mobile/features/profile/presentation/profile_screen.dart' show employeeRepositoryProvider;

import 'support/fake_api_client.dart';
import 'support/fake_auth.dart';

/// The attendance day's identity line, previous/next day and punch timeline — web
/// `components/attendance/day/day-summary.tsx` and `day-timeline.tsx`.

Map<String, dynamic> _row(String id, String date, {Map<String, dynamic> over = const {}}) => {
      'id': id,
      'employee_id': 'e-1',
      'attendance_date': date,
      'attendance_status': 'PRESENT',
      'timezone': 'Asia/Kolkata',
      'shift_id': 's-1',
      'scheduled_start': '${date}T03:30:00Z',
      'scheduled_end': '${date}T12:30:00Z',
      'actual_first_in': '${date}T03:40:00Z',
      'is_locked': false,
      ...over,
    };

class _Repo implements AttendanceRepository {
  _Repo(this.days, {this.punches = const [], this.breaks = const []});
  final Map<String, Map<String, dynamic>> days;
  final List<Punch> punches;
  final List<BreakEvent> breaks;
  final opened = <String>[];

  @override
  Future<AttendanceDay> getAttendanceDay(String id) async {
    opened.add(id);
    return AttendanceDay.fromJson(days[id]!);
  }

  @override
  Future<List<LeaveDayProjection>> listLeaveProjections({required String employeeId, required String dateFrom, required String dateTo}) async => const [];

  @override
  Future<List<Punch>> listPunches({required String employeeId, required String dateFrom, required String dateTo}) async => punches;

  @override
  Future<List<BreakEvent>> listBreakEvents({required String employeeId, required String date}) async => breaks;

  @override
  Future<List<Shift>> listShifts() async => [Shift(id: 's-1', name: 'General', isActive: true, version: 1)];

  @override
  Future<List<AttendanceDay>> listAttendanceDays({String? employeeId, required String dateFrom, required String dateTo, String? attendanceStatus}) async => [
        for (final d in days.values)
          if (d['attendance_date'].compareTo(dateFrom) >= 0 && d['attendance_date'].compareTo(dateTo) <= 0) AttendanceDay.fromJson(d),
      ];

  @override
  dynamic noSuchMethod(Invocation invocation) => super.noSuchMethod(invocation);
}

class _Employees implements EmployeeRepository {
  @override
  Future<Employee> getEmployee(String employeeId) async =>
      Employee.fromJson({'id': employeeId, 'employee_code': 'EMP-7', 'first_name': 'Asha', 'last_name': 'Rao', 'status': 'ACTIVE', 'is_active': true, 'version': 1});

  @override
  dynamic noSuchMethod(Invocation invocation) => super.noSuchMethod(invocation);
}

void main() {
  Future<_Repo> pump(WidgetTester tester, _Repo repo, {String dayId = 'd-2'}) async {
    tester.view.physicalSize = const Size(400, 3000);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.reset);
    await tester.pumpWidget(ProviderScope(
      overrides: [
        attendanceRepositoryProvider.overrideWithValue(repo),
        employeeRepositoryProvider.overrideWithValue(_Employees()),
        apiClientProvider.overrideWithValue(FakeApiClient()),
        fakeAuth(const [attendanceView, attendanceViewAll]),
      ],
      child: MaterialApp(theme: AppTheme.employee, home: AttendanceDayDetailScreen(dayId: dayId)),
    ));
    await tester.pumpAndSettle();
    return repo;
  }

  testWidgets('shows who, the shift, and the punches and breaks in order', (tester) async {
    await pump(
      tester,
      _Repo(
        {'d-2': _row('d-2', '2026-10-02', over: {'missing_punch': true})},
        punches: [Punch(id: 'p1', employeeId: 'e-1', punchTime: '2026-10-02T03:40:00Z', direction: 'IN', source: 'MOBILE')],
        breaks: const [BreakEvent(id: 'b1', eventType: 'START', eventTime: '2026-10-02T07:30:00Z', breakName: 'Lunch', source: 'WEB')],
      ),
    );
    expect(find.text('PUNCH TIMELINE'), findsOneWidget);
    expect(find.text('Punched in'), findsOneWidget);
    expect(find.text('Mobile app'), findsOneWidget);
    expect(find.text('Break started — Lunch'), findsOneWidget);
    expect(find.text('Punch-out missing'), findsOneWidget);
    expect(find.textContaining('Asha Rao'), findsOneWidget);
    expect(find.textContaining('EMP-7 · General'), findsOneWidget);
    expect(find.text('Missing'), findsOneWidget);
  });

  testWidgets('an empty day says so', (tester) async {
    await pump(tester, _Repo({'d-2': _row('d-2', '2026-10-02')}));
    expect(find.text('No punches or breaks recorded for this day.'), findsOneWidget);
  });

  testWidgets('previous and next open the neighbouring days; none recorded means disabled', (tester) async {
    final repo = await pump(tester, _Repo({'d-1': _row('d-1', '2026-10-01'), 'd-2': _row('d-2', '2026-10-02')}));
    IconButton button(String tip) => tester.widget<IconButton>(find.widgetWithIcon(IconButton, tip == 'Previous day' ? Icons.chevron_left_rounded : Icons.chevron_right_rounded));
    expect(button('Previous day').onPressed, isNotNull);
    expect(button('Next day').onPressed, isNull);

    await tester.tap(find.byTooltip('Previous day'));
    await tester.pumpAndSettle();
    expect(repo.opened.last, 'd-1');
    expect(find.text('2026-10-01'), findsWidgets);
    expect(button('Previous day').onPressed, isNull);
    expect(button('Next day').onPressed, isNotNull);
  });
}
