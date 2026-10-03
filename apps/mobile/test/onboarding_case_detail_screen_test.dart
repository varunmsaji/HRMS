import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:hrms_mobile/core/auth/permissions.dart';
import 'package:hrms_mobile/features/onboarding/data/onboarding_repository.dart';
import 'package:hrms_mobile/features/onboarding/data/public_onboarding_repository.dart' show OnboardingDocument;
import 'package:hrms_mobile/features/onboarding/presentation/onboarding_case_detail_screen.dart';
import 'package:hrms_mobile/features/onboarding/presentation/onboarding_cases_screen.dart' show onboardingRepositoryProvider;

import 'support/fake_auth.dart';

OnboardingCaseDetail _detail(String status) => OnboardingCaseDetail.fromJson({
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
    });

class _FakeRepo implements OnboardingRepository {
  _FakeRepo(this.status);
  final String status;
  final calls = <String>[];

  @override
  Future<OnboardingCaseDetail> getCase(String id) async => _detail(status);

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

Future<void> _pump(WidgetTester tester, _FakeRepo repo, List<String> permissions) async {
  tester.view.physicalSize = const Size(800, 3000);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
  await tester.pumpWidget(ProviderScope(
    overrides: [onboardingRepositoryProvider.overrideWithValue(repo), fakeAuth(permissions)],
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
}
