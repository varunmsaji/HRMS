import 'package:dio/dio.dart';

import '../../../core/api/api_client.dart';

class SectionReview {
  SectionReview({required this.section, required this.status, this.rejectionReason});
  final String section;
  final String status;
  final String? rejectionReason;

  factory SectionReview.fromJson(Map<String, dynamic> json) => SectionReview(
        section: json['section'] as String,
        status: json['status'] as String,
        rejectionReason: json['rejection_reason'] as String?,
      );
}

/// `GET /public/onboarding/{token}` — mirrors `PublicOnboardingCaseRead`.
class PublicOnboardingCase {
  PublicOnboardingCase({
    required this.status,
    required this.candidateFirstName,
    required this.proposedJoiningDate,
    required this.writable,
    required this.sections,
    required this.reviews,
  });

  final String status;
  final String candidateFirstName;
  final String proposedJoiningDate;
  final bool writable;

  /// Section JSON blobs keyed by wire name (`personal_info`, …).
  final Map<String, Map<String, dynamic>> sections;
  final List<SectionReview> reviews;

  SectionReview? reviewFor(String section) {
    for (final r in reviews) {
      if (r.section == section) return r;
    }
    return null;
  }

  static const sectionNames = [
    'personal_info',
    'address_info',
    'emergency_contact',
    'bank_info',
    'statutory_info',
    'compensation_info',
    'previous_employment_info',
    'education_info',
    'nominee_info',
  ];

  factory PublicOnboardingCase.fromJson(Map<String, dynamic> json) => PublicOnboardingCase(
        status: json['status'] as String,
        candidateFirstName: json['candidate_first_name'] as String,
        proposedJoiningDate: json['proposed_joining_date'] as String,
        writable: json['writable'] as bool,
        sections: {
          for (final n in sectionNames) n: Map<String, dynamic>.from((json[n] as Map?) ?? const {}),
        },
        reviews: ((json['section_reviews'] as List?) ?? const [])
            .map((e) => SectionReview.fromJson(e as Map<String, dynamic>))
            .toList(),
      );
}

/// Mirrors `OnboardingDocumentRead`.
class OnboardingDocument {
  OnboardingDocument({
    required this.id,
    required this.documentType,
    required this.originalFilename,
    required this.sizeBytes,
    required this.status,
    this.rejectionReason,
    this.downloadUrl,
  });

  final String id;
  final String documentType;
  final String originalFilename;
  final int sizeBytes;
  final String status;
  final String? rejectionReason;

  /// Present only on the admin listing (`OnboardingDocumentWithUrlRead`).
  final String? downloadUrl;

  factory OnboardingDocument.fromJson(Map<String, dynamic> json) => OnboardingDocument(
        id: json['id'] as String,
        documentType: json['document_type'] as String,
        originalFilename: json['original_filename'] as String,
        sizeBytes: json['size_bytes'] as int,
        status: json['status'] as String,
        rejectionReason: json['rejection_reason'] as String?,
        downloadUrl: json['download_url'] as String?,
      );
}

/// The candidate-facing, token-authenticated wizard API (`/public/onboarding/{token}`) — no
/// session, so every call is `authenticated: false`.
class PublicOnboardingRepository {
  PublicOnboardingRepository(this._client);

  final ApiClient _client;

  String _base(String token) => '/public/onboarding/$token';

  Future<PublicOnboardingCase> getCase(String token) => _client.get(
        _base(token),
        authenticated: false,
        parse: (d) => PublicOnboardingCase.fromJson(d as Map<String, dynamic>),
      );

  Future<PublicOnboardingCase> saveSection(String token, String section, Map<String, dynamic> payload) => _client.patch(
        '${_base(token)}/sections/$section',
        body: payload,
        authenticated: false,
        parse: (d) => PublicOnboardingCase.fromJson(d as Map<String, dynamic>),
      );

  Future<PublicOnboardingCase> submit(String token) => _client.post(
        '${_base(token)}/submit',
        authenticated: false,
        parse: (d) => PublicOnboardingCase.fromJson(d as Map<String, dynamic>),
      );

  Future<List<OnboardingDocument>> listDocuments(String token) => _client
      .getList('${_base(token)}/documents', authenticated: false, parseItem: (d) => OnboardingDocument.fromJson(d as Map<String, dynamic>))
      .then((e) => e.data);

  Future<OnboardingDocument> uploadDocument(String token, {required String documentType, required String path, required String filename}) =>
      _client.postMultipart(
        '${_base(token)}/documents',
        authenticated: false,
        buildForm: () => FormData.fromMap({
          'document_type': documentType,
          'file': MultipartFile.fromFileSync(path, filename: filename),
        }),
        parse: (d) => OnboardingDocument.fromJson(d as Map<String, dynamic>),
      );

  Future<void> deleteDocument(String token, String documentId) =>
      _client.delete('${_base(token)}/documents/$documentId', authenticated: false, parse: (_) {});
}
