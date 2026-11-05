import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:hrms_mobile/core/auth/permissions.dart';
import 'package:hrms_mobile/core/nav/nav_entries.dart';
import 'package:hrms_mobile/core/providers.dart';
import 'package:hrms_mobile/features/attendance/data/location_provider.dart';
import 'package:hrms_mobile/features/attendance/domain/geofence_admin.dart';
import 'package:hrms_mobile/features/attendance/domain/punch_location.dart';
import 'package:hrms_mobile/features/attendance/presentation/geofences_screen.dart';

import 'support/fake_api_client.dart';
import 'support/fake_auth.dart';

const _head = {
  'branch_id': 'b-1',
  'name': 'Head Office',
  'code': null,
  'is_active': true,
  'latitude': 12.97160,
  'longitude': 77.59460,
  'radius_m': 150,
  'configured': true,
  'assigned_employee_count': 12,
  'authorized_employee_count': 2,
};
const _plant = {
  'branch_id': 'b-2',
  'name': 'Plant',
  'code': null,
  'is_active': true,
  'latitude': null,
  'longitude': null,
  'radius_m': null,
  'configured': false,
  'assigned_employee_count': 4,
  'authorized_employee_count': 0,
};
const _employee = {'id': 'e-1', 'employee_code': 'E1', 'first_name': 'Asha', 'last_name': 'Rao', 'display_name': 'Asha Rao', 'status': 'ACTIVE', 'is_active': true, 'version': 1, 'company_id': 'c-1'};
Map<String, dynamic> _attempt({bool accepted = false}) => {
      'id': 'a-1',
      'employee_id': 'e-1',
      'punch_id': null,
      'direction': 'IN',
      'source': 'SELF',
      'mode': 'REQUIRED',
      'outcome': accepted ? 'INSIDE' : 'OUTSIDE_GEOFENCE',
      'accepted': accepted,
      'branch_id': 'b-1',
      'distance_m': '412.40',
      'radius_m': '150.00',
      'accuracy_m': '18.00',
      'latitude': '12.9750',
      'longitude': '77.5990',
      'captured_at': '2026-11-05T03:30:00+00:00',
      'client_error': null,
      'created_at': '2026-11-05T03:30:00+00:00',
    };

class _Gateway implements LocationGateway {
  _Gateway({this.accuracy = 12, this.mocked = false, this.enabled = true});
  final double accuracy;
  final bool mocked;
  final bool enabled;
  @override
  Future<bool> serviceEnabled() async => enabled;
  @override
  Future<GatewayPermission> permission() async => GatewayPermission.granted;
  @override
  Future<GatewayPermission> requestPermission() async => GatewayPermission.granted;
  @override
  Future<GpsFix> currentFix({required Duration timeout}) async => GpsFix(latitude: 12.9716012, longitude: 77.5946034, accuracyM: accuracy, timestamp: DateTime.now(), isMocked: mocked);
  @override
  Future<void> openAppSettings() async {}
  @override
  Future<void> openLocationSettings() async {}
}

Future<FakeApiClient> _pump(WidgetTester tester, {List<String> permissions = const [attendancePolicyManage, attendanceViewAll, orgBranchManage], List<Map<String, dynamic>> auths = const [], LocationGateway? gateway}) async {
  tester.view.physicalSize = const Size(600, 2600);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
  final api = FakeApiClient(
    lists: {
      '/attendance/geofences': const [_head, _plant],
      '/attendance/workplace-authorizations': auths,
      '/attendance/geofence-attempts': [_attempt()],
      '/employees': const [_employee],
    },
    objects: {'/branches/b-2': const {'id': 'b-2', 'version': 5}},
  );
  await tester.pumpWidget(ProviderScope(
    overrides: [
      apiClientProvider.overrideWithValue(api),
      fakeAuth(permissions),
      locationCaptureProvider.overrideWithValue(LocationCapture(gateway ?? _Gateway())),
    ],
    child: const MaterialApp(home: GeofencesScreen()),
  ));
  await tester.pumpAndSettle();
  return api;
}

