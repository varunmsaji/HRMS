import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:hrms_mobile/core/api/api_error.dart';
import 'package:hrms_mobile/features/attendance/data/attendance_repository.dart';
import 'package:hrms_mobile/features/attendance/presentation/employee_insights.dart';

import 'support/fake_auth.dart';

// 12:00 on 18 Nov in Asia/Kolkata.
final _now = DateTime.utc(2026, 11, 18, 6, 30);

AttendanceDay _day(String date, String status, {Map<String, dynamic> extra = const {}, String? firstIn, String? lastOut, int? worked}) => AttendanceDay.fromJson({
      'id': 'd-$date',
      'employee_id': 'e-1',
      'attendance_date': date,
      'attendance_status': status,
      'actual_first_in': firstIn,
      'actual_last_out': lastOut,
      'worked_minutes': worked,
      'is_locked': false,
      ...extra,
    });

class _FakeAttendance implements AttendanceRepository {
  _FakeAttendance({this.error});
  final ApiError? error;
  final requested = <String>[];

  @override
  Future<List<AttendanceDay>> listAttendanceDays({String? employeeId, required String dateFrom, required String dateTo, String? attendanceStatus}) async {
    requested.add('$dateFrom..$dateTo');
    if (error != null) throw error!;
    if (dateFrom == dateTo) {
      return [_day(dateFrom, 'PRESENT', firstIn: '2026-11-18T03:45:00Z', extra: {'scheduled_start': '2026-11-18T03:30:00Z', 'scheduled_end': '2026-11-18T12:30:00Z'})];
    }
    if (dateFrom.startsWith('2026-10')) return [_day('2026-10-05', 'ABSENT')];
    return [
      _day('2026-11-02', 'PRESENT', firstIn: '2026-11-02T04:00:00Z', worked: 480, extra: {'scheduled_minutes': 480}),
      _day('2026-11-03', 'PRESENT', firstIn: '2026-11-03T04:40:00Z', worked: 420, extra: {'is_late': true, 'late_minutes': 40, 'scheduled_minutes': 480}),
      _day('2026-11-04', 'ABSENT'),
      _day('2026-11-05', 'LEAVE'),
    ];
  }

  @override
  Future<List<Punch>> listPunches({required String employeeId, required String dateFrom, required String dateTo}) async {
    if (error != null) throw error!;
    return [Punch(id: 'p1', employeeId: 'e-1', punchTime: '2026-11-18T03:45:00Z', direction: 'IN', source: 'WEB')];
  }

  @override
  dynamic noSuchMethod(Invocation invocation) => super.noSuchMethod(invocation);
}

Future<void> _pump(WidgetTester tester, _FakeAttendance repo) async {
  tester.view.physicalSize = const Size(800, 6000);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
  await tester.pumpWidget(ProviderScope(
    overrides: [attendanceRepositoryProvider.overrideWithValue(repo), fakeAuth(const [])],
    child: MaterialApp(home: Scaffold(body: SingleChildScrollView(child: EmployeeInsights(employeeId: 'e-1', shiftName: 'General', now: _now, live: false)))),
  ));
  await tester.pumpAndSettle();
}

void main() {
  testWidgets('Today shows who is in, since when, and the shift', (tester) async {
    await _pump(tester, _FakeAttendance());
    expect(find.text('Working'), findsOneWidget);
    expect(find.textContaining('In since'), findsOneWidget);
    expect(find.text('General\n9:00 am IST–6:00 pm IST'), findsOneWidget);
    expect(find.text('in 6h'), findsOneWidget);
  });

  testWidgets('month tiles, status ring and the hours chart come from the month days', (tester) async {
    await _pump(tester, _FakeAttendance());
    expect(find.text('November 2026'), findsOneWidget);
    Finder tile(String label, String value) => find.descendant(of: find.byKey(Key('insights-tile-$label')), matching: find.text(value));
    expect(tile('Days worked', '2'), findsOneWidget);
    expect(tile('Absent', '1'), findsOneWidget);
    expect(tile('Late arrivals', '1'), findsOneWidget);
    expect(tile('Punctuality', '50%'), findsOneWidget);
    expect(tile('Hours worked', '15h 0m'), findsOneWidget);
    expect(find.byKey(const Key('insights-breakdown')), findsOneWidget);
    expect(find.text('Days by status'), findsOneWidget);
    expect(find.text('2 of 4 working days attended'), findsOneWidget);
    expect(find.byKey(const Key('hours-bar-2026-11-02')), findsOneWidget);
    expect(find.byKey(const Key('hours-bar-2026-11-03')), findsOneWidget);
    expect(find.text('Shift 8h 0m'), findsOneWidget);
  });

  testWidgets('tapping a day opens its detail, and tapping again closes it', (tester) async {
    await _pump(tester, _FakeAttendance());
    expect(find.byKey(const Key('insights-day-detail')), findsNothing);
    await tester.tap(find.byKey(const Key('cal-2026-11-03')));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('insights-day-detail')), findsOneWidget);
    expect(find.text('Tuesday, 3 November'), findsOneWidget);
    expect(find.text('Open the full day'), findsOneWidget);
    await tester.tap(find.byKey(const Key('cal-2026-11-03')));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('insights-day-detail')), findsNothing);

    await tester.tap(find.byKey(const Key('cal-2026-11-10')));
    await tester.pumpAndSettle();
    expect(find.text('No attendance record for this day.'), findsOneWidget);
    await tester.tap(find.byKey(const Key('cal-2026-11-20')));
    await tester.pumpAndSettle();
    expect(find.text('This day has not happened yet.'), findsOneWidget);
  });

  testWidgets('the previous month loads that month, and there is no next month past this one', (tester) async {
    final repo = _FakeAttendance();
    await _pump(tester, repo);
    expect(tester.widget<IconButton>(find.widgetWithIcon(IconButton, Icons.chevron_right)).onPressed, isNull);
    await tester.tap(find.byTooltip('Previous month'));
    await tester.pumpAndSettle();
    expect(find.text('October 2026'), findsOneWidget);
    expect(repo.requested, contains('2026-10-01..2026-10-31'));
    expect(tester.widget<IconButton>(find.widgetWithIcon(IconButton, Icons.chevron_right)).onPressed, isNotNull);
  });

  testWidgets('a viewer without access sees nothing', (tester) async {
    await _pump(tester, _FakeAttendance(error: ApiError(status: 403, code: 'FORBIDDEN', message: 'no')));
    expect(find.byKey(const Key('employee-insights')), findsNothing);
    expect(find.byKey(const Key('insights-error')), findsNothing);
  });

  testWidgets('any other failure says the figures could not be loaded', (tester) async {
    await _pump(tester, _FakeAttendance(error: ApiError(status: 500, code: 'BOOM', message: 'boom')));
    expect(find.text('Attendance figures could not be loaded right now.'), findsOneWidget);
  });
}
