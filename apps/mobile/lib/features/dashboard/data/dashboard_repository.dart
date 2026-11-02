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
  CompanyProfileSummary({required this.id, required this.name, required this.status, this.logoUrl});

  final String id;
  final String name;
  final String status;

  /// `branding.logo_url` from `GET /companies/current`; null when the company has not set one.
  final String? logoUrl;

  factory CompanyProfileSummary.fromJson(Map<String, dynamic> json) => CompanyProfileSummary(
        id: json['id'] as String,
        name: json['name'] as String,
        status: json['status'] as String,
        logoUrl: _logoUrlOf(json),
      );

  static String? _logoUrlOf(Map<String, dynamic> json) {
    final branding = json['branding'];
    final raw = (branding is Map ? branding['logo_url'] : null) ?? json['logo_url'];
    final url = raw is String ? raw.trim() : '';
    return url.isEmpty ? null : url;
  }
}

/// `GET /dashboards/company/attendance-overview` — today's mutually exclusive buckets, as the
/// backend computed them. Only the fields the mobile dashboard shows.
class AttendanceOverviewSummary {
  AttendanceOverviewSummary({required this.total, required this.present, required this.onLeave, required this.absent, required this.notCheckedIn, required this.other});

  final int total;
  final int present;
  final int onLeave;
  final int absent;
  final int notCheckedIn;

  /// Everything else (on duty, remote, incomplete, weekly off, no record) so the buckets still sum to [total].
  final int other;

  factory AttendanceOverviewSummary.fromJson(Map<String, dynamic> json) {
    int n(String k) => (json[k] as num?)?.toInt() ?? 0;
    final total = n('total');
    final present = n('present'), onLeave = n('on_leave'), absent = n('absent'), notIn = n('not_checked_in');
    return AttendanceOverviewSummary(
      total: total,
      present: present,
      onLeave: onLeave,
      absent: absent,
      notCheckedIn: notIn,
      other: total - present - onLeave - absent - notIn,
    );
  }
}

class LeaveTypeStat {
  LeaveTypeStat({required this.name, required this.days});
  final String name;
  final num days;
}

class RecentActivity {
  RecentActivity({required this.title, this.subject, this.detail, required this.occurredAt});
  final String title;
  final String? subject;
  final String? detail;
  final String occurredAt;
}

/// `GET /dashboards/company/insights` — leave statistics and recent activity (growth and
/// birthdays are on the web dashboard only).
class CompanyInsights {
  CompanyInsights({required this.leaveTotalDays, required this.leaveByType, required this.recentActivities});

  final num leaveTotalDays;
  final List<LeaveTypeStat> leaveByType;
  final List<RecentActivity> recentActivities;

  factory CompanyInsights.fromJson(Map<String, dynamic> json) {
    final leave = json['leave_statistics'] as Map<String, dynamic>? ?? const {};
    return CompanyInsights(
      leaveTotalDays: leave['total_days'] as num? ?? 0,
      leaveByType: [
        for (final t in (leave['by_type'] as List? ?? const [])) LeaveTypeStat(name: (t as Map<String, dynamic>)['name'] as String, days: t['days'] as num? ?? 0),
      ],
      recentActivities: [
        for (final a in (json['recent_activities'] as List? ?? const []))
          RecentActivity(
            title: (a as Map<String, dynamic>)['title'] as String? ?? '',
            subject: a['subject'] as String?,
            detail: a['detail'] as String?,
            occurredAt: a['occurred_at'] as String? ?? '',
          ),
      ],
    );
  }
}

class DashboardRepository {
  DashboardRepository(this._client);

  final ApiClient _client;

  Future<CompanyDashboardSummary> getCompanyDashboard() => _client.get(
        '/dashboards/company',
        parse: (data) => CompanyDashboardSummary.fromJson(data as Map<String, dynamic>),
      );

  Future<AttendanceOverviewSummary> getAttendanceOverview() => _client.get(
        '/dashboards/company/attendance-overview',
        parse: (data) => AttendanceOverviewSummary.fromJson(data as Map<String, dynamic>),
      );

  Future<CompanyInsights> getInsights() => _client.get(
        '/dashboards/company/insights?growth_months=6&leave_scope=month',
        parse: (data) => CompanyInsights.fromJson(data as Map<String, dynamic>),
      );

  /// How many records of [path] match [filters] right now, from the list's own `pagination.total`
  /// (which already applies the caller's data scope).
  Future<int> countPending(String path, Map<String, dynamic> filters) async {
    final env = await _client.getList<int>(path, query: PageQuery(page: 1, perPage: 1), filters: filters, parseItem: (_) => 0);
    return env.pagination?.total ?? env.data.length;
  }

  Future<SubscriptionSummary> getSubscription() => _client.get(
        '/companies/current/subscription',
        parse: (data) => SubscriptionSummary.fromJson(data as Map<String, dynamic>),
      );

  Future<CompanyProfileSummary> getCompanyProfile() => _client.get(
        '/companies/current',
        parse: (data) => CompanyProfileSummary.fromJson(data as Map<String, dynamic>),
      );
}
