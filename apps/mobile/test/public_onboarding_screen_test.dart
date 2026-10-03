import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:hrms_mobile/features/onboarding/data/public_onboarding_repository.dart';
import 'package:hrms_mobile/features/onboarding/presentation/public_onboarding_screen.dart';

PublicOnboardingCase _case({String status = 'INVITED', bool writable = true}) => PublicOnboardingCase(
      status: status,
      candidateFirstName: 'Asha',
      proposedJoiningDate: '2026-11-01',
      writable: writable,
      sections: {for (final n in PublicOnboardingCase.sectionNames) n: <String, dynamic>{}},
      reviews: const [],
    );

class _FakeRepo implements PublicOnboardingRepository {
  _FakeRepo(this.initial);
  final PublicOnboardingCase initial;
  final saved = <String, Map<String, dynamic>>{};

  @override
  Future<PublicOnboardingCase> getCase(String token) async => initial;

  @override
  Future<List<OnboardingDocument>> listDocuments(String token) async => const [];

  @override
  Future<PublicOnboardingCase> saveSection(String token, String section, Map<String, dynamic> payload) async {
    saved[section] = payload;
    return initial;
  }

  @override
  dynamic noSuchMethod(Invocation invocation) => super.noSuchMethod(invocation);
}

Future<void> _pump(WidgetTester tester, _FakeRepo repo) async {
  await tester.pumpWidget(ProviderScope(
    overrides: [publicOnboardingRepositoryProvider.overrideWithValue(repo)],
    child: const MaterialApp(home: PublicOnboardingScreen(token: 'tok')),
  ));
  await tester.pumpAndSettle();
}

void main() {
  testWidgets('welcome screen greets the candidate', (tester) async {
    await _pump(tester, _FakeRepo(_case()));
    expect(find.textContaining('Hi Asha'), findsOneWidget);
    expect(find.text('Get started'), findsOneWidget);
  });

  testWidgets('a non-writable case shows the inactive terminal screen', (tester) async {
    await _pump(tester, _FakeRepo(_case(status: 'EXPIRED', writable: false)));
    expect(find.text('This link is no longer active'), findsOneWidget);
  });

  testWidgets('a submitted case shows the thank-you screen', (tester) async {
    await _pump(tester, _FakeRepo(_case(status: 'SUBMITTED', writable: false)));
    expect(find.text('Thanks, Asha!'), findsOneWidget);
  });

  testWidgets('personal info blocks on a missing first name, then saves and advances', (tester) async {
    final repo = _FakeRepo(_case());
    await _pump(tester, repo);
    await tester.tap(find.text('Get started'));
    await tester.pumpAndSettle();
    expect(find.text('Personal Info'), findsWidgets);

    await tester.tap(find.text('Save & continue'));
    await tester.pumpAndSettle();
    expect(find.text('First name is required.'), findsOneWidget);
    expect(repo.saved, isEmpty);

    await tester.enterText(find.byType(TextField).first, 'Asha');
    await tester.tap(find.text('Save & continue'));
    await tester.pumpAndSettle();
    expect(repo.saved['personal_info']?['first_name'], 'Asha');
    expect(find.text('Address'), findsWidgets);
  });
}
