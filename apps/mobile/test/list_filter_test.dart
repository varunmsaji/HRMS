import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:hrms_mobile/core/format.dart';
import 'package:hrms_mobile/core/status_words.dart';
import 'package:hrms_mobile/core/theme/app_theme.dart';
import 'package:hrms_mobile/core/widgets/choice_picker.dart';
import 'package:hrms_mobile/core/widgets/list_filter.dart';
import 'package:hrms_mobile/core/widgets/ui.dart';

import 'support/test_themes.dart';

Widget _harness(Widget child) => MaterialApp(theme: AppTheme.light, home: Scaffold(body: Center(child: child)));

const _status = FilterGroup(key: 'status', label: 'Status', options: [('SUBMITTED', 'Awaiting approval'), ('APPROVED', 'Approved')]);

void main() {
  setUpAll(primeThemes);

  group('status words', () {
    test('one word per status, whichever resource it comes from', () {
      expect(requestStatusLabel('SUBMITTED'), 'Awaiting approval');
      expect(requestStatusLabel('PENDING'), 'Awaiting approval', reason: 'overtime says PENDING for the same thing');
      expect(requestStatusLabel('AUTO_APPROVED'), 'Auto-approved');
      expect(requestStatusLabel('ON_HOLD'), 'On hold', reason: 'an unknown code is still readable');
    });

    test('a cancelled request is neutral, not an error', () {
      expect(toneForRequestStatus('CANCELLED'), Tone.neutral);
      expect(toneForRequestStatus('REJECTED'), Tone.danger);
      expect(toneForRequestStatus('PENDING'), Tone.warning);
    });
  });

  group('dates', () {
    final now = DateTime(2026, 11, 15);
    test('ranges carry the year only when it is not this year', () {
      expect(formatDateRange('2026-11-12', '2026-11-13', now: now), '12–13 Nov');
      expect(formatDateRange('2025-12-28', '2026-01-02', now: now), '28 Dec 2025 – 2 Jan 2026');
      expect(formatDateRange('2025-03-03', '2025-03-04', now: now), '3–4 Mar 2025');
      expect(formatDateRange('2025-03-30', '2025-04-02', now: now), '30 Mar – 2 Apr 2025');
    });

    test('effective periods', () {
      expect(formatPeriod('2026-04-01', '2027-03-31'), '1 Apr 2026 – 31 Mar 2027');
      expect(formatPeriod('2026-04-01', null), 'From 1 Apr 2026');
      expect(formatPeriod('2026-04-01', null, openEnd: 'present'), '1 Apr 2026 – present');
      expect(formatDayCount(1), '1 day');
      expect(formatDayCount(2), '2 days');
      expect(formatDayCount(0.5), '0.5 day');
    });
  });

  group('filter', () {
    test('the count is what differs from the list\'s defaults', () {
      const defaults = ListFilter(from: '2026-10-16', to: '2026-11-15');
      expect(defaults.countAgainst(defaults), 0);
      expect(defaults.withGroup('status', 'APPROVED').countAgainst(defaults), 1);
      expect(defaults.copyWith(clearDates: true, employee: 'e-1').countAgainst(defaults), 2);
      expect(defaults.withGroup('status', ''), defaults, reason: 'an emptied choice is no filter');
    });

    testWidgets('the bar shows a count, and the sheet returns what was chosen', (tester) async {
      ListFilter? out;
      await tester.pumpWidget(_harness(Builder(
        builder: (ctx) => ListFilterBar(
          summary: 'Any date · All statuses',
          activeCount: 0,
          onTap: () async => out = await showListFilterSheet(ctx, initial: const ListFilter(), defaults: const ListFilter(), groups: const [_status]),
        ),
      )));
      expect(find.text('Filter'), findsOneWidget);
      await tester.tap(find.text('Filter'));
      await tester.pumpAndSettle();
      await tester.tap(find.widgetWithText(ChoiceChip, 'Approved'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Show results'));
      await tester.pumpAndSettle();
      expect(out, const ListFilter(groups: {'status': 'APPROVED'}));
    });

    testWidgets('Reset returns the defaults; dismissing returns nothing', (tester) async {
      const defaults = ListFilter(from: '2026-10-16', to: '2026-11-15');
      ListFilter? out = const ListFilter();
      await tester.pumpWidget(_harness(Builder(
        builder: (ctx) => TextButton(
          onPressed: () async => out = await showListFilterSheet(ctx, initial: defaults.withGroup('status', 'APPROVED'), defaults: defaults, groups: const [_status]),
          child: const Text('open'),
        ),
      )));
      await tester.tap(find.text('open'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Reset'));
      await tester.pumpAndSettle();
      expect(out, defaults);

      await tester.tap(find.text('open'));
      await tester.pumpAndSettle();
      await tester.tapAt(const Offset(10, 10));
      await tester.pumpAndSettle();
      expect(out, isNull);
    });

    testWidgets('an active filter is announced with its count', (tester) async {
      final handle = tester.ensureSemantics();
      await tester.pumpWidget(_harness(ListFilterBar(summary: 'x', activeCount: 2, onTap: () {})));
      expect(find.text('Filter (2)'), findsOneWidget);
      expect(find.bySemanticsLabel('Filter, 2 filters on'), findsOneWidget);
      handle.dispose();
    });
  });

  group('searchable choices', () {
    final people = [for (var i = 0; i < 30; i++) (value: 'e-$i', label: 'Person $i (E-$i)')];

    testWidgets('search narrows the list and picking returns the value', (tester) async {
      var value = '';
      await tester.pumpWidget(_harness(StatefulBuilder(
        builder: (ctx, set) => SizedBox(
          width: 300,
          child: SearchableChoiceField(title: 'Choose an employee', choices: people, value: value, allLabel: 'All employees', onChanged: (v) => set(() => value = v)),
        ),
      )));
      expect(find.text('All employees'), findsOneWidget);
      await tester.tap(find.text('All employees'));
      await tester.pumpAndSettle();
      await tester.enterText(find.byType(TextField), 'E-27');
      await tester.pumpAndSettle();
      expect(find.text('Person 3 (E-3)'), findsNothing);
      await tester.tap(find.text('Person 27 (E-27)'));
      await tester.pumpAndSettle();
      expect(value, 'e-27');
      expect(find.text('Person 27 (E-27)'), findsOneWidget, reason: 'the field shows the choice');
    });

    testWidgets('no match says so', (tester) async {
      await tester.pumpWidget(_harness(Builder(
        builder: (ctx) => TextButton(onPressed: () => pickChoice(ctx, title: 'Pick', choices: people), child: const Text('open')),
      )));
      await tester.tap(find.text('open'));
      await tester.pumpAndSettle();
      await tester.enterText(find.byType(TextField), 'zzz');
      await tester.pumpAndSettle();
      expect(find.text('Nothing matches "zzz".'), findsOneWidget);
    });
  });
}
