import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:hrms_mobile/core/api/api_error.dart';
import 'package:hrms_mobile/core/auth/permissions.dart';
import 'package:hrms_mobile/features/onboarding/data/onboarding_repository.dart';
import 'package:hrms_mobile/features/onboarding/data/public_onboarding_repository.dart' show OnboardingDocument;
import 'package:hrms_mobile/features/onboarding/domain/onboarding_invitation.dart';
import 'package:hrms_mobile/features/onboarding/presentation/invitation_composer_screen.dart';
import 'package:hrms_mobile/features/onboarding/presentation/onboarding_case_detail_screen.dart';
import 'package:hrms_mobile/features/onboarding/presentation/onboarding_cases_screen.dart';

import 'support/fake_api_client.dart';
import 'support/fake_auth.dart';

InvitationCompose _compose({List<InvitationTemplate> templates = _two, bool invitable = true, bool live = false}) => InvitationCompose(
      recipientEmail: 'asha@example.com',
      candidateName: 'Asha Rao',
      invitable: invitable,
      hasActiveLink: live,
      activeLinkExpiresAt: live ? '2026-11-20T00:00:00Z' : null,
      defaultSubject: 'Welcome',
      defaultBody: 'Hello {{candidate_name}} {{onboarding_url}}',
      subjectMaxLength: 200,
      bodyMaxLength: 5000,
      templates: templates,
    );

const _two = [
  InvitationTemplate(key: 'std', name: 'Standard', description: 'The usual welcome', subject: 'Welcome {{candidate_name}}', body: 'Std {{onboarding_url}}'),
  InvitationTemplate(key: 'short', name: 'Short', description: 'A brief note', subject: 'Join us', body: 'Short {{onboarding_url}}'),
];

class _Repo implements OnboardingRepository {
  _Repo({InvitationCompose? compose, this.status = 'DRAFT', this.messages = const [], this.sendError, this.cancelError, this.previewError, this.counts})
      : compose = compose ?? _compose();
  final InvitationCompose compose;
  final String status;
  final List<OnboardingMessage> messages;
  final Object? sendError;
  final Object? cancelError;
  final Object? previewError;
  final ({int total, Map<String, int> byStatus})? counts;
  final sent = <({String? subject, String? body, String? id})>[];
  final cancelled = <String?>[];
  final previews = <String>[];
  final listed = <String?>[];
  int messageLoads = 0;

  @override
  Future<InvitationCompose> getInvitationCompose(String caseId) async => compose;

  @override
  Future<Map<String, dynamic>> previewInvitation(String caseId, {required String subject, required String body}) async {
    previews.add(body);
    if (previewError != null) throw previewError!;
    return {'subject': subject.replaceAll('{{candidate_name}}', 'Asha'), 'editable_body': 'Dear Asha. $body'};
  }

  @override
  Future<Map<String, dynamic>> sendInvite(String caseId, {String? subject, String? body, String? sendRequestId}) async {
    sent.add((subject: subject, body: body, id: sendRequestId));
    if (sendError != null) throw sendError!;
    return {'invite_url': 'https://app.example/onboarding/tok', 'email_queued': true};
  }

  @override
  Future<OnboardingCaseDetail> getCase(String id) async => OnboardingCaseDetail.fromJson({'id': 'c-1', 'candidate_first_name': 'Asha', 'candidate_last_name': 'Rao', 'personal_email': 'asha@example.com', 'status': status, 'token_status': 'ACTIVE', 'section_reviews': const []});

  @override
  Future<List<OnboardingDocument>> listCaseDocuments(String caseId) async => const [];

  @override
  Future<List<OnboardingMessage>> listMessages(String caseId) async {
    messageLoads++;
    return messages;
  }

  @override
  Future<void> cancelCase(String caseId, {String? reason}) async {
    if (cancelError != null) throw cancelError!;
    cancelled.add(reason);
  }

