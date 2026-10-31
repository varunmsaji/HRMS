import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:hrms_mobile/core/theme/app_theme.dart';
import 'package:hrms_mobile/core/widgets/employee/employee_status_chip.dart';
import 'package:hrms_mobile/core/widgets/employee/interaction.dart';
import 'package:hrms_mobile/core/widgets/employee/layout.dart';
import 'package:hrms_mobile/core/widgets/employee/leave_balance_strip.dart';
import 'package:hrms_mobile/core/widgets/employee/request_row.dart';
import 'package:hrms_mobile/core/widgets/employee/status_map.dart';

import 'support/test_themes.dart';

/// Visual reference for the employee components (T0-05/T0-06). Rendered with Roboto from the
/// Flutter SDK because the test sandbox cannot download Inter; layout and colours are the real
/// ones. Regenerate with `flutter test --update-goldens test/employee_components_golden_test.dart`.
Future<bool> _loadRoboto() async {
  final root = Platform.environment['FLUTTER_ROOT'] ?? '${Platform.environment['HOME']}/flutter';
  final dir = '$root/bin/cache/artifacts/material_fonts';
  final files = {'Roboto-Regular.ttf', 'MaterialIcons-Regular.otf'};
  if (!files.every((f) => File('$dir/$f').existsSync())) return false;
  ByteData bytes(String f) => ByteData.view(File('$dir/$f').readAsBytesSync().buffer);
  // The theme's text styles name Inter families (google_fonts); register Roboto under those names
  // so every widget, including buttons, renders real glyphs instead of test boxes.
  for (final family in ['Roboto', 'Inter', 'Inter_regular', 'Inter_500', 'Inter_600', 'Inter_700']) {
    final loader = FontLoader(family);
    loader.addFont(Future.value(bytes('Roboto-Regular.ttf')));
    await loader.load();
  }
  final icons = FontLoader('MaterialIcons')..addFont(Future.value(bytes('MaterialIcons-Regular.otf')));
  await icons.load();
  return true;
}

void _noop() {}

Widget _gallery() => SingleChildScrollView(
      child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        EmployeeSectionHeader('Status', actionLabel: 'See all', onAction: () {}),
        Padding(
          padding: const EdgeInsets.symmetric(horizontal: 16),
          child: Wrap(spacing: 8, runSpacing: 8, children: [
            for (final b in ['PRESENT', 'HALF_DAY', 'ABSENT', 'LEAVE', 'REMOTE', 'HOLIDAY']) EmployeeStatusChip(status: statusForAttendanceBucket(b)),
            EmployeeStatusChip(status: statusForRequest('AUTO_APPROVED')),
          ]),
        ),
        const EmployeeSectionHeader('Status header'),
        EmployeeStatusHeader(status: statusForAttendanceBucket('PRESENT'), title: 'Friday, 30 Oct', subtitle: 'Asia/Kolkata', figure: '7h 05m', figureCaption: 'Worked'),
        const EmployeeSectionHeader('Leave balances'),
        LeaveBalanceStrip(items: [
          LeaveBalanceItem(name: 'Casual', balance: '8.50', reserved: '2.00'),
          LeaveBalanceItem(name: 'Sick', balance: '12.00'),
          LeaveBalanceItem(name: 'Earned', balance: '3.25'),
        ], onAll: _noop),
        const EmployeeSectionHeader('Leave'),
        EmployeeListGroup(children: [
          RequestRow(title: '1 Apr – 3 Apr', caption: 'Casual leave · 3 days', status: statusForRequest('SUBMITTED'), onTap: () {}),
          RequestRow(title: '12 Mar', caption: 'Sick leave · 1 day', status: statusForRequest('APPROVED'), onTap: () {}),
          RequestRow(title: '2 Feb – 3 Feb', caption: 'Casual leave · 2 days', status: statusForRequest('REJECTED'), onTap: () {}),
        ]),
        EmployeeEmptyState(icon: Icons.event_busy_outlined, title: 'No leave applications', message: 'Applications you submit will show up here.', actionLabel: 'Apply for leave', onAction: _noop),
        StickyActionBar(child: SizedBox(width: double.infinity, child: FilledButton(onPressed: () {}, child: const Text('Punch in')))),
      ]),
    );

void main() {
  setUpAll(primeThemes);

  for (final spec in [(w: 360.0, h: 1000.0, scale: 1.0, name: 'employee_components_360'), (w: 320.0, h: 1300.0, scale: 2.0, name: 'employee_components_320_scale2')]) {
    testWidgets('gallery ${spec.name}', (tester) async {
      if (!await tester.runAsync(_loadRoboto).then((v) => v ?? false)) {
        markTestSkipped('Roboto not found in the Flutter SDK');
        return;
      }
      tester.view.physicalSize = Size(spec.w, spec.h);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.reset);
      final theme = AppTheme.employee.copyWith(textTheme: AppTheme.employee.textTheme.apply(fontFamily: 'Roboto'));
      await tester.pumpWidget(employeeHarness(_gallery(), textScale: spec.scale, theme: theme));
      await tester.pump();
      expect(tester.takeException(), isNull);
      await expectLater(find.byType(MaterialApp), matchesGoldenFile('goldens/${spec.name}.png'));
    });
  }
}