void main() {
  test('a workplace can only be used once active and located', () {
    expect(GeofenceWorkplace.fromJson(_head).usable, isTrue);
    expect(GeofenceWorkplace.fromJson(_plant).usable, isFalse);
    expect(GeofenceWorkplace.fromJson(_plant).statusLabel, 'Not configured');
    expect(GeofenceWorkplace.fromJson({..._head, 'is_active': false}).statusLabel, 'Inactive');
  });

  test('outcomes read as the web does, and unknown ones are not hidden', () {
    expect(geofenceOutcomeLabel('OUTSIDE_GEOFENCE'), 'Outside the workplace');
    expect(geofenceOutcomeLabel('SOMETHING_NEW'), 'SOMETHING_NEW');
  });

  testWidgets('lists workplaces with their status, location and usage', (tester) async {
    await _pump(tester);
    expect(find.text('Head Office'), findsOneWidget);
    expect(find.text('Active'), findsOneWidget);
    expect(find.text('12.97160, 77.59460'), findsOneWidget);
    expect(find.text('Radius 150 m · 12 assigned · 2 also authorised'), findsOneWidget);
    expect(find.text('Not configured'), findsOneWidget);
    expect(find.text('No location set'), findsOneWidget);
  });

  testWidgets('only active located workplaces can be authorised', (tester) async {
    final api = await _pump(tester);
    await tester.tap(find.text('Authorise'));
    await tester.pumpAndSettle();
    expect(find.text('Choose an employee and a workplace.'), findsOneWidget);
    expect(api.calls, isEmpty);

    await tester.tap(find.byType(DropdownButtonFormField<String>));
    await tester.pumpAndSettle();
    expect(find.text('Plant'), findsOneWidget, reason: 'only its card; it is not offered in the menu');
    await tester.tap(find.text('Head Office').last);
    await tester.pumpAndSettle();
    await tester.tap(find.text('Choose an employee'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Asha Rao'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Authorise'));
    await tester.pumpAndSettle();
    final call = api.calls.single;
    expect(call.path, '/attendance/workplace-authorizations');
    expect(call.body, {'employee_id': 'e-1', 'branch_id': 'b-1'});
  });

  testWidgets('removing an authorisation asks first', (tester) async {
    final api = await _pump(tester, auths: const [{'id': 'wa-1', 'employee_id': 'e-1', 'branch_id': 'b-1', 'created_by_user_id': null, 'created_at': '2026-11-01T00:00:00+00:00'}]);
    await tester.tap(find.text('Remove'));
    await tester.pumpAndSettle();
    expect(api.calls, isEmpty);
    await tester.tap(find.widgetWithText(FilledButton, 'Remove'));
    await tester.pumpAndSettle();
    expect(api.calls.single.method, 'DELETE');
    expect(api.calls.single.path, '/attendance/workplace-authorizations/wa-1');
  });

  testWidgets('attempts open on rejected only, and the switch shows all', (tester) async {
    final api = await _pump(tester);
    expect(find.text('Outside the workplace'), findsOneWidget);
    expect(find.text('Distance 412 m of 150 m · GPS accuracy 18 m · REQUIRED'), findsOneWidget);
    Map<String, dynamic>? lastFilters() => api.listCalls.lastWhere((c) => c.path == '/attendance/geofence-attempts').filters;
    expect(lastFilters(), {'accepted': 'false'});
    await tester.tap(find.byType(SwitchListTile));
    await tester.pumpAndSettle();
    expect(lastFilters(), isEmpty);
  });

  testWidgets('a workplace location is saved on the branch against its current version', (tester) async {
    final api = await _pump(tester);
    await tester.tap(find.text('Use my current location').last);
    await tester.pumpAndSettle();
    expect(find.text('Set Plant here?'), findsOneWidget);
    expect(api.calls, isEmpty, reason: 'nothing is saved before the confirmation');
    await tester.enterText(find.widgetWithText(TextField, 'Radius (metres)'), '200');
    await tester.tap(find.text('Save location'));
    await tester.pumpAndSettle();
    final call = api.calls.single;
    expect(call.method, 'PATCH');
    expect(call.path, '/branches/b-2');
    expect(call.ifMatch, '5');
    expect(call.body, {'latitude': '12.971601', 'longitude': '77.594603', 'geofence_radius_m': 200});
    expect(find.text('Plant location saved.'), findsOneWidget);
  });

  testWidgets('a nonsense radius is refused before anything is sent', (tester) async {
    final api = await _pump(tester);
    await tester.tap(find.text('Use my current location').last);
    await tester.pumpAndSettle();
    await tester.enterText(find.widgetWithText(TextField, 'Radius (metres)'), '0');
    await tester.tap(find.text('Save location'));
    await tester.pumpAndSettle();
    expect(find.text('Enter a radius from 1 to 100000 metres.'), findsOneWidget);
    expect(api.calls, isEmpty);
  });

  for (final (name, gateway, message) in [
    ('imprecise', _Gateway(accuracy: 80), 'GPS accuracy is 80 m'),
    ('simulated', _Gateway(mocked: true), 'simulated location'),
    ('switched off', _Gateway(enabled: false), 'Turn on location services'),
  ]) {
    testWidgets('a $name reading cannot set a workplace', (tester) async {
      final api = await _pump(tester, gateway: gateway);
      await tester.tap(find.text('Use my current location').last);
      await tester.pumpAndSettle();
      expect(find.textContaining(message), findsOneWidget);
      expect(find.text('Save location'), findsNothing);
      expect(api.calls, isEmpty);
    });
  }

  testWidgets('without branch permission the location cannot be changed here', (tester) async {
    await _pump(tester, permissions: const [attendancePolicyManage]);
    expect(find.text('Use my current location'), findsNothing);
    expect(find.text('Edit branch'), findsNothing);
  });

  testWidgets('review-only access sees attempts and asks for nothing else', (tester) async {
    final api = await _pump(tester, permissions: const [attendanceViewAll]);
    expect(find.text('Location attempts'), findsOneWidget);
    expect(find.text('Workplaces'), findsNothing);
    expect(api.listCalls.map((c) => c.path), isNot(contains('/attendance/geofences')));
  });

  testWidgets('configure-only access is not asked for attempts', (tester) async {
    final api = await _pump(tester, permissions: const [attendancePolicyManage]);
    expect(find.text('Location attempts'), findsNothing);
    expect(api.listCalls.map((c) => c.path), isNot(contains('/attendance/geofence-attempts')));
  });

  testWidgets('with neither permission it says so', (tester) async {
    final api = await _pump(tester, permissions: const []);
    expect(find.text('No access'), findsOneWidget);
    expect(api.listCalls, isEmpty);
  });

  test('it is in the menu for those who can use it', () {
    List<String> routes(List<String> p) => [for (final g in visibleNavGroups(p)) for (final e in g.items) e.route];
    expect(routes(const [attendancePolicyManage]), contains('/app/attendance-geofences'));
    expect(routes(const [attendanceViewAll]), contains('/app/attendance-geofences'));
    expect(routes(const [attendanceView]), isNot(contains('/app/attendance-geofences')));
  });
}
