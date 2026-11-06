import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:hrms_mobile/core/api/api_client.dart';
import 'package:hrms_mobile/core/api/envelope.dart';
import 'package:hrms_mobile/core/auth/permissions.dart';
import 'package:hrms_mobile/core/providers.dart';
import 'package:hrms_mobile/features/leave/presentation/leave_balances_screen.dart';

import 'support/fake_api_client.dart';
import 'support/fake_auth.dart';

Map<String, dynamic> _employee(int n) => {'id': 'e-$n', 'employee_code': 'E$n', 'first_name': 'Person', 'last_name': '$n', 'display_name': 'Person $n', 'status': 'ACTIVE', 'is_active': true, 'version': 1, 'company_id': 'c-1'};

/// Two pages of employees; `q` narrows them, as the server does.
class _PagedApi extends FakeApiClient {
  _PagedApi() : super(lists: const {'/leave-ledger': []});

  @override
  Future<ListEnvelope<T>> getList<T>(String path, {required T Function(dynamic) parseItem, PageQuery? query, Map<String, dynamic>? filters, bool authenticated = true}) async {
    if (path != '/employees') return super.getList(path, parseItem: parseItem, query: query, filters: filters);
    listCalls.add((path: path, filters: filters));
    final q = filters?['q'] as String?;
    if (q != null && q.isNotEmpty) return ListEnvelope(data: [parseItem(_employee(77))], pagination: null, meta: ResponseMeta(requestId: 'r'));
    final page = query?.page ?? 1;
    return ListEnvelope(
      data: [for (var i = (page - 1) * 2 + 1; i <= page * 2; i++) parseItem(_employee(i))],
      pagination: PaginationMeta.fromJson({'page': page, 'per_page': 2, 'total': 4, 'total_pages': 2, 'has_next': page < 2, 'has_prev': page > 1}),
      meta: ResponseMeta(requestId: 'r'),
    );
  }
}

Future<_PagedApi> _pump(WidgetTester tester, {List<String> permissions = const [leaveBalanceViewAll], String? employeeId}) async {
  tester.view.physicalSize = const Size(600, 1400);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
  final api = _PagedApi();
  await tester.pumpWidget(ProviderScope(
    overrides: [apiClientProvider.overrideWithValue(api), fakeAuth(permissions, employeeId: employeeId)],
    child: const MaterialApp(home: LeaveBalancesScreen()),
  ));
  await tester.pumpAndSettle();
  return api;
}

void main() {
  testWidgets('the company account is asked to choose instead of opening on the first employee', (tester) async {
    final api = await _pump(tester);
    expect(find.text('Choose an employee'), findsWidgets);
    expect(api.listCalls.map((c) => c.path), isNot(contains('/leave-ledger')));
    expect(api.listCalls.map((c) => c.path), isNot(contains('/employees')));
  });

  testWidgets('an employee with view-all opens on their own balances and can switch', (tester) async {
    final api = await _pump(tester, employeeId: 'me');
    expect(find.text('You'), findsOneWidget);
    expect(api.listCalls.map((c) => c.path), contains('/leave-ledger'));
  });

  testWidgets('without view-all there is no picker', (tester) async {
    await _pump(tester, permissions: const [leaveBalanceView], employeeId: 'me');
    expect(find.byIcon(Icons.person_search_outlined), findsNothing);
  });

  testWidgets('someone past the first page can be reached, and by search', (tester) async {
    final api = await _pump(tester);
    await tester.tap(find.text('Choose an employee').first);
    await tester.pumpAndSettle();
    expect(find.text('Person 3'), findsNothing);
    await tester.tap(find.text('Load more'));
    await tester.pumpAndSettle();
    expect(find.text('Person 3'), findsOneWidget);

    await tester.enterText(find.byType(TextField), 'zed');
    await tester.pump(const Duration(milliseconds: 350));
    await tester.pumpAndSettle();
    expect(api.listCalls.last.filters?['q'], 'zed');
    await tester.tap(find.text('Person 77'));
    await tester.pumpAndSettle();

    expect(find.text('Person 77'), findsOneWidget);
    expect(api.listCalls.map((c) => c.path), contains('/leave-ledger'));
  });
}
