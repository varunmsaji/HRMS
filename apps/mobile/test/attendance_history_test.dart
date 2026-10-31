import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:hrms_mobile/core/api/api_client.dart';
import 'package:hrms_mobile/core/api/api_error.dart';
import 'package:hrms_mobile/core/api/envelope.dart';
import 'package:hrms_mobile/core/auth/permissions.dart';
import 'package:hrms_mobile/core/theme/app_theme.dart';
import 'package:hrms_mobile/core/time.dart';
import 'package:hrms_mobile/core/widgets/employee/attendance_history.dart';
import 'package:hrms_mobile/features/attendance/data/attendance_repository.dart';
import 'package:hrms_mobile/features/attendance/presentation/attendance_month_card.dart';
import 'package:hrms_mobile/features/attendance/presentation/attendance_self_screen.dart';

import 'support/fake_api_client.dart';
import 'support/fake_auth.dart';
import 'support/test_themes.dart';

const _zone = 'Asia/Kolkata';
final _today = businessToday(_zone);

Map<String, dynamic> _row(String id, String date, String status, {String? firstIn, String? lastOut, int worked = 0}) => {
      'id': id,
      'employee_id': 'e-1',
      'attendance_date': date,
      'attendance_status': status,
      'timezone': _zone,
      'actual_first_in': firstIn,
      'actual_last_out': lastOut,
      'worked_minutes': worked,
      'is_locked': false,
    };

/// Serves `items` in pages of the requested `per_page`, with real pagination metadata.
class _PagedClient extends FakeApiClient {
  _PagedClient(this.items, {this.pageSizeCap});
  final List<Map<String, dynamic>> items;
  final int? pageSizeCap;
  final requests = <({String path, int page, int? perPage})>[];

  @override
  Future<ListEnvelope<T>> getList<T>(String path, {required T Function(dynamic) parseItem, PageQuery? query, Map<String, dynamic>? filters, bool authenticated = true}) async {
    final page = query?.page ?? 1;
    final per = pageSizeCap ?? query?.perPage ?? 500;
    requests.add((path: path, page: page, perPage: query?.perPage));
    final slice = items.skip((page - 1) * per).take(per).toList();
    final pages = (items.length / per).ceil().clamp(1, 1 << 30);
    return ListEnvelope(
      data: slice.map(parseItem).toList(),
      pagination: PaginationMeta(page: page, perPage: per, total: items.length, totalPages: pages),
      meta: ResponseMeta(requestId: 'r'),
    );
  }
}

class _Repo implements AttendanceRepository {
  _Repo(this.days, {this.fail});
  final List<Map<String, dynamic>> days;
  final Object? fail;

  @override
  Future<FaceEnrollmentStatus> getMyFaceEnrollment() async => FaceEnrollmentStatus();

  @override
  Future<List<AttendanceDay>> listAttendanceDays({String? employeeId, required String dateFrom, required String dateTo, String? attendanceStatus}) async {
    if (fail != null) throw fail!;
    return days.map(AttendanceDay.fromJson).toList();
  }

  @override
  Future<List<Punch>> listPunches({required String employeeId, required String dateFrom, required String dateTo}) async => [];

  @override
  @override
  dynamic noSuchMethod(Invocation invocation) => super.noSuchMethod(invocation);
}

Future<void> _pumpScreen(WidgetTester tester, _Repo repo, {Size size = const Size(390, 844), double scale = 1.0}) async {
  tester.view.physicalSize = size;
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
  await tester.pumpWidget(ProviderScope(
    overrides: [fakeAuth(const [attendancePunch, attendanceView], employeeId: 'e-1'), attendanceRepositoryProvider.overrideWithValue(repo)],
    child: MaterialApp(
      theme: AppTheme.employee,
      builder: (context, child) => MediaQuery(data: MediaQuery.of(context).copyWith(textScaler: TextScaler.linear(scale)), child: child!),
      home: const AttendanceSelfScreen(),
    ),
  ));
  await tester.pumpAndSettle();
}

/// Brings the history (below the month card) into the built part of the lazy list.
Future<void> _toHistory(WidgetTester tester) async {
  await tester.drag(find.byType(ListView).first, const Offset(0, -700));
  await tester.pumpAndSettle();
}