  @override
  Future<List<OnboardingCase>> listCases({String? status}) async {
    listed.add(status);
    return [OnboardingCase(id: 'c-1', candidateFirstName: 'Asha', personalEmail: 'asha@example.com', status: status ?? 'INVITED')];
  }

  @override
  Future<({int total, Map<String, int> byStatus})> getStatusCounts() async {
    if (counts == null) throw ApiError(status: 500, code: 'X', message: 'x');
    return counts!;
  }

  @override
  dynamic noSuchMethod(Invocation invocation) => super.noSuchMethod(invocation);
}

Future<void> _pump(WidgetTester tester, _Repo repo, Widget child, {List<String> permissions = const [onboardingView, onboardingCreate, onboardingCancel]}) async {
  tester.view.physicalSize = const Size(700, 2000);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
  await tester.pumpWidget(ProviderScope(
    overrides: [onboardingRepositoryProvider.overrideWithValue(repo), fakeAuth(permissions)],
    child: MaterialApp(home: child),
  ));
  await tester.pumpAndSettle();
}

Widget _detail({bool composeOnOpen = false, String status = 'DRAFT'}) => OnboardingCaseDetailScreen(
      composeOnOpen: composeOnOpen,
      caseSummary: OnboardingCase(id: 'c-1', candidateFirstName: 'Asha', personalEmail: 'asha@example.com', status: status),
    );

OnboardingMessage _message(String status, {String by = 'u-1'}) => OnboardingMessage(id: 'm-1', recipientEmail: 'asha@example.com', subject: 'Welcome Asha', createdByUserId: by, createdAt: '2026-11-04T06:00:00Z', status: status);

