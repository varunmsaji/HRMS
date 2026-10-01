import '../../../core/api/api_client.dart';
import '../../../core/auth/auth_types.dart';

/// `GET /auth/companies/registration-config` — narrows the register screen's
/// timezone picker to what the server will actually accept (mirrors
/// `apps/web/src/lib/timezones.ts`).
class RegistrationConfig {
  RegistrationConfig({required this.allowedCompanyTimezones});

  final List<String> allowedCompanyTimezones;

  factory RegistrationConfig.fromJson(Map<String, dynamic> json) => RegistrationConfig(
        allowedCompanyTimezones: (json['allowed_company_timezones'] as List).cast<String>(),
      );
}

class CompanyRegistrationRequest {
  CompanyRegistrationRequest({
    required this.name,
    this.industryCode,
    this.countryCode,
    this.currency,
    this.timezone,
    required this.fyStartMonth,
    this.companySize,
    required this.adminFirstName,
    required this.adminLastName,
    required this.adminEmail,
    required this.adminPassword,
  });

  final String name;
  final String? industryCode;
  final String? countryCode;
  final String? currency;
  final String? timezone;
  final int fyStartMonth;
  final String? companySize;
  final String adminFirstName;
  final String adminLastName;
  final String adminEmail;
  final String adminPassword;

  Map<String, dynamic> toJson() => {
        'name': name,
        if (industryCode != null) 'industry_code': industryCode,
        if (countryCode != null) 'country_code': countryCode,
        if (currency != null) 'currency': currency,
        if (timezone != null) 'timezone': timezone,
        'fy_start_month': fyStartMonth,
        if (companySize != null) 'company_size': companySize,
        'admin_first_name': adminFirstName,
        'admin_last_name': adminLastName,
        'admin_email': adminEmail,
        'admin_password': adminPassword,
      };
}

/// `GET /public/account-invites/{token}` — shown before the accept form.
/// Mirrors `PublicAccountInviteRead` (account_invite/schemas.py).
class PublicAccountInvite {
  PublicAccountInvite({
    required this.email,
    required this.companyName,
    required this.expiresAt,
    required this.existingAccount,
  });

  final String email;
  final String companyName;
  final DateTime expiresAt;
  final bool existingAccount;

  factory PublicAccountInvite.fromJson(Map<String, dynamic> json) => PublicAccountInvite(
        email: json['email'] as String,
        companyName: json['company_name'] as String,
        expiresAt: DateTime.parse(json['expires_at'] as String),
        existingAccount: json['existing_account'] as bool,
      );
}

/// Every unauthenticated (and the handful of authenticated) `/auth/*` calls,
/// mirroring `apps/web/src/lib/auth/auth-context.tsx` + the `/companies/*` and
/// `/public/account-invites/*` routes it also drives from the login/register
/// screens. Kept as one repository (not split by web route) since they all
/// share the same "no session yet" shape.
class AuthRepository {
  AuthRepository(this._client);

  final ApiClient _client;

  Future<TokenResponseData> login({required String email, required String password}) => _client.post(
        '/auth/login',
        body: {'email': email, 'password': password},
        authenticated: false,
        parse: (data) => TokenResponseData.fromJson(data as Map<String, dynamic>),
      );

  Future<UserProfile> me() => _client.get(
        '/auth/me',
        parse: (data) => UserProfile.fromJson((data as Map<String, dynamic>)['user'] as Map<String, dynamic>),
      );

  Future<void> logout() => _client.post('/auth/logout', parse: (_) {});

  Future<void> forgotPassword(String email) => _client.post(
        '/auth/password/forgot',
        body: {'email': email},
        authenticated: false,
        parse: (_) {},
      );

  Future<void> resetPassword({required String token, required String password}) => _client.post(
        '/auth/password/reset',
        body: {'token': token, 'password': password},
        authenticated: false,
        parse: (_) {},
      );

  Future<void> verifyEmail(String token) => _client.post(
        '/auth/email/verify',
        body: {'token': token},
        authenticated: false,
        parse: (_) {},
      );

  Future<void> resendVerification(String email) => _client.post(
        '/auth/email/resend-verification',
        body: {'email': email},
        authenticated: false,
        parse: (_) {},
      );

  Future<RegistrationConfig> registrationConfig() => _client.get(
        '/companies/registration-config',
        authenticated: false,
        parse: (data) => RegistrationConfig.fromJson(data as Map<String, dynamic>),
      );

  Future<TokenResponseData> registerCompany(CompanyRegistrationRequest body) => _client.post(
        '/companies/register',
        body: body.toJson(),
        authenticated: false,
        parse: (data) => TokenResponseData.fromJson(data as Map<String, dynamic>),
      );

  Future<PublicAccountInvite> getInvite(String token) => _client.get(
        '/public/account-invites/$token',
        authenticated: false,
        parse: (data) => PublicAccountInvite.fromJson(data as Map<String, dynamic>),
      );

  Future<TokenResponseData> acceptInvite({
    required String token,
    required String password,
    String? firstName,
    String? lastName,
  }) =>
      _client.post(
        '/public/account-invites/$token/accept',
        body: {
          'password': password,
          if (firstName != null && firstName.isNotEmpty) 'first_name': firstName,
          if (lastName != null && lastName.isNotEmpty) 'last_name': lastName,
        },
        authenticated: false,
        parse: (data) => TokenResponseData.fromJson(data as Map<String, dynamic>),
      );
}
