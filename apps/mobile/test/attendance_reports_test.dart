import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:hrms_mobile/core/api/api_error.dart';
import 'package:hrms_mobile/core/providers.dart';
import 'package:hrms_mobile/features/attendance/data/attendance_repository.dart';
import 'package:hrms_mobile/features/attendance/domain/attendance_reports.dart';
import 'package:hrms_mobile/features/attendance/presentation/attendance_reports_screen.dart';

import 'support/fake_api_client.dart';

AttendanceDay day(String emp, String date, String status, {String? firstIn, int worked = 0, Map<String, dynamic> extra = const {}}) => AttendanceDay(
      id: '$emp-$date',
      employeeId: emp,
      attendanceDate: date,
      attendanceStatus: status,
      actualFirstIn: firstIn,
      workedMinutes: worked,
      isLocked: false,
      raw: extra,
    );

String _name(String id) => const {'a': 'Asha', 'b': 'Ben', 'c': 'Cy'}[id] ?? id;

ReportDef _report(List<ReportDef> all, String key) => all.firstWhere((r) => r.key == key);

/// The report chips scroll sideways; bring one into view before tapping it.
Future<void> openReport(WidgetTester tester, String label) async {
  final chip = find.widgetWithText(ChoiceChip, label);
  await tester.ensureVisible(chip);
  await tester.pumpAndSettle();
  await tester.tap(chip);
  await tester.pumpAndSettle();
}

