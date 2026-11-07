import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:hrms_mobile/core/api/api_error.dart';
import 'package:hrms_mobile/core/api/envelope.dart';
import 'package:hrms_mobile/core/providers.dart';
import 'package:hrms_mobile/core/time.dart';
import 'package:hrms_mobile/core/widgets/ui.dart';
import 'package:hrms_mobile/features/attendance/domain/policy_coverage.dart';
import 'package:hrms_mobile/features/attendance/presentation/set_policies_panel.dart';

import 'support/fake_api_client.dart';
import 'support/fake_auth.dart';

const _coveragePath = '/policy-assignments/coverage';

Map<String, dynamic> _row(String kind, {String? leaveType, String? leaveName, Map<String, dynamic>? own, Map<String, dynamic>? applied}) =>
    {'policy_kind': kind, 'leave_type_id': leaveType, 'leave_type_name': leaveName, 'own': own, 'applied': applied};

Map<String, dynamic> _applied(String id, String name, {String scope = 'COMPANY', String? scopeName, String from = '2026-01-01', String? to, bool rules = true}) =>
    {'policy_id': id, 'policy_name': name, 'scope_type': scope, 'scope_id': null, 'scope_name': scopeName, 'effective_from': from, 'effective_to': to, 'has_rules': rules};

Map<String, dynamic> _own(String id, String name, {String from = '2026-01-01', int version = 3, String assignment = 'as1'}) =>
    {'assignment_id': assignment, 'policy_id': id, 'policy_name': name, 'effective_from': from, 'version': version};

/// The company's coverage: attendance set here, overtime not set, casual leave set here, calendar set here.
final _companyCoverage = {
  'scope_type': 'COMPANY',
  'scope_id': null,
  'as_of': '2026-11-07',
  'rows': [
    _row('WORK_CALENDAR', own: _own('wc1', 'Main calendar', assignment: 'as0'), applied: _applied('wc1', 'Main calendar')),
    _row('ATTENDANCE_POLICY', own: _own('ap1', 'Standard'), applied: _applied('ap1', 'Standard')),
    _row('OVERTIME_POLICY'),
    _row('LEAVE_POLICY', leaveType: 'lt1', leaveName: 'Casual', own: _own('lp1', 'Casual A', version: 5, assignment: 'as2'), applied: _applied('lp1', 'Casual A')),
  ],
};

Map<String, List<Map<String, dynamic>>> _lists() => {
      '/work-calendars': [
        {'id': 'wc1', 'name': 'Main calendar'},
        {'id': 'wc2', 'name': 'Plant calendar'},
      ],
      '/weekly-off-patterns': const [],
      '/attendance-policies': [
        {'id': 'ap1', 'name': 'Standard'},
        {'id': 'ap2', 'name': 'Strict'},
        {'id': 'ap3', 'name': 'Retired', 'is_active': false},
      ],
      '/overtime-policies': [
        {'id': 'op1', 'name': 'OT 2x'},
      ],
      '/regularization-policies': const [],
      '/leave-policies': [
        {'id': 'lp1', 'name': 'Casual A', 'leave_type_id': 'lt1'},
        {'id': 'lp2', 'name': 'Casual B', 'leave_type_id': 'lt1'},
        {'id': 'lp9', 'name': 'Sick A', 'leave_type_id': 'lt2'},
      ],
      '/branches': [
        {'id': 'b1', 'name': 'Pune HQ'},
      ],
    };

Future<void> _pump(WidgetTester tester, FakeApiClient api) async {
  tester.view.physicalSize = const Size(800, 3000);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
  await tester.pumpWidget(ProviderScope(
    overrides: [apiClientProvider.overrideWithValue(api), fakeAuth(const [])],
    child: const MaterialApp(home: Scaffold(body: SetPoliciesPanel())),
  ));
  await tester.pumpAndSettle();
}

/// Opens the "Change to" dropdown of the card titled [rowLabel] and picks [option].
Future<void> _pick(WidgetTester tester, String rowLabel, String option) async {
  final card = find.ancestor(of: find.text(rowLabel), matching: find.byType(AppCard)).first;
  await tester.tap(find.descendant(of: card, matching: find.byType(DropdownButtonFormField<String>)));
  await tester.pumpAndSettle();
  await tester.tap(find.text(option).last);
  await tester.pumpAndSettle();
}

