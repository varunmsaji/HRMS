import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:hrms_mobile/core/api/api_client.dart';
import 'package:hrms_mobile/core/export/file_share.dart';
import 'package:hrms_mobile/core/providers.dart';
import 'package:hrms_mobile/features/attendance/data/attendance_repository.dart';
import 'package:hrms_mobile/features/attendance/domain/attendance_export.dart';
import 'package:hrms_mobile/features/attendance/domain/attendance_totals.dart';
import 'package:hrms_mobile/features/attendance/domain/pattern_alerts.dart';
import 'package:hrms_mobile/features/attendance/presentation/attendance_insights_screen.dart';

import 'support/fake_api_client.dart';
import 'support/fake_auth.dart';
import 'support/totals_fixture.dart';

class _Repo implements AttendanceRepository {
  final requested = <String>[];

  @override
  Future<DownloadedFile> downloadExport(String path) async {
    requested.add(path);
    return DownloadedFile(bytes: [1, 2], filename: null);
  }

  @override
  Future<List<AttendanceDay>> listAttendanceDays({String? employeeId, required String dateFrom, required String dateTo, String? attendanceStatus}) async => const [];

  @override
  Future<AttendanceTotals> attendanceSummary({required String dateFrom, required String dateTo}) async => AttendanceTotals.fromJson(totalsJson(dateTo, dateFrom));

  @override
  Future<PatternAlerts> patternAlerts({String? asOf}) async => PatternAlerts.fromJson({
        'as_of': asOf ?? '2026-10-14',
        'thresholds': {'window_days': 30, 'weekday_window_days': 56, 'late_days': 5, 'absent_days': 4, 'incomplete_days': 3, 'weekday_absences': 3},
        'alerts': [],
      });

  @override
  dynamic noSuchMethod(Invocation invocation) => super.noSuchMethod(invocation);
}

void main() {
  group('export rules (web export.ts)', () {
    test('the period must be whole, ordered, not in the future and at most a year', () {
      expect(exportWindowError('', '2026-10-01', '2026-10-14'), 'Choose both dates.');
      expect(exportWindowError('2026-10-05', '2026-10-01', '2026-10-14'), contains('on or before'));
      expect(exportWindowError('2026-10-01', '2026-10-20', '2026-10-14'), contains('future'));
      expect(exportWindowError('2025-01-01', '2026-01-02', '2026-10-14'), contains('at most 366'));
      expect(exportWindowError('2025-10-14', '2026-10-14', '2026-10-14'), isNull); // 366 days, to the day
    });

    test('a PDF register covers at most 62 days', () {
      expect(pdfRegisterError('2026-08-14', '2026-10-14'), isNull); // 62 days
      expect(pdfRegisterError('2026-08-13', '2026-10-14'), contains('62'));
    });

    test('paths carry the period and format', () {
      expect(musterExportPath('2026-10-01', '2026-10-14', 'xlsx'), '/attendance/export/muster?date_from=2026-10-01&date_to=2026-10-14&format=xlsx');
      expect(reportExportPath(serverReports['late_early']!, '2026-10-01', '2026-10-14', 'csv'), '/attendance/reports/late-early/export?date_from=2026-10-01&date_to=2026-10-14&format=csv');
      expect(serverReports.containsKey('payroll'), isFalse);
    });
  });

  testWidgets('the register export asks the server for the chosen format and shares the file', (tester) async {
    tester.view.physicalSize = const Size(800, 6000);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.reset);
    final repo = _Repo();
    final shared = <String>[];
    final api = FakeApiClient(lists: {'/employees': const [], '/regularizations': const [], '/attendance-periods': const [], '/overtime': const []});
    await tester.pumpWidget(ProviderScope(
      overrides: [
        attendanceRepositoryProvider.overrideWithValue(repo),
        apiClientProvider.overrideWithValue(api),
        fileSharerProvider.overrideWithValue((name, bytes, mime) async => shared.add('$name $mime')),
        fakeAuth(const []),
      ],
      child: const MaterialApp(home: AttendanceInsightsScreen()),
    ));
    await tester.pumpAndSettle();
    // With no attendance days the heatmap has nothing to show, so the register export is on Reports.
    await tester.tap(find.widgetWithText(Tab, 'Reports'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Export period'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Export'));
    await tester.pumpAndSettle();
    expect(repo.requested.single, startsWith('/attendance/reports/daily/export?date_from='));
    expect(repo.requested.single, endsWith('&format=csv'));
    expect(shared.single, matches(RegExp(r'^daily_\d{4}-\d{2}-\d{2}_\d{4}-\d{2}-\d{2}\.csv text/csv$')));
  });
}
