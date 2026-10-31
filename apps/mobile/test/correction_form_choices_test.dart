import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:hrms_mobile/core/api/api_error.dart';
import 'package:hrms_mobile/core/auth/permissions.dart';
import 'package:hrms_mobile/core/forms/choice_sources.dart';
import 'package:hrms_mobile/core/providers.dart';
import 'package:hrms_mobile/core/requests/request_screens.dart';
import 'package:hrms_mobile/features/attendance/domain/request_resources.dart';

import 'support/fake_api_client.dart';
import 'support/fake_auth.dart';

/// T3-03 (mobile only): `/shifts` needs ORG.SHIFT.MANAGE, which an employee lacks. The correction
/// form must open, keep punch-time corrections usable and disable only "correct the shift".
FakeApiClient _api({Object? shiftsError}) => FakeApiClient(
      lists: {
        '/regularizations': const [],
        '/shifts': [
          {'id': 'sh-1', 'name': 'General', 'is_active': true},
        ],
        '/employees': [
          {'id': 'emp-2', 'first_name': 'Ravi', 'last_name': 'Iyer', 'employee_code': 'E-2'},
        ],
      },
      failing: {if (shiftsError != null) '/shifts': shiftsError},
    );

final _denied = ApiError(status: 403, code: 'PERMISSION_DENIED', message: 'Permission ORG.SHIFT.MANAGE is required');

Future<void> _pump(WidgetTester tester, FakeApiClient api, {List<String> permissions = const [attendanceRegularizationRequest]}) async {
  tester.view.physicalSize = const Size(800, 4000);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
  await tester.pumpWidget(ProviderScope(
    overrides: [apiClientProvider.overrideWithValue(api), fakeAuth(permissions, employeeId: 'emp-1')],
    child: MaterialApp(home: RequestListScreen(config: regularizationConfig)),
  ));
  await tester.pumpAndSettle();
}

Future<void> _openForm(WidgetTester tester) async {
  await tester.tap(find.text('Regularization request'));
  await tester.pumpAndSettle();
}

Future<void> _closeForm(WidgetTester tester) async {
  await tester.pageBack();
  await tester.pumpAndSettle();
}

SwitchListTile _shiftToggle(WidgetTester tester) => tester.widget<SwitchListTile>(find.widgetWithText(SwitchListTile, 'Correct the assigned shift instead of punch times'));

int _shiftCalls(FakeApiClient api) => api.listCalls.where((c) => c.path == '/shifts').length;

void main() {
  testWidgets('403 on /shifts: the form opens without an error banner and punch times stay usable', (tester) async {
    final api = _api(shiftsError: _denied);
    await _pump(tester, api);
    await _openForm(tester);

    expect(find.textContaining('Could not load the options'), findsNothing);
    expect(find.text('HH:MM'), findsNWidgets(2), reason: 'check-in and check-out time fields');
    expect(find.widgetWithText(FilledButton, 'Create'), findsOneWidget);
  });

  testWidgets('403 on /shifts: only the shift option is disabled, with an explanation', (tester) async {
    await _pump(tester, _api(shiftsError: _denied));
    await _openForm(tester);

    expect(_shiftToggle(tester).onChanged, isNull);
    expect(_shiftToggle(tester).value, isFalse);
    expect(find.text('Not available with your access. Ask HR to change this for you.'), findsOneWidget);
    expect(find.text('Select'), findsOneWidget, reason: 'only the request-type picker; the shift picker stays hidden');
  });

  testWidgets('a refused endpoint is not asked again when the form is reopened', (tester) async {
    final api = _api(shiftsError: _denied);
    await _pump(tester, api);
    await _openForm(tester);
    expect(_shiftCalls(api), 1);
    await _closeForm(tester);
    await _openForm(tester);
    await _closeForm(tester);
    await _openForm(tester);
    expect(_shiftCalls(api), 1, reason: 'one 403 per session, then never again');
    expect(find.text('Not available with your access. Ask HR to change this for you.'), findsOneWidget);
  });

  testWidgets('a holder of ORG.SHIFT.MANAGE (the call succeeds) keeps the shift option', (tester) async {
    final api = _api();
    await _pump(tester, api, permissions: const [attendanceRegularizationRequest, orgShiftManage]);
    await _openForm(tester);
    expect(_shiftToggle(tester).onChanged, isNotNull);
    await tester.tap(find.text('Correct the assigned shift instead of punch times'));
    await tester.pumpAndSettle();
    expect(find.text('Select'), findsNWidgets(2), reason: 'request type and the shift picker');
    expect(find.text('HH:MM'), findsNothing);
  });

  testWidgets('any other failure also keeps the form, says so, and is tried again next time', (tester) async {
    final api = _api(shiftsError: ApiError(status: 500, code: 'X', message: 'down'));
    await _pump(tester, api);
    await _openForm(tester);
    expect(find.textContaining('Could not load the options'), findsNothing);
    expect(_shiftToggle(tester).onChanged, isNull);
    expect(find.text('Couldn\'t load the options for this. Try again later.'), findsOneWidget);
    await _closeForm(tester);
    await _openForm(tester);
    expect(_shiftCalls(api), 2, reason: 'a transient failure is not remembered as a refusal');
  });

  testWidgets('a required source still fails the form: on-behalf needs the employee list', (tester) async {
    final api = FakeApiClient(
      lists: {'/regularizations': const [], '/shifts': const []},
      failing: {'/employees': ApiError(status: 500, code: 'X', message: 'no employees')},
    );
    await _pump(tester, api, permissions: const [attendanceRegularizationRequest, attendanceRegularizationApprove, attendanceRegularizationRequestOnBehalf]);
    await tester.tap(find.text('Regularization request on behalf'));
    await tester.pumpAndSettle();
    expect(find.textContaining('Could not load the options'), findsOneWidget);
  });

  group('loadChoicesTolerant', () {
    test('required sources throw; optional ones are reported, not thrown', () async {
      final ok = await loadChoicesTolerant(_api(shiftsError: _denied), optional: ['shifts']);
      expect(ok.unavailable['shifts'], ChoiceUnavailable.denied);
      expect(ok.choices.containsKey('shifts'), isFalse);
      await expectLater(loadChoicesTolerant(_api(shiftsError: _denied), required: ['shifts']), throwsA(isA<ApiError>()));
    });

    test('a known-denied source is not requested at all', () async {
      final api = _api();
      final r = await loadChoicesTolerant(api, optional: ['shifts'], knownDenied: {'shifts'});
      expect(r.unavailable['shifts'], ChoiceUnavailable.denied);
      expect(api.listCalls, isEmpty);
    });

    test('loadChoices itself is unchanged: it still fails whole', () async {
      await expectLater(loadChoices(_api(shiftsError: _denied), ['shifts']), throwsA(isA<ApiError>()));
    });
  });
}