void main() {
  group('coverage rules (web set-policies-panel / policy-assignment types)', () {
    final rows = coverageRows(_companyCoverage);
    final leave = rows.last;

    test('row keys and labels match web', () {
      expect([for (final r in rows) r.key], ['WORK_CALENDAR', 'ATTENDANCE_POLICY', 'OVERTIME_POLICY', 'LEAVE_POLICY:lt1']);
      expect(leave.label, 'Leave Policy — Casual');
      expect(rows[1].label, 'Attendance Policy');
    });

    test('a leave row offers only its leave type, and keeps a retired current policy first', () {
      final options = activeOptions(_lists()['/leave-policies']!);
      expect([for (final o in rowOptions(leave, options)) o.id], ['lp1', 'lp2']);
      final gone = CoverageRow(_row('ATTENDANCE_POLICY', own: _own('ap3', 'Retired')));
      expect([for (final o in rowOptions(gone, activeOptions(_lists()['/attendance-policies']!))) o.name], ['Retired', 'Standard', 'Strict']);
    });

    test('only picks that differ from what is set here are changes', () {
      final options = {'ATTENDANCE_POLICY': activeOptions(_lists()['/attendance-policies']!)};
      final changes = pendingChanges(rows, {'ATTENDANCE_POLICY': 'ap1', 'OVERTIME_POLICY': '', 'LEAVE_POLICY:lt1': 'lp2'}, options);
      expect([for (final c in changes) '${c.row.key}=${c.policyId}'], ['LEAVE_POLICY:lt1=lp2']);
      expect(changes.single.policyName, 'Selected policy', reason: 'leave options were not given');
    });

    test('a change must start after the current assignment here did', () {
      final change = CoverageChange(rows[1], 'ap2', 'Strict');
      expect(effectiveFromError('', [change]), 'Effective from is required.');
      expect(effectiveFromError('2026-01-01', [change]), 'Attendance Policy must start after 1 Jan 2026, when its current assignment started.');
      expect(effectiveFromError('2026-01-02', [change]), isNull);
    });

    test('where today’s policy comes from, in web wording', () {
      expect(appliedNote(_applied('x', 'X'), 'COMPANY'), 'Set here since 1 Jan 2026');
      expect(appliedNote(_applied('x', 'X', to: '2026-12-31'), 'COMPANY'), 'Set here until 31 Dec 2026, then inherited');
      expect(appliedNote(_applied('x', 'X', scopeName: 'Acme Pvt'), 'BRANCH'), 'Inherited from Whole company: Acme Pvt');
    });

    test('return to inherited is offered for a group override, never company-wide or calendars', () {
      expect(canReturnToInherited(rows[1], 'BRANCH'), isTrue);
      expect(canReturnToInherited(rows[1], 'COMPANY'), isFalse);
      expect(canReturnToInherited(rows[0], 'BRANCH'), isFalse);
      expect(canReturnToInherited(rows[2], 'BRANCH'), isFalse, reason: 'nothing set here');
    });

    test('batch and impact bodies match web', () {
      final c = CoverageChange(leave, 'lp2', 'Casual B');
      expect(batchBody(scopeType: 'BRANCH', scopeId: 'b1', effectiveFrom: '2026-12-01', reason: '  ', changes: [c]), {
        'scope_type': 'BRANCH',
        'scope_id': 'b1',
        'effective_from': '2026-12-01',
        'reason': null,
        'changes': [
          {'policy_kind': 'LEAVE_POLICY', 'policy_id': 'lp2', 'leave_type_id': 'lt1', 'expected_version': 5},
        ],
      });
      final cal = impactChange(change: CoverageChange(rows[0], 'wc2', 'Plant'), scopeType: 'COMPANY', scopeId: null, effectiveFrom: '2026-12-01', reason: 'Plant move');
      expect(cal['change_type'], 'ASSIGNMENT_CREATE');
      expect(cal['expected_version'], 3);
      expect((cal['body'] as Map)['policy_id'], 'wc2');
      expect(failedChange([c], {'policy_kind': 'LEAVE_POLICY', 'leave_type_id': 'lt1'}), same(c));
    });
  });

  testWidgets('shows what applies for the company and saves two changes in one batch', (tester) async {
    final api = FakeApiClient(objects: {_coveragePath: _companyCoverage}, lists: _lists());
    await _pump(tester, api);
    expect(find.text('Attendance Policy'), findsOneWidget);
    expect(find.text('Set here since 1 Jan 2026'), findsWidgets);
    expect(find.text('Not set'), findsWidgets, reason: 'overtime has nothing set');
    expect(find.text('No changes'), findsOneWidget);

    await _pick(tester, 'Attendance Policy', 'Strict');
    await _pick(tester, 'Leave Policy — Casual', 'Casual B');
    expect(find.text('Review 2 changes'), findsOneWidget);
    // The default date is today; the current assignments started on 1 Jan, so that is fine.
    await tester.tap(find.text('Review 2 changes'));
    await tester.pumpAndSettle();
    expect(find.text('Review changes'), findsOneWidget);
    expect(find.text('Standard → Strict'), findsOneWidget);
    expect(find.text('Casual A → Casual B'), findsOneWidget);

    await tester.tap(find.text('Confirm'));
    await tester.pumpAndSettle();
    final call = api.calls.single;
    expect((call.method, call.path), ('POST', '/policy-assignments/batch'));
    final body = call.body as Map<String, dynamic>;
    expect(body['scope_type'], 'COMPANY');
    expect(body['effective_from'], businessToday('Asia/Kolkata'));
    expect(body['changes'], [
      {'policy_kind': 'ATTENDANCE_POLICY', 'policy_id': 'ap2', 'leave_type_id': null, 'expected_version': 3},
      {'policy_kind': 'LEAVE_POLICY', 'policy_id': 'lp2', 'leave_type_id': 'lt1', 'expected_version': 5},
    ]);
    expect(find.text('2 assignments saved'), findsOneWidget);
    expect(find.text('No changes'), findsOneWidget);
  });

  testWidgets('a refused batch saves nothing, names the failing row and keeps the sheet open', (tester) async {
    final api = FakeApiClient(
      objects: {_coveragePath: _companyCoverage},
      lists: _lists(),
      failing: {
        '/policy-assignments/batch': ApiError(status: 409, code: 'STALE_RESOURCE', message: 'Changed by someone else.', details: [
          ErrorDetail(code: 'STALE_RESOURCE', message: 'x', context: {'policy_kind': 'LEAVE_POLICY', 'leave_type_id': 'lt1'}),
        ]),
      },
    );
    await _pump(tester, api);
    await _pick(tester, 'Leave Policy — Casual', 'Casual B');
    await tester.tap(find.text('Review 1 change'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Confirm'));
    await tester.pumpAndSettle();
    expect(find.text('Nothing was saved. Leave Policy — Casual: Changed by someone else.'), findsOneWidget);
    expect(find.text('Review changes'), findsOneWidget);
  });

  testWidgets('a work calendar change skips the batch and opens the impact preview', (tester) async {
    final api = FakeApiClient(objects: {_coveragePath: _companyCoverage}, lists: _lists());
    await _pump(tester, api);
    await _pick(tester, 'Work Calendar', 'Plant calendar');
    await tester.tap(find.text('Review 1 change'));
    await tester.pumpAndSettle();
    expect(find.textContaining('open an impact preview next'), findsOneWidget);
    await tester.tap(find.text('Confirm'));
    await tester.pumpAndSettle();
    expect(api.calls.where((c) => c.path == '/policy-assignments/batch'), isEmpty);
    expect(find.text('Change Work Calendar: review impact'), findsOneWidget);
    final preview = api.calls.singleWhere((c) => c.path == '/work-calendar-changes/preview');
    final change = (preview.body as Map)['change'] as Map;
    expect((change['change_type'], change['expected_version'], (change['body'] as Map)['policy_id']), ('ASSIGNMENT_CREATE', 3, 'wc2'));
  });

  testWidgets('an effective date on or before the current start is refused before review', (tester) async {
    final today = businessToday('Asia/Kolkata');
    final coverage = {
      ..._companyCoverage,
      'rows': [_row('ATTENDANCE_POLICY', own: _own('ap1', 'Standard', from: today), applied: _applied('ap1', 'Standard', from: today))],
    };
    await _pump(tester, FakeApiClient(objects: {_coveragePath: coverage}, lists: _lists()));
    await _pick(tester, 'Attendance Policy', 'Strict');
    await tester.tap(find.text('Review 1 change'));
    await tester.pumpAndSettle();
    expect(find.textContaining('must start after'), findsOneWidget);
    expect(find.text('Review changes'), findsNothing);
  });

  testWidgets('choosing a branch asks for its coverage; a branch override can return to inherited', (tester) async {
    final branch = {
      'scope_type': 'BRANCH',
      'scope_id': 'b1',
      'as_of': '2026-11-07',
      'rows': [
        _row('ATTENDANCE_POLICY', own: _own('ap2', 'Strict'), applied: _applied('ap2', 'Strict', scope: 'BRANCH')),
        _row('OVERTIME_POLICY', applied: _applied('op1', 'OT 2x', scopeName: 'Acme')),
      ],
    };
    final api = _ScopedCoverage({'COMPANY': _companyCoverage, 'BRANCH': branch}, _lists());
    await _pump(tester, api);
    await tester.tap(find.text('Whole company'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Branch').last);
    await tester.pumpAndSettle();
    expect(find.text('Choose who to see what they follow.'), findsOneWidget);
    await tester.tap(find.text('Choose…'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Pune HQ').last);
    await tester.pumpAndSettle();
    expect(api.asked.last, contains('scope_id=b1'));
    expect(find.text('Inherited from Whole company: Acme'), findsOneWidget);
    expect(find.text('Keep inherited'), findsOneWidget);
    expect(find.text('Return to inherited'), findsOneWidget, reason: 'only the attendance override');
  });

  testWidgets('without permission it says so', (tester) async {
    await _pump(tester, FakeApiClient(failing: {_coveragePath: ApiError(status: 403, code: 'PERMISSION_DENIED', message: 'no')}, lists: _lists()));
    expect(find.text('You do not have permission to manage policy assignments.'), findsOneWidget);
  });
}

/// Answers coverage per `scope_type` and records each coverage URL asked for.
class _ScopedCoverage extends FakeApiClient {
  _ScopedCoverage(this.byScope, Map<String, List<Map<String, dynamic>>> lists) : super(lists: lists);
  final Map<String, Map<String, dynamic>> byScope;
  final asked = <String>[];

  @override
  Future<T> get<T>(String path, {required T Function(dynamic) parse, bool authenticated = true}) async {
    if (path.startsWith(_coveragePath)) {
      asked.add(path);
      return parse(byScope[Uri.parse(path).queryParameters['scope_type']]);
    }
    return super.get(path, parse: parse, authenticated: authenticated);
  }
}
