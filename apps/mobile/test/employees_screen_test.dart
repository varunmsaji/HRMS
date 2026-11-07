import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:hrms_mobile/core/api/api_client.dart';
import 'package:hrms_mobile/core/api/api_error.dart';
import 'package:hrms_mobile/core/api/envelope.dart';
import 'package:hrms_mobile/core/auth/permissions.dart';
import 'package:hrms_mobile/core/export/csv_export.dart';
import 'package:hrms_mobile/core/providers.dart';
import 'package:hrms_mobile/features/employees/presentation/employees_screen.dart';

import 'package:hrms_mobile/features/profile/data/employee_repository.dart';

import 'support/fake_api_client.dart';
import 'support/fake_auth.dart';

Map<String, dynamic> _employee(int n, String first, {String status = 'ACTIVE', bool active = true}) => {
      'id': 'e$n',
      'employee_code': 'E-$n',
      'first_name': first,
      'last_name': 'Test',
      'personal_email': '${first.toLowerCase()}@example.com',
      'status': status,
      'is_active': active,
      'version': 1,
    };

/// `GET /employees/directory/summary`, as the API's `DirectorySummary` serialises it.
const _summary = {
  'total': 42,
  'active': 40,
  'on_probation': 5,
  'on_notice': 2,
  'department_count': 3,
  'department_names': ['Sales', 'Ops', 'Finance'],
};

/// A server that filters by `q` and serves two pages: the first holds [firstPage] rows.
class _DirectoryApi extends FakeApiClient {
  _DirectoryApi(this.all);
  final List<Map<String, dynamic>> all;
  static const firstPage = 2;
  final searches = <String?>[];
  final pages = <int?>[];
  final rowRequests = <String>[];
  Object? summaryError;

  @override
  Future<T> get<T>(String path, {required T Function(dynamic) parse, bool authenticated = true}) async {
    if (path == '/employees/directory/summary') {
      if (summaryError != null) throw summaryError!;
      return parse(_summary);
    }
    if (path.startsWith('/employees/directory/rows?')) {
      rowRequests.add(path);
      final ids = Uri.parse(path).queryParametersAll['ids'] ?? const [];
      return parse([
        for (final id in ids)
          {'employee_id': id, 'designation': 'Engineer', 'department': id == 'e1' ? 'Sales, East' : 'Ops', 'branch': null, 'manager_name': 'Mo "Boss" Lee', 'shift_name': null},
      ]);
    }
    return super.get(path, parse: parse, authenticated: authenticated);
  }

  @override
  Future<ListEnvelope<T>> getList<T>(String path, {required T Function(dynamic) parseItem, PageQuery? query, Map<String, dynamic>? filters, bool authenticated = true}) async {
    final q = filters?['q'] as String?;
    searches.add(q);
    pages.add(query?.page);
    final matching = [for (final e in all) if (q == null || (e['first_name'] as String).toLowerCase().contains(q.toLowerCase())) e];
    final page = query?.page ?? 1;
    final rows = page == 1 ? matching.take(firstPage).toList() : matching.skip(firstPage).toList();
    final totalPages = matching.length > firstPage ? 2 : 1;
    return ListEnvelope(
      data: rows.map(parseItem).toList(),
      pagination: PaginationMeta(page: page, perPage: firstPage, total: matching.length, totalPages: totalPages),
      meta: ResponseMeta(requestId: 'r'),
    );
  }
}

Future<void> _pump(WidgetTester tester, FakeApiClient api, {CsvSharer? sharer}) async {
  tester.view.physicalSize = const Size(800, 2000);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
  await tester.pumpWidget(ProviderScope(
    overrides: [apiClientProvider.overrideWithValue(api), fakeAuth([employeeViewAll]), if (sharer != null) csvSharerProvider.overrideWithValue(sharer)],
    child: const MaterialApp(home: EmployeesScreen()),
  ));
  await tester.pumpAndSettle();
}