void main() {
  setUpAll(primeThemes);

  group('history is never silently truncated by the API page size', () {
    test('days: follows every page (250 rows at 100 per page)', () async {
      final rows = [for (var i = 0; i < 250; i++) _row('d$i', '2026-01-01', 'PRESENT')];
      final client = _PagedClient(rows);
      final days = await AttendanceRepository(client).listAttendanceDays(employeeId: 'e-1', dateFrom: '2026-01-01', dateTo: '2026-12-31');
      expect(days, hasLength(250));
      expect(client.requests.map((r) => r.page), [1, 2, 3]);
      expect(client.requests.every((r) => r.perPage == 100), isTrue);
    });

    test('days: still complete when the server caps pages below what was asked', () async {
      final rows = [for (var i = 0; i < 130; i++) _row('d$i', '2026-01-01', 'PRESENT')];
      final days = await AttendanceRepository(_PagedClient(rows, pageSizeCap: 50)).listAttendanceDays(employeeId: 'e-1', dateFrom: 'a', dateTo: 'b');
      expect(days, hasLength(130));
    });

    test('punches: follows pages too (the server default is 500 a page, newest first)', () async {
      final rows = [for (var i = 0; i < 1200; i++) {'id': 'p$i', 'employee_id': 'e-1', 'punch_time': '2026-10-30T04:00:00Z', 'direction': 'IN', 'source': 'MOBILE'}];
      final client = _PagedClient(rows);
      final punches = await AttendanceRepository(client).listPunches(employeeId: 'e-1', dateFrom: 'a', dateTo: 'b');
      expect(punches, hasLength(1200));
      expect(client.requests.map((r) => r.page), [1, 2, 3]);
    });

    test('a single page response (no pagination block) is returned whole', () async {
      final client = FakeApiClient(lists: {'/attendance/days': [_row('d1', '2026-01-01', 'PRESENT')]});
      expect(await AttendanceRepository(client).listAttendanceDays(employeeId: 'e-1', dateFrom: 'a', dateTo: 'b'), hasLength(1));
    });
  });

  group('Last 14 days as one grouped list', () {
    testWidgets('rows show a status word, the time range and worked time, newest first, in one group', (tester) async {
      final yesterday = businessDayOffset(_zone, -1);
      final older = businessDayOffset(_zone, -2);
      await _pumpScreen(tester, _Repo([
        _row('a', older, 'PRESENT', firstIn: '${older}T04:00:00Z', lastOut: '${older}T12:30:00Z', worked: 510),
        _row('b', yesterday, 'LEAVE'),
      ]));
      await _toHistory(tester);
      expect(find.text('Last 14 days'), findsOneWidget);
      expect(find.byType(AttendanceHistoryGroup), findsOneWidget);
      expect(find.text('Present'), findsWidgets);
      expect(find.text('9:30 am IST – 6:00 pm IST · 8h 30m'), findsOneWidget);
      expect(find.text('On leave'), findsWidgets);
      expect(find.text('No punches'), findsOneWidget);
      expect(tester.getTopLeft(find.text('On leave').first).dy, lessThan(tester.getTopLeft(find.text('9:30 am IST – 6:00 pm IST · 8h 30m')).dy), reason: 'newest first');
    });

    testWidgets('today\'s placeholder ABSENT row is never called Absent', (tester) async {
      await _pumpScreen(tester, _Repo([_row('t', _today, 'ABSENT')]));
      await _toHistory(tester);
      expect(find.text('Not punched in yet'), findsWidgets, reason: 'the list row and the month legend');
      expect(find.text('Absent'), findsNothing);
    });

    testWidgets('a past ABSENT day is Absent', (tester) async {
      final d = businessDayOffset(_zone, -3);
      await _pumpScreen(tester, _Repo([_row('x', d, 'ABSENT')]));
      await _toHistory(tester);
      expect(find.text('Absent'), findsWidgets);
    });

    testWidgets('an open day (punched in, not out) shows an open range', (tester) async {
      final d = businessDayOffset(_zone, -1);
      await _pumpScreen(tester, _Repo([_row('o', d, 'INCOMPLETE', firstIn: '${d}T04:00:00Z')]));
      await _toHistory(tester);
      expect(find.text('9:30 am IST – …'), findsOneWidget);
    });

    testWidgets('tapping a row opens the day', (tester) async {
      final d = businessDayOffset(_zone, -1);
      await _pumpScreen(tester, _Repo([_row('o', d, 'PRESENT', firstIn: '${d}T04:00:00Z', lastOut: '${d}T12:00:00Z', worked: 480)]));
      await _toHistory(tester);
      await tester.tap(find.textContaining('IST –'));
      await tester.pump();
      await tester.pump(const Duration(seconds: 1));
      expect(find.text('Attendance day'), findsOneWidget);
    });

    testWidgets('failure shows the message and Try again, and the punch bar stays', (tester) async {
      await _pumpScreen(tester, _Repo(const [], fail: ApiError(status: 500, code: 'X', message: 'Down for now.')));
      await _toHistory(tester);
      expect(find.text('Couldn\'t load attendance'), findsOneWidget);
      expect(find.text('Down for now.'), findsWidgets);
      expect(find.text('Punch in'), findsOneWidget);
    });

    testWidgets('empty history says so', (tester) async {
      await _pumpScreen(tester, _Repo(const []));
      await _toHistory(tester);
      expect(find.text('No attendance yet'), findsOneWidget);
    });

    for (final size in [const Size(320, 568), const Size(360, 800)]) {
      testWidgets('no overflow at ${size.width.toInt()} px and 2x text, scrolled to the end', (tester) async {
        final days = [
          for (var i = 1; i <= 14; i++)
            _row('r$i', businessDayOffset(_zone, -i), i.isEven ? 'PRESENT' : 'HALF_DAY', firstIn: '${businessDayOffset(_zone, -i)}T04:00:00Z', lastOut: '${businessDayOffset(_zone, -i)}T12:30:00Z', worked: 510),
        ];
        await _pumpScreen(tester, _Repo(days), size: size, scale: 2.0);
        await tester.drag(find.byType(ListView).first, const Offset(0, -3000));
      await _toHistory(tester);
        await tester.pumpAndSettle();
        expect(tester.takeException(), isNull);
        expect(find.text('Punch in'), findsOneWidget, reason: 'the bar stays pinned');
      });
    }
  });

  group('calendar touch targets', () {
    Future<void> pumpMonth(WidgetTester tester, double width, {double scale = 1.0}) async {
      tester.view.physicalSize = Size(width, 900);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.reset);
      final d = '${_today.substring(0, 8)}01';
      await tester.pumpWidget(ProviderScope(
        overrides: [fakeAuth(const [attendanceView], employeeId: 'e-1'), attendanceRepositoryProvider.overrideWithValue(_Repo([_row('m', d, 'PRESENT', firstIn: '${d}T04:00:00Z', lastOut: '${d}T12:00:00Z', worked: 480)]))],
        child: MaterialApp(
          theme: AppTheme.employee,
          builder: (context, child) => MediaQuery(data: MediaQuery.of(context).copyWith(textScaler: TextScaler.linear(scale)), child: child!),
          home: Scaffold(body: SingleChildScrollView(child: Padding(padding: const EdgeInsets.all(16), child: AttendanceMonthCard(employeeId: 'e-1', zone: _zone)))),
        ),
      ));
      await tester.pumpAndSettle();
    }

    Finder cell() => find.ancestor(of: find.text('1'), matching: find.byType(InkWell)).first;

    for (final w in [320.0, 360.0, 390.0]) {
      testWidgets('at ${w.toInt()} px the whole grid cell is the touch target: at least 48 high and as wide as the grid allows', (tester) async {
        await pumpMonth(tester, w);
        final size = tester.getSize(cell());
        expect(size.height, greaterThanOrEqualTo(48));
        expect(size.width, greaterThanOrEqualTo(w == 320 ? 38 : 40), reason: '320 px cannot give seven columns more than ~39 px without removing the card');
      });
    }

    testWidgets('a tap near the edge of the cell (outside the drawn tile) still opens the day', (tester) async {
      await pumpMonth(tester, 320);
      final rect = tester.getRect(cell());
      await tester.tapAt(rect.topLeft + const Offset(1, 1));
      await tester.pump();
      await tester.pump(const Duration(seconds: 1));
      expect(find.text('Attendance day'), findsOneWidget);
    });

    testWidgets('cells grow with text size so the touch target never shrinks below content', (tester) async {
      await pumpMonth(tester, 320, scale: 2.0);
      expect(tester.getSize(cell()).height, greaterThanOrEqualTo(96));
    });
  });
}
