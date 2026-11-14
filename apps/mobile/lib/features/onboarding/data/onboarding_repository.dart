import '../../../core/api/api_client.dart';
import 'public_onboarding_repository.dart' show OnboardingDocument;
import '../domain/onboarding_invitation.dart';

class OnboardingCase {
  OnboardingCase({
    required this.id,
    required this.candidateFirstName,
    this.candidateLastName,
    required this.personalEmail,
    required this.status,
    this.proposedJoiningDate,
  });
  final String id;
  final String candidateFirstName;
  final String? candidateLastName;
  final String personalEmail;
  final String status;
  final String? proposedJoiningDate;

  String get candidateName => [candidateFirstName, candidateLastName].where((s) => s != null && s.isNotEmpty).join(' ');

  factory OnboardingCase.fromJson(Map<String, dynamic> json) => OnboardingCase(
        id: json['id'] as String,
        candidateFirstName: json['candidate_first_name'] as String,
        candidateLastName: json['candidate_last_name'] as String?,
        personalEmail: json['personal_email'] as String,
        status: json['status'] as String,
        proposedJoiningDate: json['proposed_joining_date'] as String?,
      );
}

class OnboardingCaseDetail extends OnboardingCase {
  OnboardingCaseDetail({
    required super.id,
    required super.candidateFirstName,
    super.candidateLastName,
    required super.personalEmail,
    required super.status,
    super.proposedJoiningDate,
    required this.tokenStatus,
    required this.sectionReviews,
    this.tokenExpiresAt,
    this.employeeId,
    this.personalMobile,
    this.sections = const {},
    this.faceEnrollmentRequired = false,
    this.faceEnrollmentState,
    this.faceRequirementMet = false,
  });
  final String? tokenStatus;

  /// The company requires face enrollment as part of onboarding.
  final bool faceEnrollmentRequired;

  /// Present once activated: the employee's enrollment state (`NOT_ENROLLED`, `ENROLLED`, …).
  final String? faceEnrollmentState;

  /// Not required, or HR has approved the enrollment.
  final bool faceRequirementMet;
  final String? tokenExpiresAt;
  final String? employeeId;
  final String? personalMobile;
  final List<Map<String, dynamic>> sectionReviews;

  /// The eight reviewable section JSON blobs, keyed by wire name.
  final Map<String, Map<String, dynamic>> sections;

  String reviewStatus(String section) {
    for (final r in sectionReviews) {
      if (r['section'] == section) return r['status'] as String;
    }
    return 'PENDING';
  }

  String? rejectionReason(String section) {
    for (final r in sectionReviews) {
      if (r['section'] == section) return r['rejection_reason'] as String?;
    }
    return null;
  }

  factory OnboardingCaseDetail.fromJson(Map<String, dynamic> json) => OnboardingCaseDetail(
        id: json['id'] as String,
        candidateFirstName: json['candidate_first_name'] as String,
        candidateLastName: json['candidate_last_name'] as String?,
        personalEmail: json['personal_email'] as String,
        status: json['status'] as String,
        proposedJoiningDate: json['proposed_joining_date'] as String?,
        tokenStatus: json['token_status'] as String?,
        tokenExpiresAt: json['token_expires_at'] as String?,
        employeeId: json['employee_id'] as String?,
        personalMobile: json['personal_mobile'] as String?,
        faceEnrollmentRequired: json['face_enrollment_required'] == true,
        faceEnrollmentState: (json['face_enrollment'] as Map?)?['state'] as String?,
        faceRequirementMet: (json['face_enrollment'] as Map?)?['requirement_met'] == true,
        sectionReviews: (json['section_reviews'] as List? ?? []).cast<Map<String, dynamic>>(),
        sections: {
          for (final n in const [
            'personal_info',
            'address_info',
            'emergency_contact',
            'bank_info',
            'statutory_info',
            'previous_employment_info',
            'education_info',
            'nominee_info',
          ])
            n: Map<String, dynamic>.from((json[n] as Map?) ?? const {}),
        },
      );
}

class SetupStep {
  SetupStep({required this.code, required this.label, required this.isComplete});
  final String code;
  final String label;
  final bool isComplete;

