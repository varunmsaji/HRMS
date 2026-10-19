import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:hrms_mobile/core/auth/auth_types.dart';
import 'package:hrms_mobile/features/shell/app_shell.dart';

void main() {
  test('UserProfile reads company_status and defaults to ACTIVE for older APIs', () {
    final base = {
      'id': 'u',
      'email': 'a@b.c',
      'company_id': 'c',
      'employee_id': null,
      'permissions': <String>[],
      'company_timezone': 'Asia/Kolkata',
    };
    expect(UserProfile.fromJson(base).companyStatus, 'ACTIVE');
    expect(UserProfile.fromJson({...base, 'company_status': 'SUSPENDED'}).companyStatus, 'SUSPENDED');
  });

  testWidgets('banner explains the read-only state', (tester) async {
    await tester.pumpWidget(const MaterialApp(home: Scaffold(body: CompanyReadOnlyBanner(status: 'PENDING_APPROVAL'))));
    expect(find.textContaining('awaiting approval'), findsOneWidget);
    await tester.pumpWidget(const MaterialApp(home: Scaffold(body: CompanyReadOnlyBanner(status: 'SUSPENDED'))));
    expect(find.textContaining('suspended'), findsOneWidget);
  });
}
