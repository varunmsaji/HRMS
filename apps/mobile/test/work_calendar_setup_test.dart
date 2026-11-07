import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:hrms_mobile/core/api/api_error.dart';
import 'package:hrms_mobile/core/auth/permissions.dart';
import 'package:hrms_mobile/core/providers.dart';
import 'package:hrms_mobile/core/resource/resource_screens.dart';
import 'package:hrms_mobile/core/time.dart';
import 'package:hrms_mobile/features/organisation/domain/org_resources.dart';
import 'package:hrms_mobile/features/organisation/presentation/work_calendar_setup_screen.dart';

import 'support/fake_api_client.dart';
import 'support/fake_auth.dart';

const _required = {
  'state': 'SETUP_REQUIRED',
  'message': 'Setup required',
  'holiday_calendar_count': 1,
  'suggestion': {
    'confirmed': false,
    'working_weekdays': [0, 1, 2, 3, 4],
    'weekly_off_weekdays': [5, 6],
    'weekday_labels': ['Monday'],
    'holidays_included': false,
    'notice': 'Suggested from your company profile; nothing is active yet.',
  },
};

const _configured = {
  'state': 'CONFIGURED',
  'message': 'ok',
  'holiday_calendar_count': 1,
  'company_assignment': {'assignment_id': 'as1', 'work_calendar_id': 'wc9', 'scope_type': 'COMPANY', 'scope_id': null, 'effective_from': '2026-11-07'},
};

const _preview = {
  'preview_only': true,
  'notice': 'Preview only.',
  'effective_from': '2026-11-07',
  'range_from': '2026-11-07',
  'range_to': '2026-11-08',
  'working_day_count': 1,
  'non_working_day_count': 1,
  'holiday_calendar_count': 0,
  'warnings': ['No holiday calendar is linked.'],
  'days': [
    {'date': '2026-11-07', 'day_type': 'WORKING'},
    {'date': '2026-11-08', 'day_type': 'WEEKLY_OFF', 'weekly_off_fraction': '1.00'},
  ],
};

/// Serves the setup status, switching to CONFIGURED once a confirm succeeds.
class _Api extends FakeApiClient {
  _Api({Map<String, dynamic> status = _required, super.failing})
      : _status = status,
        super(
          objects: {'/work-calendar-setup/preview': _preview, '/work-calendar-setup/confirm': const {}},
          lists: {
            '/holiday-calendars': [
              {'id': 'hc1', 'name': 'India 2026', 'is_active': true},
              {'id': 'hc2', 'name': 'Old list', 'is_active': false},
            ],
          },
        );
  Map<String, dynamic> _status;
  int statusLoads = 0;

  @override
  Future<T> get<T>(String path, {required T Function(dynamic) parse, bool authenticated = true}) async {
    if (path == '/work-calendar-setup') {
      statusLoads++;
      if (failing.containsKey(path)) throw failing[path]!;
      return parse(_status);
    }
    return super.get(path, parse: parse, authenticated: authenticated);
  }

  @override
  Future<T> post<T>(String path, {dynamic body, required T Function(dynamic) parse, bool authenticated = true, String? ifMatch, Map<String, String>? headers}) async {
    final result = await super.post(path, body: body, parse: parse, authenticated: authenticated, ifMatch: ifMatch, headers: headers);
    if (path == '/work-calendar-setup/confirm') _status = _configured;
    return result;
  }
}

Future<void> _pump(WidgetTester tester, FakeApiClient api, {List<String> perms = const [orgCalendarManage]}) async {
  tester.view.physicalSize = const Size(600, 3200);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
  await tester.pumpWidget(ProviderScope(
    overrides: [apiClientProvider.overrideWithValue(api), fakeAuth(perms)],
    child: const MaterialApp(home: WorkCalendarSetupScreen()),
  ));
  await tester.pumpAndSettle();
}

bool _checked(WidgetTester tester, String label) => tester.widget<CheckboxListTile>(find.widgetWithText(CheckboxListTile, label)).value == true;

VoidCallback? _button(WidgetTester tester, String label) {
  final f = find.widgetWithText(FilledButton, label);
  if (f.evaluate().isNotEmpty) return tester.widget<FilledButton>(f).onPressed;
  return tester.widget<OutlinedButton>(find.widgetWithText(OutlinedButton, label)).onPressed;
}

