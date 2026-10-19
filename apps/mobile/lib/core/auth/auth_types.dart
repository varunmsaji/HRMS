/// Mirrors `apps/web/src/lib/auth/types.ts`, which in turn mirrors
/// `apps/api/src/hrms/modules/identity/schemas.py`.
library;

class CompanySummary {
  CompanySummary({required this.id, required this.name, required this.isPrimary});

  final String id;
  final String name;
  final bool isPrimary;

  factory CompanySummary.fromJson(Map<String, dynamic> json) => CompanySummary(
        id: json['id'] as String,
        name: json['name'] as String,
        isPrimary: json['is_primary'] as bool,
      );
}

class TokenResponseData {
  TokenResponseData({
    required this.accessToken,
    required this.tokenType,
    required this.expiresInMinutes,
    required this.companyId,
    required this.companies,
  });

  final String accessToken;
  final String tokenType;
  final int expiresInMinutes;
  final String companyId;
  final List<CompanySummary> companies;

  factory TokenResponseData.fromJson(Map<String, dynamic> json) => TokenResponseData(
        accessToken: json['access_token'] as String,
        tokenType: json['token_type'] as String,
        expiresInMinutes: json['expires_in_minutes'] as int,
        companyId: json['company_id'] as String,
        companies: (json['companies'] as List)
            .map((e) => CompanySummary.fromJson(e as Map<String, dynamic>))
            .toList(),
      );
}

class UserProfile {
  UserProfile({
    required this.id,
    required this.email,
    required this.companyId,
    required this.employeeId,
    required this.permissions,
    required this.companyTimezone,
    this.companyStatus = 'ACTIVE',
  });

  final String id;
  final String? email;
  final String companyId;
  final String? employeeId;
  final List<String> permissions;

  /// TZ-07 — the resolved business timezone, always the company's timezone.
  /// Screens compute "business today" and render attendance timestamps against
  /// this rather than the device's local timezone.
  final String companyTimezone;

  /// Platform lifecycle status of the company. `PENDING_APPROVAL` and `SUSPENDED` are read-only:
  /// the API refuses writes with 403 `COMPANY_PENDING_APPROVAL` / `COMPANY_SUSPENDED`.
  final String companyStatus;

  factory UserProfile.fromJson(Map<String, dynamic> json) => UserProfile(
        id: json['id'] as String,
        email: json['email'] as String?,
        companyId: json['company_id'] as String,
        employeeId: json['employee_id'] as String?,
        permissions: (json['permissions'] as List).cast<String>(),
        companyTimezone: json['company_timezone'] as String,
        companyStatus: (json['company_status'] as String?) ?? 'ACTIVE',
      );
}
