import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:hrms_mobile/core/auth/permissions.dart';
import 'package:hrms_mobile/features/onboarding/data/onboarding_repository.dart';
import 'package:hrms_mobile/features/onboarding/data/public_onboarding_repository.dart' show OnboardingDocument;
import 'package:hrms_mobile/features/onboarding/presentation/onboarding_case_detail_screen.dart';
import 'package:hrms_mobile/features/onboarding/presentation/onboarding_cases_screen.dart' show onboardingRepositoryProvider;
import 'package:hrms_mobile/features/profile/data/employee_repository.dart';
import 'package:hrms_mobile/features/profile/presentation/profile_screen.dart' show employeeRepositoryProvider;

import 'support/fake_auth.dart';

OnboardingCaseDetail _detail(String status, [Map<String, dynamic> extra = const {}]) => OnboardingCaseDetail.fromJson({
      'id': 'case-1',
      'candidate_first_name': 'Asha',
      'candidate_last_name': 'Rao',
      'personal_email': 'asha@example.com',
      'status': status,
      'proposed_joining_date': '2026-11-01',
      'token_status': 'ACTIVE',
      'section_reviews': [
        {'section': 'bank_info', 'status': 'REJECTED', 'rejection_reason': 'Wrong IFSC'},
      ],
      'personal_info': {'first_name': 'Asha', 'pan_number_enc': 'ABCDE1234F'},
      'education_info': {
        'items': [
          {'qualification': 'B.Tech', 'institution_name': 'IIT'}
        ]
      },
      ...extra,
    });

class _FakeRepo implements OnboardingRepository {
  _FakeRepo(this.status, [this.extra = const {}]);
  final String status;
  final Map<String, dynamic> extra;
  final calls = <String>[];

  @override
  Future<OnboardingCaseDetail> getCase(String id) async => _detail(status, extra);

  @override
  Future<List<OnboardingDocument>> listCaseDocuments(String caseId) async => [
        OnboardingDocument(id: 'd-1', documentType: 'PAN', originalFilename: 'pan.pdf', sizeBytes: 2048, status: 'PENDING', downloadUrl: 'https://x/y'),
      ];

  @override
  Future<void> reviewSection(String caseId, String section, {required bool verified, String? reason}) async =>
      calls.add('section:$section:${verified ? 'verified' : 'rejected'}');

  @override
  Future<OnboardingDocument> reviewDocument(String caseId, String documentId, {required bool verified, String? reason}) async {
    calls.add('doc:$documentId:${verified ? 'verified' : 'rejected'}');
    return OnboardingDocument(id: documentId, documentType: 'PAN', originalFilename: 'pan.pdf', sizeBytes: 2048, status: 'VERIFIED');
  }

  @override
  Future<OnboardingCase> requestChanges(String caseId) async {
    calls.add('request-changes');
    return _detail(status);
  }

  @override
  dynamic noSuchMethod(Invocation invocation) => super.noSuchMethod(invocation);
}

class _FakeEmployees implements EmployeeRepository {
  final invited = <String>[];

  @override
  Future<({String email, bool emailSent, String? inviteUrl})> inviteEmployee(String employeeId) async {
    invited.add(employeeId);
    return (email: 'asha@acme.test', emailSent: false, inviteUrl: 'https://app.test/accept-invite/tok');
  }

  @override
  dynamic noSuchMethod(Invocation invocation) => super.noSuchMethod(invocation);
}

Future<void> _pump(WidgetTester tester, _FakeRepo repo, List<String> permissions, {_FakeEmployees? employees}) async {
  tester.view.physicalSize = const Size(800, 3000);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
  await tester.pumpWidget(ProviderScope(
    overrides: [
      onboardingRepositoryProvider.overrideWithValue(repo),
      employeeRepositoryProvider.overrideWithValue(employees ?? _FakeEmployees()),
      fakeAuth(permissions),
    ],
    child: MaterialApp(
      home: OnboardingCaseDetailScreen(
        caseSummary: OnboardingCase(id: 'case-1', candidateFirstName: 'Asha', personalEmail: 'asha@example.com', status: 'UNDER_REVIEW'),
      ),
    ),
  ));
  await tester.pumpAndSettle();
}