  factory SetupStep.fromJson(Map<String, dynamic> json) =>
      SetupStep(code: json['code'] as String, label: json['label'] as String, isComplete: json['is_complete'] as bool);
}

class SetupProgress {
  SetupProgress({required this.status, this.currentStep, required this.steps});
  final String status;
  final String? currentStep;
  final List<SetupStep> steps;

  factory SetupProgress.fromJson(Map<String, dynamic> json) => SetupProgress(
        status: json['status'] as String,
        currentStep: json['current_step'] as String?,
        steps: (json['steps'] as List).map((s) => SetupStep.fromJson(s as Map<String, dynamic>)).toList(),
      );
}

/// One line of `GET /companies/current/setup-checklist`: what the company needs, worked out live
/// from its real data (unlike [SetupProgress], which records registration).
class SetupChecklistItem {
  SetupChecklistItem({required this.code, required this.label, required this.description, required this.required, required this.isComplete, required this.path});
  final String code;
  final String label;
  final String description;
  final bool required;
  final bool isComplete;
  final String path;

  factory SetupChecklistItem.fromJson(Map<String, dynamic> json) => SetupChecklistItem(
        code: json['code'] as String,
        label: json['label'] as String,
        description: json['description'] as String,
        required: json['required'] as bool,
        isComplete: json['is_complete'] as bool,
        path: json['path'] as String,
      );

  /// The web paths point at create pages (`/new`, `/setup`) that the app does not have; the list
  /// screen at the parent path is where the app adds one.
  String get appPath => path.replaceFirst(RegExp(r'/(new|setup)$'), '');
}

class SetupChecklist {
  SetupChecklist({required this.items, required this.requiredTotal, required this.requiredComplete, this.nextCode});
  final List<SetupChecklistItem> items;
  final int requiredTotal;
  final int requiredComplete;
  final String? nextCode;

  factory SetupChecklist.fromJson(Map<String, dynamic> json) => SetupChecklist(
        items: (json['items'] as List).map((i) => SetupChecklistItem.fromJson(i as Map<String, dynamic>)).toList(),
        requiredTotal: json['required_total'] as int,
        requiredComplete: json['required_complete'] as int,
        nextCode: json['next_code'] as String?,
      );
}

class UserSummary {
  UserSummary({required this.userId, this.email, this.firstName, this.lastName, required this.status, required this.roleCodes});
  final String userId;

  /// Null for a user without an email address (the backend allows it).
  final String? email;
  final String? firstName;
  final String? lastName;
  final String status;
  final List<String> roleCodes;

  String get emailLabel => email ?? 'No email';

  factory UserSummary.fromJson(Map<String, dynamic> json) => UserSummary(
        userId: json['user_id'] as String,
        email: json['email'] as String?,
        firstName: json['first_name'] as String?,
        lastName: json['last_name'] as String?,
        status: json['status'] as String,
        roleCodes: (json['role_codes'] as List).cast<String>(),
      );
}

/// Covers Onboarding Cases, Setup Checklist and Users & Roles — mirrors
/// `apps/api/src/hrms/modules/{onboarding,organisation,account_invite}/router.py`.
class OnboardingRepository {
  OnboardingRepository(this._client);
  final ApiClient _client;

  /// Every case, or those in [status], a page at a time.
  Future<List<OnboardingCase>> listCases({String? status}) async {
    final all = <OnboardingCase>[];
    for (var page = 1; page <= 20; page++) {
      final env = await _client.getList(
        '/onboarding-cases',
        query: PageQuery(page: page, perPage: 100),
        filters: {if (status != null) 'status': status},
        parseItem: (d) => OnboardingCase.fromJson(d as Map<String, dynamic>),
      );
      all.addAll(env.data);
      if (!(env.pagination?.hasNext ?? false)) break;
    }
    return all;
  }

