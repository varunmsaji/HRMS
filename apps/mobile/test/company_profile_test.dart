import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:hrms_mobile/core/auth/permissions.dart';
import 'package:hrms_mobile/core/providers.dart';
import 'package:hrms_mobile/features/organisation/domain/company_profile_form.dart';
import 'package:hrms_mobile/features/organisation/presentation/company_profile_screen.dart';

import 'support/fake_api_client.dart';
import 'support/fake_auth.dart';

final _profile = {
  'id': 'c1',
  'name': 'Acme',
  'legal_name': null,
  'registration_number': null,
  'industry_code': null,
  'company_size': '11-50',
  'country_code': 'IN',
  'currency': 'INR',
  'timezone': 'Asia/Kolkata',
  'status': 'TRIAL',
  'version': 4,
  'subdomain': 'acme',
  'onboarded_at': null,
  'trial_ends_at': null,
  'contact': {'email': 'hr@acme.test', 'phone': null, 'website': null},
  'address': {'line1': null, 'line2': null, 'city': 'Pune', 'state': null, 'postal_code': null, 'country_code': null},
  'locale': {'language_code': 'en-IN', 'date_format': 'DD/MM/YYYY'},
  'fiscal_year': {'start_month': 4},
  'working_days': [
    for (final d in ['MON', 'TUE', 'WED', 'THU', 'FRI']) {'day': d, 'is_working': true, 'is_alternate': false},
    for (final d in ['SAT', 'SUN']) {'day': d, 'is_working': false, 'is_alternate': false},
  ],
  'business_hours': {'start_time': '09:00', 'end_time': '18:00'},
  'branding': {'logo_url': null, 'theme': {'primary_color': '#4F46E5'}},
};

Future<FakeApiClient> _pump(WidgetTester tester) async {
  tester.view.physicalSize = const Size(800, 4000);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
  final api = FakeApiClient(objects: {'/companies/current': _profile});
  await tester.pumpWidget(ProviderScope(overrides: [apiClientProvider.overrideWithValue(api), fakeAuth([orgCompanyManage])], child: const MaterialApp(home: CompanyProfileScreen())));
  await tester.pumpAndSettle();
  return api;
}

void main() {
  test('an unchanged form produces no patch', () {
    final form = profileToForm(_profile);
    expect(buildProfilePatch(form, const {}), isEmpty);
  });

  test('a changed member sends its whole nested group, like the web', () {
    final form = {...profileToForm(_profile), 'address_city': 'Mumbai', 'wd_SAT': true, 'primary_color': '#000000'};
    final patch = buildProfilePatch(form, {'address_city': 'Mumbai', 'wd_SAT': true, 'primary_color': '#000000'});
    expect((patch['address'] as Map)['city'], 'Mumbai');
    expect((patch['address'] as Map).keys, containsAll(['line1', 'line2', 'state', 'postal_code', 'country_code']));
    expect((patch['working_days'] as List).length, 7);
    expect(((patch['working_days'] as List).firstWhere((d) => d['day'] == 'SAT') as Map)['is_working'], true);
    expect(patch['branding'], {'logo_url': null, 'theme': {'primary_color': '#000000'}});
    expect(patch.containsKey('contact'), isFalse);
  });

  test('the form needs one working day and a consistent pair of business hours', () {
    final spec = companyProfileSpec(currencyLocked: false);
    final none = {...profileToForm(_profile), for (final d in weekDays) 'wd_$d': false};
    expect(spec.extraValidate!(none), contains('wd_MON'));
    expect(spec.extraValidate!({...profileToForm(_profile), 'bh_end': '08:00'}), contains('bh_end'));
    expect(spec.extraValidate!(profileToForm(_profile)), isEmpty);
  });

  testWidgets('shows every section of the profile', (tester) async {
    await _pump(tester);
    for (final t in ['Basic information', 'Contact information', 'Address', 'Localization', 'Working schedule', 'Business hours', 'Branding', 'Company metadata']) {
      expect(find.text(t), findsOneWidget);
    }
    expect(find.text('Monday, Tuesday, Wednesday, Thursday, Friday'), findsOneWidget);
    expect(find.text('09:00 – 18:00'), findsOneWidget);
    expect(find.text('April'), findsOneWidget);
    expect(find.text('#4F46E5'), findsOneWidget);
  });

  testWidgets('editing sends only the changed group, with the profile version as If-Match', (tester) async {
    final api = await _pump(tester);
    await tester.tap(find.byTooltip('Edit'));
    await tester.pumpAndSettle();
    await tester.enterText(find.widgetWithText(TextField, 'Pune'), 'Mumbai');
    await tester.scrollUntilVisible(find.text('Save changes'), 400, scrollable: find.byType(Scrollable).first);
    await tester.tap(find.text('Save changes'));
    await tester.pumpAndSettle();
    final call = api.calls.singleWhere((c) => c.method == 'PATCH');
    expect(call.path, '/companies/current');
    expect(call.ifMatch, '4');
    expect(call.body, {
      'address': {'line1': null, 'line2': null, 'city': 'Mumbai', 'state': null, 'postal_code': null, 'country_code': null},
    });
  });
}