void main() {
  testWidgets('shows candidate data, section review state and documents', (tester) async {
    await _pump(tester, _FakeRepo('UNDER_REVIEW'), [onboardingReview]);
    expect(find.text('Asha'), findsWidgets);
    expect(find.text('ABCDE1234F'), findsOneWidget);
    expect(find.text('B.Tech'), findsOneWidget);
    expect(find.textContaining('Wrong IFSC'), findsOneWidget);
    expect(find.text('pan.pdf'), findsOneWidget);
  });

  testWidgets('a reviewer can verify a section and a document, and request changes after a rejection', (tester) async {
    final repo = _FakeRepo('UNDER_REVIEW');
    await _pump(tester, repo, [onboardingReview]);
    await tester.tap(find.text('Verify').first);
    await tester.pumpAndSettle();
    expect(repo.calls.single, startsWith('section:'));
    await tester.tap(find.text('Verify').last);
    await tester.pumpAndSettle();
    expect(repo.calls.last, 'doc:d-1:verified');
    await tester.tap(find.text('Request changes'));
    await tester.pumpAndSettle();
    expect(repo.calls.last, 'request-changes');
  });

  testWidgets('without the review permission there are no review buttons', (tester) async {
    await _pump(tester, _FakeRepo('UNDER_REVIEW'), const []);
    expect(find.text('Verify'), findsNothing);
    expect(find.text('Request changes'), findsNothing);
  });

  testWidgets('activate is offered for a verified case with the activate permission', (tester) async {
    await _pump(tester, _FakeRepo('VERIFIED'), [onboardingActivate]);
    expect(find.text('Activate employee'), findsOneWidget);
  });

  testWidgets('activate is hidden until the case is verified', (tester) async {
    await _pump(tester, _FakeRepo('UNDER_REVIEW'), [onboardingActivate]);
    expect(find.text('Activate employee'), findsNothing);
  });

  testWidgets("review progress counts verified items as web does, with the next step", (tester) async {
    await _pump(tester, _FakeRepo('UNDER_REVIEW', {
      'section_reviews': [
        {'section': 'personal_info', 'status': 'VERIFIED'},
        {'section': 'bank_info', 'status': 'REJECTED', 'rejection_reason': 'Wrong IFSC'},
      ],
    }), [onboardingReview]);
    expect(find.byKey(const Key('onboarding-review-progress')), findsOneWidget);
    expect(find.text('1/9'), findsOneWidget, reason: 'eight sections plus one document');
    expect(find.text('Sections: 1 of 8 verified, 1 rejected'), findsOneWidget);
    expect(find.text('Documents: 0 of 1 verified'), findsOneWidget);
    expect(find.textContaining('Review each section and document'), findsOneWidget);
  });

  testWidgets('face enrollment card follows the company requirement', (tester) async {
    await _pump(tester, _FakeRepo('ACTIVATED', {
      'employee_id': 'emp-1',
      'face_enrollment_required': true,
      'face_enrollment': {'required': true, 'state': 'PENDING_APPROVAL', 'requirement_met': false},
    }), [onboardingReview]);
    expect(find.byKey(const Key('onboarding-face-enrollment')), findsOneWidget);
    expect(find.textContaining('Status: Awaiting approval — onboarding is not complete'), findsOneWidget);
  });

  testWidgets('no face enrollment card when the company does not require it', (tester) async {
    await _pump(tester, _FakeRepo('UNDER_REVIEW'), [onboardingReview]);
    expect(find.byKey(const Key('onboarding-face-enrollment')), findsNothing);
  });

  testWidgets('an activated case can send the login link and shows it to copy', (tester) async {
    final employees = _FakeEmployees();
    await _pump(tester, _FakeRepo('ACTIVATED', {'employee_id': 'emp-1'}), [onboardingReview, employeeInvite], employees: employees);
    await tester.tap(find.text('Send login link'));
    await tester.pumpAndSettle();
    expect(employees.invited, ['emp-1']);
    expect(find.text('Login setup link'), findsOneWidget);
    expect(find.text('https://app.test/accept-invite/tok'), findsOneWidget);
  });

  testWidgets('no login link button without the invite permission', (tester) async {
    await _pump(tester, _FakeRepo('ACTIVATED', {'employee_id': 'emp-1'}), [onboardingReview]);
    expect(find.text('Send login link'), findsNothing);
  });
}