void main() {
  testWidgets('starts from the suggestion; active holiday calendars only; activate needs a preview', (tester) async {
    await _pump(tester, _Api());
    expect(find.text('Work calendar setup required'), findsOneWidget);
    expect(find.text('Suggested from your company profile; nothing is active yet.'), findsOneWidget);
    expect(_checked(tester, 'Saturday'), isTrue);
    expect(_checked(tester, 'Sunday'), isTrue);
    expect(_checked(tester, 'Monday'), isFalse);
    expect(find.text('India 2026'), findsOneWidget);
    expect(find.text('Old list'), findsNothing);
    expect(_button(tester, 'Review and activate'), isNull);
  });

  testWidgets('preview sends the proposal and shows the result; an edit makes it stale', (tester) async {
    final api = _Api();
    await _pump(tester, api);
    await tester.tap(find.text('India 2026'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Preview calendar'));
    await tester.pumpAndSettle();
    final call = api.calls.single;
    expect(call.path, '/work-calendar-setup/preview');
    expect(call.body, {'weekly_off_weekdays': [5, 6], 'holiday_calendar_ids': ['hc1'], 'effective_from': businessToday('Asia/Kolkata')});
    expect(find.text('Not saved'), findsOneWidget);
    expect(find.textContaining('1 working day, 1 non-working.'), findsOneWidget);
    expect(find.text('• No holiday calendar is linked.'), findsOneWidget);
    expect(find.bySemanticsLabel('2026-11-08: Weekly off'), findsOneWidget);
    expect(_button(tester, 'Review and activate'), isNotNull);

    await tester.tap(find.text('Friday'));
    await tester.pumpAndSettle();
    expect(find.text('The proposal changed after the last preview. Preview again before activating.'), findsOneWidget);
    expect(_button(tester, 'Review and activate'), isNull);
    await tester.tap(find.text('Preview calendar'));
    await tester.pumpAndSettle();
    expect((api.calls.last.body as Map)['weekly_off_weekdays'], [4, 5, 6]);
    expect(_button(tester, 'Review and activate'), isNotNull);
  });

  testWidgets('seven weekly offs or an empty name cannot be previewed', (tester) async {
    await _pump(tester, _Api());
    for (final d in ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday']) {
      await tester.tap(find.text(d));
    }
    await tester.pumpAndSettle();
    expect(_button(tester, 'Preview calendar'), isNull);
    await tester.tap(find.text('Monday'));
    await tester.enterText(find.widgetWithText(TextField, 'Calendar name'), '  ');
    await tester.pumpAndSettle();
    expect(_button(tester, 'Preview calendar'), isNull);
  });

  testWidgets('activating needs the acknowledgement, then confirms and shows it configured', (tester) async {
    final api = _Api();
    await _pump(tester, api);
    await tester.tap(find.text('Preview calendar'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Review and activate'));
    await tester.pumpAndSettle();
    expect(find.text('Activate this work calendar?'), findsOneWidget);
    expect(tester.widget<FilledButton>(find.widgetWithText(FilledButton, 'Activate calendar')).onPressed, isNull);
    await tester.tap(find.textContaining('I have reviewed the preview'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Activate calendar'));
    await tester.pumpAndSettle();

    final confirm = api.calls.last;
    expect(confirm.path, '/work-calendar-setup/confirm');
    expect(confirm.body, {'weekly_off_weekdays': [5, 6], 'holiday_calendar_ids': <String>[], 'effective_from': businessToday('Asia/Kolkata'), 'name': 'Default work calendar', 'confirm': true});
    expect(find.text('Work calendar activated'), findsOneWidget);
    expect(find.text('Configured'), findsOneWidget);
    expect(find.text('The work calendar has been activated. It applies from 2026-11-07.'), findsOneWidget);
  });

  testWidgets('if another admin activated first, it says so and reloads', (tester) async {
    final api = _Api(failing: {'/work-calendar-setup/confirm': ApiError(status: 409, code: 'WORK_CALENDAR_ALREADY_CONFIGURED', message: 'Already configured.')});
    await _pump(tester, api);
    await tester.tap(find.text('Preview calendar'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Review and activate'));
    await tester.pumpAndSettle();
    await tester.tap(find.textContaining('I have reviewed the preview'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Activate calendar'));
    await tester.pumpAndSettle();
    expect(find.textContaining('Someone else activated a calendar first.'), findsOneWidget);
    expect(api.statusLoads, 2);
  });

  testWidgets('an active company calendar is shown as configured with a link to it', (tester) async {
    await _pump(tester, _Api(status: _configured));
    expect(find.text('A company-wide work calendar is already active. It applies from 2026-11-07.'), findsOneWidget);
    expect(find.text('View the calendar'), findsOneWidget);
    expect(find.text('Preview calendar'), findsNothing);
  });

  testWidgets('without calendar management the suggestion is read-only', (tester) async {
    await _pump(tester, _Api(), perms: const []);
    expect(find.text('You can view this suggestion but need calendar management permission to activate it.'), findsOneWidget);
    expect(find.text('Preview calendar'), findsNothing);
    expect(tester.widget<CheckboxListTile>(find.widgetWithText(CheckboxListTile, 'Monday')).onChanged, isNull);
  });

  testWidgets('a forbidden status says so without a retry', (tester) async {
    await _pump(tester, _Api(failing: {'/work-calendar-setup': ApiError(status: 403, code: 'PERMISSION_DENIED', message: 'no')}));
    expect(find.text('You do not have permission to manage work calendars.'), findsOneWidget);
    expect(find.text('Try again'), findsNothing);
  });

  Future<void> list(WidgetTester tester, List<String> perms) async {
    await tester.pumpWidget(ProviderScope(
      overrides: [apiClientProvider.overrideWithValue(FakeApiClient()), fakeAuth(perms)],
      child: MaterialApp(home: ResourceListScreen(config: workCalendarResource)),
    ));
    await tester.pumpAndSettle();
  }

  testWidgets('the Work Calendars list offers Guided setup to calendar managers', (tester) async {
    await list(tester, const [orgCalendarManage]);
    expect(find.text('Guided setup'), findsOneWidget);
  });

  testWidgets('without calendar management there is no Guided setup', (tester) async {
    await list(tester, const []);
    expect(find.text('Guided setup'), findsNothing);
  });
}
