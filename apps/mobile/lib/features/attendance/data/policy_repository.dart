import '../../../core/api/api_client.dart';

/// A policy identity (name/code) shared by Attendance/Overtime/
/// Regularization Policies (and Leave Policies) — each has its own
/// versioned config attached separately.
class PolicyIdentity {
  PolicyIdentity({required this.id, required this.name, this.code, required this.isActive, required this.version});

  final String id;
  final String name;
  final String? code;
  final bool isActive;
  final int version;

  factory PolicyIdentity.fromJson(Map<String, dynamic> json) => PolicyIdentity(
        id: json['id'] as String,
        name: json['name'] as String,
        code: json['code'] as String?,
        isActive: json['is_active'] as bool,
        version: json['version'] as int,
      );
}

/// A policy version — the actual rule config. Kept as a raw JSON map since
/// each policy kind's version schema has 15-30 fields; the detail screen
/// renders whatever keys are present rather than a fixed Dart model per kind.
class PolicyVersion {
  PolicyVersion({
    required this.id,
    required this.status,
    required this.versionNumber,
    this.effectiveFrom,
    this.effectiveTo,
    required this.raw,
  });

  final String id;
  final String status;
  final int versionNumber;
  final String? effectiveFrom;
  final String? effectiveTo;
  final Map<String, dynamic> raw;

  bool get isDraft => status == 'DRAFT';

  factory PolicyVersion.fromJson(Map<String, dynamic> json) => PolicyVersion(
        id: json['id'] as String,
        status: json['status'] as String,
        versionNumber: json['version'] as int,
        effectiveFrom: json['effective_from'] as String?,
        effectiveTo: json['effective_to'] as String?,
        raw: json,
      );
}

/// One repository per policy kind (Attendance/Overtime/Regularization),
/// sharing this same identity+version shape and route pattern
/// (`/{basePath}`, `/{basePath}/{id}/versions`, `/versions/{id}/publish`).
class PolicyRepository {
  PolicyRepository(this._client, this.basePath);

  final ApiClient _client;
  final String basePath;

  Future<List<PolicyIdentity>> listPolicies() =>
      _client.getList('/$basePath', parseItem: (d) => PolicyIdentity.fromJson(d as Map<String, dynamic>)).then((e) => e.data);

  Future<PolicyIdentity> createPolicy({required String name, String? code}) => _client.post(
        '/$basePath',
        body: {'name': name, if (code != null && code.isNotEmpty) 'code': code},
        parse: (data) => PolicyIdentity.fromJson(data as Map<String, dynamic>),
      );

  Future<List<PolicyVersion>> listVersions(String policyId) => _client
      .getList('/$basePath/$policyId/versions', parseItem: (d) => PolicyVersion.fromJson(d as Map<String, dynamic>))
      .then((e) => e.data);

  Future<PolicyVersion> createVersion(String policyId, Map<String, dynamic> body) => _client.post(
        '/$basePath/$policyId/versions',
        body: body,
        parse: (data) => PolicyVersion.fromJson(data as Map<String, dynamic>),
      );

  Future<PolicyVersion> publishVersion(String policyId, String versionId, {required String ifMatch, String? publishReason}) =>
      _client.post(
        '/$basePath/$policyId/versions/$versionId/publish',
        ifMatch: ifMatch,
        body: {if (publishReason != null && publishReason.isNotEmpty) 'publish_reason': publishReason},
        parse: (data) => PolicyVersion.fromJson(data as Map<String, dynamic>),
      );

  Future<void> discardVersion(String policyId, String versionId, {required String ifMatch}) => _client.delete(
        '/$basePath/$policyId/versions/$versionId',
        ifMatch: ifMatch,
        parse: (_) {},
      );
}
