import 'dart:math';

/// The HR-editable invitation (`apps/api/.../onboarding/invitation_schemas.py`), with the same
/// wording as the web's `lib/onboarding/invitation.ts`.
class InvitationTemplate {
  const InvitationTemplate({required this.key, required this.name, required this.description, required this.subject, required this.body});

  factory InvitationTemplate.fromJson(Map<String, dynamic> j) => InvitationTemplate(
        key: j['key'] as String,
        name: j['name'] as String,
        description: j['description'] as String,
        subject: j['subject'] as String,
        body: j['body'] as String,
      );

  final String key;
  final String name;
  final String description;
  final String subject;
  final String body;
}

class InvitationCompose {
  const InvitationCompose({
    required this.recipientEmail,
    required this.candidateName,
    required this.invitable,
    required this.hasActiveLink,
    required this.defaultSubject,
    required this.defaultBody,
    required this.subjectMaxLength,
    required this.bodyMaxLength,
    this.activeLinkExpiresAt,
    this.templates = const [],
  });

  factory InvitationCompose.fromJson(Map<String, dynamic> j) => InvitationCompose(
        recipientEmail: j['recipient_email'] as String,
        candidateName: j['candidate_name'] as String,
        invitable: j['invitable'] as bool,
        hasActiveLink: j['has_active_link'] as bool,
        activeLinkExpiresAt: j['active_link_expires_at'] as String?,
        defaultSubject: j['default_subject'] as String,
        defaultBody: j['default_body'] as String,
        subjectMaxLength: j['subject_max_length'] as int,
        bodyMaxLength: j['body_max_length'] as int,
        templates: [for (final t in (j['templates'] as List? ?? const [])) InvitationTemplate.fromJson(t as Map<String, dynamic>)],
      );

  final String recipientEmail;
  final String candidateName;

  /// False once the case is in a status a link can no longer be sent for.
  final bool invitable;

  /// A live link exists, and sending again revokes it.
  final bool hasActiveLink;
  final String? activeLinkExpiresAt;
  final String defaultSubject;
  final String defaultBody;
  final int subjectMaxLength;
  final int bodyMaxLength;
  final List<InvitationTemplate> templates;
}

class OnboardingMessage {
  const OnboardingMessage({required this.id, required this.recipientEmail, required this.subject, required this.createdByUserId, required this.createdAt, required this.status, this.lastAttemptAt, this.providerAcceptedAt});

  factory OnboardingMessage.fromJson(Map<String, dynamic> j) => OnboardingMessage(
        id: j['id'] as String,
        recipientEmail: j['recipient_email'] as String,
        subject: j['subject'] as String,
        createdByUserId: j['created_by_user_id'] as String,
        createdAt: j['created_at'] as String,
        status: j['status'] as String,
        lastAttemptAt: j['last_attempt_at'] as String?,
        providerAcceptedAt: j['provider_accepted_at'] as String?,
      );

  final String id;
  final String recipientEmail;
  final String subject;
  final String createdByUserId;
  final String createdAt;
  final String status;
  final String? lastAttemptAt;
  final String? providerAcceptedAt;
}

/// "Accepted by mail provider" is deliberately not "delivered": no delivery or bounce events are
/// processed, so inbox delivery is never claimed. [needsResend]: a new invitation is the only remedy.
({String label, String description, bool needsResend}) describeMessageStatus(String status) => switch (status) {
      'QUEUED' => (label: 'Queued', description: 'Waiting to be handed to the mail provider.', needsResend: false),
      'SENDING' => (label: 'Sending', description: 'Being handed to the mail provider now.', needsResend: false),
      'RETRYING' => (label: 'Retrying', description: 'A delivery attempt failed; it is being retried automatically with the same link.', needsResend: false),
      'PROVIDER_ACCEPTED' => (label: 'Accepted by mail provider', description: 'The provider accepted the message. This does not confirm it reached the inbox.', needsResend: false),
      'FAILED' => (label: 'Failed', description: 'The message could not be delivered. The link in it cannot be re-sent; send a new invitation.', needsResend: true),
      'NOT_QUEUED' => (label: 'Not queued', description: 'The email was not queued. The link was created but nothing was sent; send a new invitation.', needsResend: true),
      _ => (label: 'Unknown', description: 'Delivery status is unavailable.', needsResend: false),
    };

/// The server's status filters, as tabs. "Verified & ready" is VERIFIED, ready to activate.
const onboardingStatusTabs = <(String, String?)>[
  ('All cases', null),
  ('Invited', 'INVITED'),
  ('In progress', 'IN_PROGRESS'),
  ('Submitted', 'SUBMITTED'),
  ('Under review', 'UNDER_REVIEW'),
  ('Changes requested', 'CHANGES_REQUESTED'),
  ('Verified & ready', 'VERIFIED'),
];

/// Statuses the server accepts a cancel for (`ONBOARDING_CASE_CANCELLABLE_STATUSES`).
const onboardingCancellableStatuses = ['DRAFT', 'INVITED', 'IN_PROGRESS', 'SUBMITTED', 'UNDER_REVIEW', 'VERIFIED', 'CHANGES_REQUESTED'];

/// One id per compose session: if a send times out and is retried, the server recognises the
/// duplicate instead of issuing a second link.
String newSendRequestId() {
  final r = Random.secure();
  final b = List<int>.generate(16, (_) => r.nextInt(256));
  b[6] = (b[6] & 0x0f) | 0x40;
  b[8] = (b[8] & 0x3f) | 0x80;
  final h = b.map((x) => x.toRadixString(16).padLeft(2, '0')).join();
  return '${h.substring(0, 8)}-${h.substring(8, 12)}-${h.substring(12, 16)}-${h.substring(16, 20)}-${h.substring(20)}';
}