void main() {
  final days = [
    day('a', '2026-11-03', 'PRESENT', firstIn: 't', worked: 480, extra: {'scheduled_minutes': 480, 'is_late': true, 'late_minutes': 10}),
    day('a', '2026-11-04', 'WFH', firstIn: 't', worked: 420, extra: {'scheduled_minutes': 480}),
    day('b', '2026-11-03', 'ABSENT'),
    day('b', '2026-11-04', 'HALF_DAY', firstIn: 't', worked: 240, extra: {'is_early_out': true, 'early_departure_minutes': 30}),
    day('c', '2026-11-04', 'LEAVE'),
  ];
  final all = buildReports(days: days, overtime: const [], name: _name, zone: 'Asia/Kolkata');

  group('report rules (web reports-panel.tsx)', () {
    test('the five day-based reports come in web order', () {
      expect([for (final r in all) r.label], ['Daily attendance', 'Present / absent', 'Late / early', 'Work hours', 'Overtime']);
    });

    test('present / absent tallies per employee; remote counts as present', () {
      final t = {for (final e in tallyByEmployee(days)) e.id: e};
      expect((t['a']!.present, t['a']!.absent), (2, 0));
      expect((t['b']!.absent, t['b']!.half), (1, 1));
      expect(t['c']!.leave, 1);
    });

    test('work hours only lists people with checked-in days, with their average', () {
      final hours = _report(all, 'hours');
      expect([for (final r in hours.rows) (r as EmployeeTally).id], ['a', 'b']);
      final avg = hours.columns.firstWhere((c) => c.key == 'avg');
      expect(avg.render(hours.rows.first), '7h 30m');
    });

    test('late / early keeps only late or early days and shows a dash for the other side', () {
      final r = _report(all, 'late_early');
      expect(r.rows, hasLength(2));
      final late = r.columns.firstWhere((c) => c.key == 'late');
      final early = r.columns.firstWhere((c) => c.key == 'early');
      final ben = r.rows.firstWhere((d) => (d as AttendanceDay).employeeId == 'b');
      expect((late.render(ben), early.render(ben)), ('—', '30'));
    });

    test('daily uses web status labels and is searchable by name or status', () {
      final r = _report(all, 'daily');
      expect(r.columns[2].render(days[1]), 'Remote (WFH)');
      expect(reportView(r, query: 'on leave').total, 1);
      expect(reportView(r, query: 'BEN').total, 2);
    });

    test('sort by any column either way, and pages of 15', () {
      final many = buildReports(days: [for (var i = 1; i <= 20; i++) day('e$i', '2026-11-${i.toString().padLeft(2, '0')}', 'PRESENT', firstIn: 't', worked: i)], overtime: const [], name: (id) => id, zone: 'Asia/Kolkata');
      final daily = _report(many, 'daily');
      final first = reportView(daily, sortKey: 'worked', ascending: false);
      expect((first.total, first.pages, first.rows.length), (20, 2, 15));
      expect((first.rows.first as AttendanceDay).workedMinutes, 20);
      final second = reportView(daily, sortKey: 'worked', ascending: false, page: 9);
      expect((second.page, second.rows.length), (2, 5), reason: 'a page past the end is clamped');
    });

    test('payroll attendance shows the backend figures and sums the four overtime kinds', () {
      final r = payrollReport([
        {'employee_id': 'a', 'payable_days': '21.5', 'paid_days': null, 'present_days': '20', 'ot_minutes_normal': 60, 'ot_minutes_night': 30},
        {'employee_id': 'b', 'payable_days': null, 'present_days': '18', 'ot_minutes_holiday': 15},
      ], _name);
      String cell(String key, int i) => r.columns.firstWhere((c) => c.key == key).render(r.rows[i]);
      expect((cell('payable', 0), cell('paid', 0), cell('ot', 0)), ('21.5', '—', '1h 30m'));
      final asc = reportView(r, sortKey: 'payable');
      expect(_name('${(asc.rows.first as Map)['employee_id']}'), 'Ben', reason: 'unknown sorts first');
    });
  });

  Future<FakeApiClient> pump(WidgetTester tester, {FakeApiClient? api, List<Map<String, dynamic>>? periods, String? overtimeError}) async {
    tester.view.physicalSize = const Size(800, 3000);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.reset);
    final client = api ?? FakeApiClient();
    await tester.pumpWidget(ProviderScope(
      overrides: [apiClientProvider.overrideWithValue(client)],
      child: MaterialApp(
        home: AttendanceReportsScreen(
          days: days,
          overtime: const [
            {'id': 'o1', 'employee_id': 'a', 'attendance_date': '2026-11-03', 'day_class': 'HOLIDAY', 'minutes_detected': 90, 'minutes_approved': 60, 'status': 'APPROVED'},
          ],
          overtimeError: overtimeError,
          periods: periods ?? const [],
          name: _name,
          zone: 'Asia/Kolkata',
          today: '2026-11-04',
          rangeLabel: '03 Nov – 04 Nov',
        ),
      ),
    ));
    await tester.pumpAndSettle();
    return client;
  }

  testWidgets('opens on Daily attendance, searches, and switches report', (tester) async {
    await pump(tester);
    expect(find.text('03 Nov – 04 Nov. Read-only views of existing attendance data.'), findsOneWidget);
    expect(find.text('5 rows'), findsOneWidget);
    await tester.enterText(find.byType(TextField), 'asha');
    await tester.pumpAndSettle();
    expect(find.text('2 rows'), findsOneWidget);

    await openReport(tester, 'Overtime');
    expect(find.text('03 Nov · Asha'), findsOneWidget);
    expect(find.textContaining('Day class Holiday', findRichText: true), findsOneWidget);
    expect(find.textContaining('Status Approved', findRichText: true), findsOneWidget);
  });

  testWidgets('a failed overtime load shows its message on the Overtime report only', (tester) async {
    await pump(tester, overtimeError: "You don't have permission to view this.");
    expect(find.text("You don't have permission to view this."), findsNothing);
    await openReport(tester, 'Overtime');
    expect(find.text("You don't have permission to view this."), findsOneWidget);
  });

  testWidgets('payroll attendance loads the default period summary once', (tester) async {
    final api = FakeApiClient(lists: {
      '/attendance-periods/p1/summary': [
        {'employee_id': 'a', 'payable_days': '20', 'present_days': '19', 'absent_days': '1', 'leave_days': '0', 'lop_days': '0'},
      ],
    });
    await pump(tester, api: api, periods: const [
      {'id': 'p1', 'status': 'OPEN', 'period_start': '2026-11-01', 'period_end': '2026-11-30'},
    ]);
    expect(api.listCalls.where((c) => c.path.endsWith('/summary')), isEmpty, reason: 'not fetched until opened');
    await openReport(tester, 'Payroll attendance');
    expect(find.text('01 Nov – 30 Nov'), findsOneWidget);
    expect(find.text('Asha'), findsOneWidget);
    expect(find.text('1 row'), findsOneWidget);
    await openReport(tester, 'Daily attendance');
    await openReport(tester, 'Payroll attendance');
    expect(api.listCalls.where((c) => c.path.endsWith('/summary')), hasLength(1));
  });

  testWidgets('payroll attendance says when there is no period, or no permission', (tester) async {
    await pump(tester);
    await openReport(tester, 'Payroll attendance');
    expect(find.text('No attendance period to report on yet.'), findsOneWidget);
  });

  testWidgets('a forbidden period summary says so, with no retry', (tester) async {
    final api = FakeApiClient(failing: {'/attendance-periods/p1/summary': ApiError(status: 403, code: 'FORBIDDEN', message: 'no')});
    await pump(tester, api: api, periods: const [
      {'id': 'p1', 'status': 'OPEN', 'period_start': '2026-11-01', 'period_end': '2026-11-30'},
    ]);
    await openReport(tester, 'Payroll attendance');
    expect(find.text('You do not have permission to view the period summary.'), findsOneWidget);
    expect(find.text('Try again'), findsNothing);
  });
}
