import '../../../core/api/api_client.dart';

class DashboardSetupProgress {
  DashboardSetupProgress({required this.status, required this.stepsCompleted, required this.stepsTotal});

  final String status;
  final int stepsCompleted;
  final int stepsTotal;

  bool get isComplete => status == 'COMPLETE';

  factory DashboardSetupProgress.fromJson(Map<String, dynamic> json) => DashboardSetupProgress(
        status: json['status'] as String,
        stepsCompleted: json['steps_completed'] as int,
        stepsTotal: json['steps_total'] as int,
      );
}

class DashboardSubscription {
  DashboardSubscription({required this.planCode, required this.status, this.trialEndsAt});

  final String planCode;
  final String status;
  final String? trialEndsAt;

  factory DashboardSubscription.fromJson(Map<String, dynamic> json) => DashboardSubscription(
        planCode: json['plan_code'] as String,
        status: json['status'] as String,
        trialEndsAt: json['trial_ends_at'] as String?,
      );
}

/// `GET /dashboards/company` — mirrors `CompanyDashboardSummary`
/// (organisation/schemas.py). Sibling counts (`branch_count`, …) stay `null`
/// until those modules ship; render as "—", never a fabricated 0.
class CompanyDashboardSummary {
  CompanyDashboardSummary({
    required this.setupProgress,
    this.subscription,
    this.branchCount,
    this.departmentCount,
    this.employeeCount,
  });

  final DashboardSetupProgress setupProgress;
  final DashboardSubscription? subscription;
  final int? branchCount;
  final int? departmentCount;
  final int? employeeCount;

  factory CompanyDashboardSummary.fromJson(Map<String, dynamic> json) => CompanyDashboardSummary(
        setupProgress: DashboardSetupProgress.fromJson(json['setup_progress'] as Map<String, dynamic>),
        subscription:
            json['subscription'] == null ? null : DashboardSubscription.fromJson(json['subscription'] as Map<String, dynamic>),
        branchCount: json['branch_count'] as int?,
        departmentCount: json['department_count'] as int?,
        employeeCount: json['employee_count'] as int?,
      );
}

class SubscriptionFeature {
  SubscriptionFeature({required this.code, required this.isEnabled, required this.source, this.limitValue});

  final String code;
  final bool isEnabled;
  final String source;
  final int? limitValue;

  factory SubscriptionFeature.fromJson(Map<String, dynamic> json) => SubscriptionFeature(
        code: json['code'] as String,
        isEnabled: json['is_enabled'] as bool,
        source: json['source'] as String,
        limitValue: json['limit_value'] as int?,
      );
}

/// `GET /companies/current/subscription`.
class SubscriptionSummary {
  SubscriptionSummary({
    required this.planCode,
    required this.planName,
    required this.status,
    this.trialEndsAt,
    this.seatLimit,
    required this.features,
  });

  final String planCode;
  final String planName;
  final String status;
  final String? trialEndsAt;
  final int? seatLimit;
  final List<SubscriptionFeature> features;

  factory SubscriptionSummary.fromJson(Map<String, dynamic> json) => SubscriptionSummary(
        planCode: (json['plan'] as Map<String, dynamic>)['code'] as String,
        planName: (json['plan'] as Map<String, dynamic>)['name'] as String,
        status: json['status'] as String,
        trialEndsAt: json['trial_ends_at'] as String?,
        seatLimit: json['seat_limit'] as int?,
        features: (json['features'] as List)
            .map((f) => SubscriptionFeature.fromJson(f as Map<String, dynamic>))
            .toList(),
      );
}

/// `GET /companies/current` — only the fields the Dashboard's "Company" card
/// actually shows (id, name, status); `CompanyProfileRead` carries many more
/// that don't have a mobile screen yet.
class CompanyProfileSummary {
  CompanyProfileSummary({required this.id, required this.name, required this.status});

  final String id;
  final String name;
  final String status;

  factory CompanyProfileSummary.fromJson(Map<String, dynamic> json) => CompanyProfileSummary(
        id: json['id'] as String,
        name: json['name'] as String,
        status: json['status'] as String,
      );
}

class DashboardRepository {
  DashboardRepository(this._client);

  final ApiClient _client;

  Future<CompanyDashboardSummary> getCompanyDashboard() => _client.get(
        '/dashboards/company',
        parse: (data) => CompanyDashboardSummary.fromJson(data as Map<String, dynamic>),
      );

  Future<SubscriptionSummary> getSubscription() => _client.get(
        '/companies/current/subscription',
        parse: (data) => SubscriptionSummary.fromJson(data as Map<String, dynamic>),
      );

  Future<CompanyProfileSummary> getCompanyProfile() => _client.get(
        '/companies/current',
        parse: (data) => CompanyProfileSummary.fromJson(data as Map<String, dynamic>),
      );
}