void main() {
  group('message status wording', () {
    test('accepted is never called delivered', () {
      final info = describeMessageStatus('PROVIDER_ACCEPTED');
      expect(info.label, 'Accepted by mail provider');
      expect(info.description, contains('does not confirm it reached the inbox'));
      expect(info.needsResend, isFalse);
    });

    test('only a failed or unqueued email needs a new invitation', () {
      for (final s in ['QUEUED', 'SENDING', 'RETRYING', 'PROVIDER_ACCEPTED', 'UNKNOWN', 'SOMETHING_NEW']) {
        expect(describeMessageStatus(s).needsResend, isFalse, reason: s);
      }
      for (final s in ['FAILED', 'NOT_QUEUED']) {
        expect(describeMessageStatus(s).needsResend, isTrue, reason: s);
      }
    });

    test('a send id is a valid random UUID, new each session', () {
      final id = newSendRequestId();
      expect(id, matches(RegExp(r'^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$')));
      expect(newSendRequestId(), isNot(id));
    });
  });

  group('repository', () {
    test('a composed invitation carries its text and id; the default sends no body', () async {
      final api = FakeApiClient(objects: {'/onboarding-cases/c-1/send-invite': const {'invite_url': 'x'}});
      final repo = OnboardingRepository(api);
      await repo.sendInvite('c-1', subject: 'S', body: 'B', sendRequestId: 'id-1');
      expect(api.calls.last.body, {'subject': 'S', 'body': 'B', 'send_request_id': 'id-1'});
      await repo.sendInvite('c-1');
      expect(api.calls.last.body, isNull);
    });

    test('cancel sends the reason, and the list filter goes to the server', () async {
      final api = FakeApiClient(lists: const {'/onboarding-cases': []});
      final repo = OnboardingRepository(api);
      await repo.cancelCase('c-1', reason: 'Declined the offer');
      expect(api.calls.single.path, '/onboarding-cases/c-1/cancel');
      expect(api.calls.single.body, {'reason': 'Declined the offer'});
      await repo.listCases(status: 'VERIFIED');
      expect(api.listCalls.single.filters, {'status': 'VERIFIED'});
    });
  });

  group('composer', () {
    testWidgets('choose a template, then edit the text the server filled in, then send', (tester) async {
      final repo = _Repo();
      await _pump(tester, repo, const InvitationComposerScreen(caseId: 'c-1'));
      expect(find.text('Choose a template'), findsOneWidget);
      await tester.tap(find.text('Short'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Next'));
      await tester.pumpAndSettle();
      expect(repo.previews, ['Short {{onboarding_url}}']);
      expect(find.text('To: Asha Rao <asha@example.com>'), findsOneWidget);
      expect(repo.sent, isEmpty, reason: 'nothing is sent until asked');

      await tester.enterText(find.widgetWithText(TextField, 'Subject'), 'Join us, Asha');
      await tester.tap(find.text('Send invitation'));
      await tester.pumpAndSettle();
      final send = repo.sent.single;
      expect(send.subject, 'Join us, Asha');
      expect(send.body, 'Dear Asha. Short {{onboarding_url}}');
      expect(send.id, isNotNull);
    });

    testWidgets('with one template there is nothing to choose', (tester) async {
      final repo = _Repo(compose: _compose(templates: const []));
      await _pump(tester, repo, const InvitationComposerScreen(caseId: 'c-1'));
      expect(find.text('Review and send invitation'), findsOneWidget);
      expect(find.text('Next'), findsNothing);
    });

    testWidgets('a failed fill-in leaves the raw template to edit rather than stranding the user', (tester) async {
      final repo = _Repo(compose: _compose(templates: const []), previewError: ApiError(status: 500, code: 'X', message: 'Preview trouble'));
      await _pump(tester, repo, const InvitationComposerScreen(caseId: 'c-1'));
      expect(find.text('Preview trouble'), findsOneWidget);
      expect(find.text('Send invitation'), findsOneWidget);
    });

    testWidgets('warns that sending revokes a live link', (tester) async {
      await _pump(tester, _Repo(compose: _compose(templates: const [], live: true)), const InvitationComposerScreen(caseId: 'c-1'));
      expect(find.textContaining('new link and revokes the previous one'), findsOneWidget);
    });

    testWidgets('a retry after a failure reuses the same send id, so no second link is issued', (tester) async {
      final repo = _Repo(compose: _compose(templates: const []), sendError: ApiError(status: 0, code: 'REQUEST_TIMEOUT', message: 'Timed out'));
      await _pump(tester, repo, const InvitationComposerScreen(caseId: 'c-1'));
      await tester.tap(find.text('Send invitation'));
      await tester.pumpAndSettle();
      expect(find.text('Timed out'), findsOneWidget);
      await tester.tap(find.text('Send invitation'));
      await tester.pumpAndSettle();
      expect(repo.sent.length, 2);
      expect(repo.sent[0].id, repo.sent[1].id);
    });

    testWidgets('a case past inviting cannot send', (tester) async {
      await _pump(tester, _Repo(compose: _compose(templates: const [], invitable: false)), const InvitationComposerScreen(caseId: 'c-1'));
      expect(find.textContaining('no longer in a status'), findsOneWidget);
      expect(tester.widget<FilledButton>(find.widgetWithText(FilledButton, 'Send invitation')).onPressed, isNull);
    });
  });

  group('case detail', () {
    testWidgets('sending goes through the composer, shows the link, and refreshes the history', (tester) async {
      final repo = _Repo(compose: _compose(templates: const []));
      await _pump(tester, repo, _detail());
      final before = repo.messageLoads;
      await tester.tap(find.text('Send invite'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Send invitation'));
      await tester.pumpAndSettle();
      expect(repo.sent.single.subject, isNotNull);
      expect(find.text('https://app.example/onboarding/tok'), findsOneWidget);
      expect(find.textContaining('Invitation queued'), findsOneWidget);
      expect(repo.messageLoads, greaterThan(before));
    });

    testWidgets('a new case goes straight on to the invitation, saying nothing has been sent', (tester) async {
      final repo = _Repo(compose: _compose(templates: const []));
      await _pump(tester, repo, _detail(composeOnOpen: true));
      expect(find.textContaining('No email has been sent yet.'), findsOneWidget);
      expect(repo.sent, isEmpty);
    });

    testWidgets('history names the sender and offers a new invitation only when needed', (tester) async {
      await _pump(tester, _Repo(messages: [_message('FAILED')]), _detail());
      expect(find.text('Failed'), findsOneWidget);
      expect(find.textContaining('by you'), findsOneWidget);
      expect(find.text('Send new invitation'), findsOneWidget);
    });

    testWidgets('an accepted email needs nothing, and another user is not named', (tester) async {
      await _pump(tester, _Repo(messages: [_message('PROVIDER_ACCEPTED', by: 'u-2')]), _detail());
      expect(find.text('Accepted by mail provider'), findsOneWidget);
      expect(find.textContaining('by another HR user'), findsOneWidget);
      expect(find.text('Send new invitation'), findsNothing);
    });

    testWidgets('cancelling asks first, says what happens, and records the reason', (tester) async {
      final repo = _Repo();
      await _pump(tester, repo, _detail());
      await tester.tap(find.text('Cancel onboarding'));
      await tester.pumpAndSettle();
      expect(find.textContaining('Their onboarding link stops working immediately.'), findsOneWidget);
      expect(repo.cancelled, isEmpty);
      await tester.enterText(find.byType(TextField).last, 'Declined the offer');
      await tester.tap(find.widgetWithText(FilledButton, 'Cancel onboarding'));
      await tester.pumpAndSettle();
      expect(repo.cancelled.single, 'Declined the offer');
      expect(find.text('Onboarding cancelled.'), findsOneWidget);
    });

    testWidgets('Keep case changes nothing', (tester) async {
      final repo = _Repo();
      await _pump(tester, repo, _detail());
      await tester.tap(find.text('Cancel onboarding'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Keep case'));
      await tester.pumpAndSettle();
      expect(repo.cancelled, isEmpty);
    });

    testWidgets('a case that has moved on says so instead of failing silently', (tester) async {
      final repo = _Repo(cancelError: ApiError(status: 409, code: 'X', message: 'x'));
      await _pump(tester, repo, _detail());
      await tester.tap(find.text('Cancel onboarding'));
      await tester.pumpAndSettle();
      await tester.tap(find.widgetWithText(FilledButton, 'Cancel onboarding'));
      await tester.pumpAndSettle();
      expect(find.textContaining('can no longer be cancelled'), findsOneWidget);
    });

    testWidgets('cancel needs the permission and a status that allows it', (tester) async {
      await _pump(tester, _Repo(), _detail(), permissions: const [onboardingView, onboardingCreate]);
      expect(find.text('Cancel onboarding'), findsNothing);
    });

    testWidgets('an activated case cannot be cancelled', (tester) async {
      await _pump(tester, _Repo(status: 'ACTIVATED'), _detail(status: 'ACTIVATED'));
      expect(find.text('Cancel onboarding'), findsNothing);
    });
  });

  group('case list', () {
    testWidgets('tabs show the server counts and filter on the server', (tester) async {
      final repo = _Repo(counts: (total: 9, byStatus: const {'INVITED': 4}));
      await _pump(tester, repo, const OnboardingCasesScreen());
      expect(find.text('All cases (9)'), findsOneWidget);
      expect(find.text('Invited (4)'), findsOneWidget);
      expect(repo.listed.first, isNull);
      await tester.tap(find.text('Invited (4)'));
      await tester.pumpAndSettle();
      expect(repo.listed.last, 'INVITED');
    });

    testWidgets('the tabs still work if the counts cannot load', (tester) async {
      final repo = _Repo();
      await _pump(tester, repo, const OnboardingCasesScreen());
      await tester.tap(find.widgetWithText(ChoiceChip, 'Invited'));
      await tester.pumpAndSettle();
      expect(repo.listed.last, 'INVITED');
    });
  });

}