  Future<({int total, Map<String, int> byStatus})> getStatusCounts() => _client.get(
        '/onboarding-cases/status-counts',
        parse: (d) {
          final m = d as Map<String, dynamic>;
          return (total: m['total'] as int, byStatus: (m['by_status'] as Map<String, dynamic>).cast<String, int>());
        },
      );
  Future<OnboardingCaseDetail> getCase(String id) => _client.get(
        '/onboarding-cases/$id',
        parse: (d) => OnboardingCaseDetail.fromJson(d as Map<String, dynamic>),
      );
  Future<OnboardingCase> createCase(Map<String, dynamic> body) => _client.post(
        '/onboarding-cases',
        body: body,
        parse: (d) => OnboardingCase.fromJson(d as Map<String, dynamic>),
      );
  /// With no [subject] and [body] the server sends its built-in invitation.
  Future<Map<String, dynamic>> sendInvite(String caseId, {String? subject, String? body, String? sendRequestId}) => _client.post(
        '/onboarding-cases/$caseId/send-invite',
        body: subject == null && body == null && sendRequestId == null
            ? null
            : {if (subject != null) 'subject': subject, if (body != null) 'body': body, if (sendRequestId != null) 'send_request_id': sendRequestId},
        parse: (d) => d as Map<String, dynamic>,
      );
  Future<InvitationCompose> getInvitationCompose(String caseId) => _client.get(
        '/onboarding-cases/$caseId/invitation/compose',
        parse: (d) => InvitationCompose.fromJson(d as Map<String, dynamic>),
      );
  Future<Map<String, dynamic>> previewInvitation(String caseId, {required String subject, required String body}) => _client.post(
        '/onboarding-cases/$caseId/invitation/preview',
        body: {'subject': subject, 'body': body},
        parse: (d) => d as Map<String, dynamic>,
      );
  Future<List<OnboardingMessage>> listMessages(String caseId) => _client.get(
        '/onboarding-cases/$caseId/messages',
        parse: (d) => [for (final m in d as List) OnboardingMessage.fromJson(m as Map<String, dynamic>)],
      );
  Future<void> cancelCase(String caseId, {String? reason}) => _client.post(
        '/onboarding-cases/$caseId/cancel',
        body: {'reason': reason},
        parse: (_) {},
      );
  Future<List<OnboardingDocument>> listCaseDocuments(String caseId) => _client
      .getList('/onboarding-cases/$caseId/documents', parseItem: (d) => OnboardingDocument.fromJson(d as Map<String, dynamic>))
      .then((e) => e.data);
  Future<void> reviewSection(String caseId, String section, {required bool verified, String? reason}) => _client.post(
        '/onboarding-cases/$caseId/sections/$section/review',
        body: {'status': verified ? 'VERIFIED' : 'REJECTED', if (!verified) 'rejection_reason': reason},
        parse: (_) {},
      );
  Future<OnboardingDocument> reviewDocument(String caseId, String documentId, {required bool verified, String? reason}) => _client.post(
        '/onboarding-cases/$caseId/documents/$documentId/review',
        body: {'status': verified ? 'VERIFIED' : 'REJECTED', if (!verified) 'rejection_reason': reason},
        parse: (d) => OnboardingDocument.fromJson(d as Map<String, dynamic>),
      );
  Future<OnboardingCase> requestChanges(String caseId) => _client.post(
        '/onboarding-cases/$caseId/request-changes',
        parse: (d) => OnboardingCase.fromJson(d as Map<String, dynamic>),
      );
  Future<OnboardingCase> activate(String caseId) => _client.post(
        '/onboarding-cases/$caseId/activate',
        parse: (d) => OnboardingCase.fromJson(d as Map<String, dynamic>),
      );

  Future<SetupProgress> getSetupProgress() => _client.get(
        '/companies/current/setup-progress',
        parse: (d) => SetupProgress.fromJson(d as Map<String, dynamic>),
      );

  Future<SetupChecklist> getSetupChecklist() => _client.get(
        '/companies/current/setup-checklist',
        parse: (d) => SetupChecklist.fromJson(d as Map<String, dynamic>),
      );

  Future<List<UserSummary>> listUsers() =>
      _client.getList('/users', parseItem: (d) => UserSummary.fromJson(d as Map<String, dynamic>)).then((e) => e.data);
  Future<Map<String, dynamic>> inviteUser({required String email, required String roleCode}) => _client.post(
        '/users/invite',
        body: {'email': email, 'role_code': roleCode},
        parse: (d) => d as Map<String, dynamic>,
      );
  Future<void> updateUserRoles(String userId, List<String> roleCodes) => _client.patch(
        '/users/$userId/roles',
        body: {'role_codes': roleCodes},
        parse: (_) {},
      );
}
