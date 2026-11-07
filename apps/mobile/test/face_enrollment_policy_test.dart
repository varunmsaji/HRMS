import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:hrms_mobile/core/api/api_error.dart';
import 'package:hrms_mobile/core/auth/permissions.dart';
import 'package:hrms_mobile/core/providers.dart';
import 'package:hrms_mobile/core/resource/resource_screens.dart';
import 'package:hrms_mobile/features/attendance/domain/policy_resources.dart';
import 'package:hrms_mobile/features/attendance/presentation/face_enrollment_policy_card.dart';

import 'support/fake_api_client.dart';
import 'support/fake_auth.dart';

const _path = '/attendance/face-enrollment-policy';

/// Serves the setting and answers a PUT with what was sent, like the API.
class _Api extends FakeApiClient {
  _Api({bool required = false, this.putError, super.failing}) : super(objects: {_path: {'require_enrollment_on_onboarding': required}});
  final Object? putError;
  int gets = 0;

  @override
  Future<T> get<T>(String path, {required T Function(dynamic) parse, bool authenticated = true}) {
    if (path == _path) gets++;
    return super.get(path, parse: parse, authenticated: authenticated);
  }

  @override
  Future<T> put<T>(String path, {dynamic body, required T Function(dynamic) parse, bool authenticated = true, String? ifMatch}) async {
    calls.add((method: 'PUT', path: path, body: body, ifMatch: ifMatch));
    if (putError != null) throw putError!;
    return parse(body);
  }
}

Future<void> _pump(WidgetTester tester, FakeApiClient api, List<String> perms, {Widget home = const Scaffold(body: FaceEnrollmentPolicyCard())}) async {
  tester.view.physicalSize = const Size(800, 1600);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
  await tester.pumpWidget(ProviderScope(overrides: [apiClientProvider.overrideWithValue(api), fakeAuth(perms)], child: MaterialApp(home: home)));
  await tester.pumpAndSettle();
}

bool _switchValue(WidgetTester tester) => tester.widget<SwitchListTile>(find.byType(SwitchListTile)).value;

void main() {
  testWidgets('without the face-enrollment grant the card is absent and nothing is asked', (tester) async {
    final api = _Api();
    await _pump(tester, api, const [attendancePolicyManage]);
    expect(find.text('Face enrollment during onboarding'), findsNothing);
    expect(api.gets, 0);
  });

  testWidgets('shows the current setting with web wording', (tester) async {
    await _pump(tester, _Api(required: true), const [attendanceFaceEnrollmentManage]);
    expect(find.text('Face enrollment during onboarding'), findsOneWidget);
    expect(find.text('Require face enrollment'), findsOneWidget);
    expect(find.textContaining('onboarding is not complete until the employee enrolls and HR approves'), findsOneWidget);
    expect(_switchValue(tester), isTrue);
  });

  testWidgets('turning it on sends the new value and confirms', (tester) async {
    final api = _Api();
    await _pump(tester, api, const [attendanceFaceEnrollmentManage]);
    await tester.tap(find.byType(Switch));
    await tester.pumpAndSettle();
    expect(api.calls.single.body, {'require_enrollment_on_onboarding': true});
    expect(_switchValue(tester), isTrue);
    expect(find.text('Face enrollment is now required in onboarding'), findsOneWidget);
  });

  testWidgets('turning it off says it is optional', (tester) async {
    await _pump(tester, _Api(required: true), const [attendanceFaceEnrollmentManage]);
    await tester.tap(find.byType(Switch));
    await tester.pumpAndSettle();
    expect(_switchValue(tester), isFalse);
    expect(find.text('Face enrollment is optional in onboarding'), findsOneWidget);
  });

  testWidgets('a failed save keeps the old value and says why', (tester) async {
    await _pump(tester, _Api(putError: ApiError(status: 403, code: 'PERMISSION_DENIED', message: 'Not allowed.')), const [attendanceFaceEnrollmentManage]);
    await tester.tap(find.byType(Switch));
    await tester.pumpAndSettle();
    expect(_switchValue(tester), isFalse);
    expect(find.text('Could not update the setting. Not allowed.'), findsOneWidget);
  });

  testWidgets('a failed load shows the reason instead of a switch', (tester) async {
    await _pump(tester, _Api(failing: {_path: ApiError(status: 500, code: 'X', message: 'Server unavailable.')}), const [attendanceFaceEnrollmentManage]);
    expect(find.text('Server unavailable.'), findsOneWidget);
    expect(find.byType(SwitchListTile), findsNothing);
  });

  testWidgets('sits above the Attendance Policies list, also when there are none yet', (tester) async {
    final api = _Api();
    await _pump(tester, api, const [attendancePolicyManage, attendanceFaceEnrollmentManage], home: ResourceListScreen(config: attendancePolicyResource));
    expect(find.text('Face enrollment during onboarding'), findsOneWidget);
    expect(find.text('No attendance policies yet'), findsOneWidget);
  });
}
