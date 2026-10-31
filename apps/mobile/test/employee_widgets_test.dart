import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:hrms_mobile/core/theme/app_theme.dart';
import 'package:hrms_mobile/core/widgets/employee/employee_status_chip.dart';
import 'package:hrms_mobile/core/widgets/employee/filter_sheet.dart';
import 'package:hrms_mobile/core/widgets/employee/interaction.dart';
import 'package:hrms_mobile/core/widgets/employee/layout.dart';
import 'package:hrms_mobile/core/widgets/employee/leave_balance_strip.dart';
import 'package:hrms_mobile/core/widgets/employee/request_row.dart';
import 'package:hrms_mobile/core/widgets/employee/status_map.dart';

import 'support/test_themes.dart';

void main() {
  setUpAll(primeThemes);

  group('status map', () {
    test('attendance buckets', () {
      expect(statusForAttendanceBucket('PRESENT').kind, StatusKind.success);
      expect(statusForAttendanceBucket('LEAVE').kind, StatusKind.onLeave);
      expect(statusForAttendanceBucket('REMOTE').kind, StatusKind.wfh);
      expect(statusForAttendanceBucket('CONFIG_ERROR').kind, StatusKind.danger);
      expect(statusForAttendanceBucket('HOLIDAY').kind, StatusKind.holiday);
      expect(statusForAttendanceBucket('ABSENT').label, 'Absent');
    });
    test('request statuses share one colour across leave, corrections and overtime', () {
      expect(statusForRequest('SUBMITTED').kind, StatusKind.warning);
      expect(statusForRequest('APPROVED').kind, StatusKind.success);
      expect(statusForRequest('AUTO_APPROVED').kind, StatusKind.success);
      expect(statusForRequest('AUTO_APPROVED').label, 'Auto-approved');
      expect(statusForRequest('REJECTED').kind, StatusKind.danger);
      expect(statusForRequest('CANCELLED').kind, StatusKind.holiday, reason: 'chosen by the employee, not an error');
      expect(statusForRequest('PENDING_APPROVAL', labels: {'PENDING_APPROVAL': 'Awaiting'}).label, 'Awaiting');
    });
    test('every kind has a glyph', () {
      for (final k in StatusKind.values) {
        expect(glyphFor(k), isA<IconData>());
      }
    });
  });

  for (final scale in [1.0, 2.0]) {
    group('renders at text scale $scale on a 320 px screen', () {
      Future<void> pump(WidgetTester tester, Widget w) async {
        tester.view.physicalSize = const Size(320, 640);
        tester.view.devicePixelRatio = 1;
        addTearDown(tester.view.reset);
        await tester.pumpWidget(employeeHarness(SingleChildScrollView(child: w), textScale: scale));
      }

      testWidgets('list group, rows and chips do not overflow', (tester) async {
        await pump(
          tester,
          EmployeeListGroup(children: [
            RequestRow(title: '1 Apr – 3 Apr · 3 days (a long leave type name that wraps)', caption: 'Casual leave', status: statusForRequest('SUBMITTED'), onTap: () {}),
            RequestRow(title: 'Missing punch · 30 Oct', status: statusForRequest('AUTO_APPROVED')),
          ]),
        );
        expect(tester.takeException(), isNull);
        expect(find.text('Submitted'), findsOneWidget);
      });

      testWidgets('status header and empty state', (tester) async {
        await pump(
          tester,
          Column(children: [
            EmployeeStatusHeader(status: statusForAttendanceBucket('PRESENT'), title: 'Friday, 30 Oct', subtitle: 'Asia/Kolkata', figure: '7h 05m', figureCaption: 'Worked'),
            const EmployeeEmptyState(icon: Icons.event_busy_outlined, title: 'No leave applications', message: 'Applications you submit will show up here.', actionLabel: 'Apply for leave'),
          ]),
        );
        expect(tester.takeException(), isNull);
        expect(find.text('Apply for leave'), findsOneWidget);
      });

      testWidgets('leave balance strip', (tester) async {
        await pump(
          tester,
          const LeaveBalanceStrip(items: [
            LeaveBalanceItem(name: 'Casual leave', balance: '8.50', reserved: '2.00'),
            LeaveBalanceItem(name: 'Sick leave', balance: '12.00', reserved: '0.00'),
            LeaveBalanceItem(name: 'Earned leave', balance: '3.00'),
            LeaveBalanceItem(name: 'Comp off', balance: '1.00'),
          ]),
        );
        expect(tester.takeException(), isNull);
      });
    });
  }

  testWidgets('balance strip keeps API decimal strings, shows the 3 largest, flags reserved only when non-zero', (tester) async {
    await tester.pumpWidget(employeeHarness(const LeaveBalanceStrip(items: [
      LeaveBalanceItem(name: 'Casual', balance: '8.50', reserved: '2.00'),
      LeaveBalanceItem(name: 'Sick', balance: '12.00', reserved: '0.00'),
      LeaveBalanceItem(name: 'Earned', balance: '3.25'),
      LeaveBalanceItem(name: 'Comp off', balance: '1.00'),
    ])));
    expect(find.text('12.00'), findsOneWidget);
    expect(find.text('8.50'), findsOneWidget);
    expect(find.text('3.25'), findsOneWidget);
    expect(find.text('Comp off'), findsNothing, reason: 'only the three largest are shown');
    expect(find.text('2.00 reserved'), findsOneWidget);
    expect(find.textContaining('0.00 reserved'), findsNothing);
    expect(find.text('All balances (+1)'), findsOneWidget);
  });

  testWidgets('list row is at least 64 high and tappable rows show a chevron', (tester) async {
    var taps = 0;
    await tester.pumpWidget(employeeHarness(EmployeeListGroup(children: [EmployeeListRow(title: 'Payslips', onTap: () => taps++)])));
    expect(tester.getSize(find.byType(EmployeeListRow)).height, greaterThanOrEqualTo(64));
    expect(find.byIcon(Icons.chevron_right_rounded), findsOneWidget);
    await tester.tap(find.text('Payslips'));
    expect(taps, 1);
  });

  testWidgets('status chip exposes the status word to screen readers', (tester) async {
    final handle = tester.ensureSemantics();
    await tester.pumpWidget(employeeHarness(EmployeeStatusChip(status: statusForRequest('APPROVED'))));
    expect(find.bySemanticsLabel('Status: Approved'), findsOneWidget);
    handle.dispose();
  });

  group('confirmDestructive', () {
    testWidgets('returns true only on the destructive action', (tester) async {
      bool? result;
      await tester.pumpWidget(employeeHarness(Builder(
        builder: (ctx) => TextButton(
          onPressed: () async => result = await confirmDestructive(ctx, title: 'Sign out?', body: 'You will need to sign in again to use the app.', confirmLabel: 'Sign out'),
          child: const Text('open'),
        ),
      )));
      await tester.tap(find.text('open'));
      await tester.pumpAndSettle();
      expect(find.text('Sign out?'), findsOneWidget);
      await tester.tap(find.text('Cancel'));
      await tester.pumpAndSettle();
      expect(result, isFalse);
      await tester.tap(find.text('open'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Sign out'));
      await tester.pumpAndSettle();
      expect(result, isTrue);
    });
  });

  group('filter sheet', () {
    testWidgets('Apply returns the chosen status; Clear returns an empty filter; caption describes it', (tester) async {
      EmployeeFilter? out;
      await tester.pumpWidget(employeeHarness(Builder(
        builder: (ctx) => TextButton(
          onPressed: () async => out = await showEmployeeFilterSheet(ctx, initial: const EmployeeFilter(dateFrom: '2026-10-01'), statuses: const {'SUBMITTED': 'Submitted', 'APPROVED': 'Approved'}),
          child: const Text('open'),
        ),
      )));
      await tester.tap(find.text('open'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Submitted'));
      await tester.tap(find.text('Apply'));
      await tester.pumpAndSettle();
      expect(out, const EmployeeFilter(dateFrom: '2026-10-01', status: 'SUBMITTED'));
      expect(out!.caption(statusLabels: const {'SUBMITTED': 'Submitted'}), '2026-10-01 – … · Submitted');

      await tester.tap(find.text('open'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Clear'));
      await tester.pumpAndSettle();
      expect(out, const EmployeeFilter());
      expect(out!.caption(), 'All dates · All statuses');
    });

    testWidgets('dismissing returns null (keep the current filter)', (tester) async {
      EmployeeFilter? out = const EmployeeFilter(status: 'X');
      await tester.pumpWidget(employeeHarness(Builder(
        builder: (ctx) => TextButton(onPressed: () async => out = await showEmployeeFilterSheet(ctx, initial: const EmployeeFilter()), child: const Text('open')),
      )));
      await tester.tap(find.text('open'));
      await tester.pumpAndSettle();
      await tester.tapAt(const Offset(10, 10));
      await tester.pumpAndSettle();
      expect(out, isNull);
    });
  });

  testWidgets('sticky bar sits below the body: nothing is covered', (tester) async {
    await tester.pumpWidget(employeeHarness(WithStickyBar(body: ListView(children: [for (var i = 0; i < 40; i++) Text('row $i')]), bar: const Text('Punch in'))));
    final bar = tester.getTopLeft(find.text('Punch in')).dy;
    final list = tester.getBottomLeft(find.byType(ListView)).dy;
    expect(bar, greaterThanOrEqualTo(list));
  });

  group('form scaffold', () {
    Future<ValueNotifier<bool>> openForm(WidgetTester tester) async {
      final dirty = ValueNotifier<bool>(false);
      await tester.pumpWidget(MaterialApp(
        theme: AppTheme.employee,
        home: Builder(
          builder: (ctx) => Scaffold(
            body: TextButton(
              onPressed: () => Navigator.of(ctx).push(MaterialPageRoute<void>(
                builder: (_) => ValueListenableBuilder<bool>(
                  valueListenable: dirty,
                  builder: (c, d, _) => EmployeeFormScaffold(
                    title: 'Apply for leave',
                    submitLabel: 'Submit',
                    onSubmit: () {},
                    dirty: d,
                    discardTitle: 'Discard this application?',
                    children: const [Text('field')],
                  ),
                ),
              )),
              child: const Text('open'),
            ),
          ),
        ),
      ));
      await tester.tap(find.text('open'));
      await tester.pumpAndSettle();
      return dirty;
    }

    testWidgets('a clean form closes without asking', (tester) async {
      await openForm(tester);
      await tester.pageBack();
      await tester.pumpAndSettle();
      expect(find.text('open'), findsOneWidget);
    });

    testWidgets('a dirty form asks before discarding, and Keep editing stays', (tester) async {
      final dirty = await openForm(tester);
      dirty.value = true;
      await tester.pumpAndSettle();
      await tester.pageBack();
      await tester.pumpAndSettle();
      expect(find.text('Discard this application?'), findsOneWidget);
      await tester.tap(find.text('Keep editing'));
      await tester.pumpAndSettle();
      expect(find.text('Apply for leave'), findsOneWidget);
      await tester.pageBack();
      await tester.pumpAndSettle();
      await tester.tap(find.text('Discard'));
      await tester.pumpAndSettle();
      expect(find.text('open'), findsOneWidget);
    });

    testWidgets('busy disables Submit and shows the busy label', (tester) async {
      await tester.pumpWidget(employeeHarness(EmployeeFormScaffold(title: 'T', submitLabel: 'Submit', onSubmit: () {}, busy: true, children: const [Text('f')])));
      expect(find.text('Submit…'), findsOneWidget);
      expect(tester.widget<FilledButton>(find.byType(FilledButton)).onPressed, isNull);
    });
  });

  testWidgets('progress track shows step n of m', (tester) async {
    await tester.pumpWidget(employeeHarness(const ProgressTrack(step: 2, total: 11)));
    expect(find.text('Step 3 of 11'), findsOneWidget);
  });

  testWidgets('components also render under the administrator dark theme (tokens fall back to the scheme)', (tester) async {
    await tester.pumpWidget(employeeHarness(
      EmployeeListGroup(children: [RequestRow(title: 'Row', status: statusForRequest('APPROVED'))]),
      theme: AppTheme.dark,
    ));
    expect(tester.takeException(), isNull);
    expect(find.text('Approved'), findsOneWidget);
  });
}