void main() {
  final people = [_employee(1, 'Asha'), _employee(2, 'Ben'), _employee(3, 'Bianca'), _employee(4, 'Cy')];

  testWidgets('while payroll is paused the record has no Salary tab, but keeps Compensation', (tester) async {
    tester.view.physicalSize = const Size(1600, 2000);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.reset);
    await tester.pumpWidget(ProviderScope(
      overrides: [apiClientProvider.overrideWithValue(FakeApiClient()), fakeAuth([employeeViewAll, employeeViewCompensation])],
      child: MaterialApp(home: EmployeeDetailScreen(employee: Employee.fromJson(_employee(1, 'Asha')))),
    ));
    await tester.pumpAndSettle();
    expect(find.text('Compensation'), findsOneWidget);
    expect(find.text('Salary'), findsNothing);
  });

  testWidgets('shows the first page and loads the next on demand', (tester) async {
    final api = _DirectoryApi(people);
    await _pump(tester, api);
    expect(find.text('Asha Test'), findsOneWidget);
    expect(find.text('Bianca Test'), findsNothing, reason: 'it is on page 2');
    await tester.tap(find.text('Load more'));
    await tester.pumpAndSettle();
    expect(find.text('Bianca Test'), findsOneWidget);
    expect(find.text('Cy Test'), findsOneWidget);
    expect(find.text('Load more'), findsNothing);
    expect(api.pages, [1, 2]);
  });

  testWidgets('search goes to the server, so someone on a later page is found', (tester) async {
    final api = _DirectoryApi(people);
    await _pump(tester, api);
    await tester.enterText(find.byType(TextField), 'bian');
    await tester.pump(const Duration(milliseconds: 100));
    expect(api.searches, [null], reason: 'typing is debounced, not sent on every key');
    await tester.pump(const Duration(milliseconds: 400));
    await tester.pumpAndSettle();
    expect(api.searches.last, 'bian');
    expect(find.text('Bianca Test'), findsOneWidget);
    expect(find.text('Asha Test'), findsNothing);
  });

  testWidgets('a search with no result says so', (tester) async {
    final api = _DirectoryApi(people);
    await _pump(tester, api);
    await tester.enterText(find.byType(TextField), 'zzz');
    await tester.pump(const Duration(milliseconds: 400));
    await tester.pumpAndSettle();
    expect(find.text('No matches'), findsOneWidget);
  });

  testWidgets('shows the directory summary cards from the API, as on web', (tester) async {
    await _pump(tester, _DirectoryApi(people));
    expect(find.text('TOTAL EMPLOYEES'), findsOneWidget);
    expect(find.text('42'), findsOneWidget);
    expect(find.text('40 active'), findsOneWidget);
    expect(find.text('ON PROBATION'), findsOneWidget);
    expect(find.text('5'), findsOneWidget);
    expect(find.text('ON NOTICE'), findsOneWidget);
    expect(find.text('Sales, Ops, Finance'), findsOneWidget);
  });

  testWidgets('a failed summary leaves the directory working, without cards', (tester) async {
    final api = _DirectoryApi(people)..summaryError = ApiError(status: 500, code: 'X', message: 'boom');
    await _pump(tester, api);
    expect(find.text('TOTAL EMPLOYEES'), findsNothing);
    expect(find.text('Asha Test'), findsOneWidget);
  });

  testWidgets('each row shows designation and department, fetched in one batch per page', (tester) async {
    final api = _DirectoryApi(people);
    await _pump(tester, api);
    expect(find.text('E-1 · Engineer · Sales, East'), findsOneWidget);
    expect(api.rowRequests, hasLength(1));
    expect(Uri.parse(api.rowRequests.single).queryParametersAll['ids'], ['e1', 'e2']);
  });

  testWidgets('status and record-state filters narrow the loaded rows, and Clear resets them', (tester) async {
    final api = _DirectoryApi([
      _employee(1, 'Asha'),
      _employee(2, 'Ben', status: 'PROBATION'),
    ]);
    await _pump(tester, api);
    await tester.tap(find.text('All statuses'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('PROBATION').last);
    await tester.pumpAndSettle();
    expect(find.text('Ben Test'), findsOneWidget);
    expect(find.text('Asha Test'), findsNothing);

    await tester.tap(find.text('All states'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Inactive only').last);
    await tester.pumpAndSettle();
    expect(find.text('No employees match these filters.'), findsOneWidget);

    await tester.tap(find.text('Clear'));
    await tester.pumpAndSettle();
    expect(find.text('Asha Test'), findsOneWidget);
    expect(find.text('Ben Test'), findsOneWidget);
  });

  testWidgets('filtering with more pages on the server says it covers only the loaded rows', (tester) async {
    await _pump(tester, _DirectoryApi(people));
    await tester.tap(find.text('All states'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Active only').last);
    await tester.pumpAndSettle();
    expect(find.text('Filters apply to the 2 employees loaded so far.'), findsOneWidget);
  });

  testWidgets('Export CSV shares the rows on screen with web columns', (tester) async {
    final shared = <(String, String)>[];
    final api = _DirectoryApi([
      _employee(1, 'Asha'),
      _employee(2, 'Ben', status: 'PROBATION'),
    ]);
    await _pump(tester, api, sharer: (name, csv) async => shared.add((name, csv)));
    await tester.tap(find.text('All statuses'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('ACTIVE').last);
    await tester.pumpAndSettle();

    await tester.tap(find.byTooltip('Export CSV'));
    await tester.pumpAndSettle();
    expect(shared, hasLength(1));
    expect(shared.single.$1, 'employees.csv');
    expect(shared.single.$2.split('\n'), [
      'Employee code,Name,Email,Mobile,Status,Designation,Department,Reporting manager,Shift',
      'E-1,Asha Test,asha@example.com,,ACTIVE,Engineer,"Sales, East","Mo ""Boss"" Lee",',
    ]);
  });

  testWidgets('a failed share says so instead of failing silently', (tester) async {
    await _pump(tester, _DirectoryApi(people), sharer: (_, __) async => throw Exception('no share sheet'));
    await tester.tap(find.byTooltip('Export CSV'));
    await tester.pumpAndSettle();
    expect(find.text('Could not export the list. Try again.'), findsOneWidget);
  });
}
