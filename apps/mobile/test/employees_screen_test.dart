import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:hrms_mobile/core/api/api_client.dart';
import 'package:hrms_mobile/core/api/envelope.dart';
import 'package:hrms_mobile/core/auth/permissions.dart';
import 'package:hrms_mobile/core/providers.dart';
import 'package:hrms_mobile/features/employees/presentation/employees_screen.dart';

import 'support/fake_api_client.dart';
import 'support/fake_auth.dart';

Map<String, dynamic> _employee(int n, String first) => {
      'id': 'e$n',
      'employee_code': 'E-$n',
      'first_name': first,
      'last_name': 'Test',
      'status': 'ACTIVE',
      'is_active': true,
      'version': 1,
    };

/// A server that filters by `q` and serves two pages: the first holds [firstPage] rows.
class _DirectoryApi extends FakeApiClient {
  _DirectoryApi(this.all);
  final List<Map<String, dynamic>> all;
  static const firstPage = 2;
  final searches = <String?>[];
  final pages = <int?>[];

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

Future<void> _pump(WidgetTester tester, FakeApiClient api) async {
  tester.view.physicalSize = const Size(800, 2000);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
  await tester.pumpWidget(ProviderScope(
    overrides: [apiClientProvider.overrideWithValue(api), fakeAuth([employeeViewAll])],
    child: const MaterialApp(home: EmployeesScreen()),
  ));
  await tester.pumpAndSettle();
}

void main() {
  final people = [_employee(1, 'Asha'), _employee(2, 'Ben'), _employee(3, 'Bianca'), _employee(4, 'Cy')];

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
}
