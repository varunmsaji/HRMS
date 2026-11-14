import '../../../core/api/api_client.dart';
import '../../profile/data/employee_repository.dart' show Employee;

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
  AttendanceOverviewSummary({
    required this.total,
    required this.present,
    required this.onLeave,
    required this.absent,
    this.remoteWork = 0,
    this.onDuty = 0,
    this.expectedEmployees = 0,
    this.late = 0,
    this.halfDayLeave = 0,
  });

  final int total;
  final int present;
  final int onLeave;
  final int absent;
  final int remoteWork;
  final int onDuty;

  /// Employees the engine expects to work today (total minus not expected and no record).
  final int expectedEmployees;
  final int late;
  final int halfDayLeave;

  /// Everyone not in a named bucket, so the chart still sums to [total] — web `attendanceSegments`.
  int get others => [total - present - onLeave - absent - remoteWork - onDuty, 0].reduce((a, b) => a > b ? a : b);

  /// Nobody in any named bucket yet, so a chart would be one grey ring — web `nobodyRecorded`.
  bool get nobodyRecorded => present == 0 && onLeave == 0 && absent == 0 && remoteWork == 0 && onDuty == 0;

  factory AttendanceOverviewSummary.fromJson(Map<String, dynamic> json) {
    int n(String k) => (json[k] as num?)?.toInt() ?? 0;
    return AttendanceOverviewSummary(
      total: n('total'),
      present: n('present'),
      onLeave: n('on_leave'),
      absent: n('absent'),
      remoteWork: n('remote_work'),
      onDuty: n('on_duty'),
      expectedEmployees: n('expected_employees'),
      late: n('late'),
      halfDayLeave: n('half_day_leave'),
    );
  }
}

/// Change against an earlier figure — web `trendOf`: none when there is nothing to compare with.
({int pct, String label})? trendOf(int? current, int? previous, String label) {
  if (current == null || previous == null || previous <= 0) return null;
  return (pct: ((current - previous) / previous * 100).round(), label: label);
}

/// "+5% vs yesterday" / "-3% vs last month".
String trendText(({int pct, String label}) t) => '${t.pct >= 0 ? '+' : ''}${t.pct}% ${t.label}';

/// One waiting request on the dashboard's "Pending Approvals" panel — web `pendingRows`.
class PendingItem {
  PendingItem({required this.kind, required this.id, required this.employeeId, required this.at});

  /// 'leave', 'regularization' or 'overtime'.
  final String kind;
  final String id;
  final String employeeId;
  final String at;
}

/// A queue's total and its newest few rows.
class PendingQueue {
  PendingQueue({required this.total, required this.items});
  final int total;
  final List<PendingItem> items;
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

/// `GET /dashboards/company/insights` — the comparison figures, leave statistics and recent
/// activity (growth and birthdays are on the web dashboard only).
class CompanyInsights {
  CompanyInsights({
    required this.leaveTotalDays,
    required this.leaveByType,
    required this.recentActivities,
    this.headcountPrevMonthEnd,
    this.yesterdayPresent,
    this.yesterdayOnLeave,
    this.leavePeriodStart,
    this.leavePeriodEnd,
  });

  final int? headcountPrevMonthEnd;
  final int? yesterdayPresent;
  final int? yesterdayOnLeave;
  final String? leavePeriodStart;
  final String? leavePeriodEnd;
  final num leaveTotalDays;
  final List<LeaveTypeStat> leaveByType;
  final List<RecentActivity> recentActivities;

  factory CompanyInsights.fromJson(Map<String, dynamic> json) {
    final leave = json['leave_statistics'] as Map<String, dynamic>? ?? const {};
    final cmp = json['kpi_comparison'] as Map<String, dynamic>? ?? const {};
    return CompanyInsights(
      headcountPrevMonthEnd: (cmp['headcount_prev_month_end'] as num?)?.toInt(),
      yesterdayPresent: (cmp['yesterday_present'] as num?)?.toInt(),
      yesterdayOnLeave: (cmp['yesterday_on_leave'] as num?)?.toInt(),
      leavePeriodStart: leave['period_start'] as String?,
      leavePeriodEnd: leave['period_end'] as String?,
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

  /// Company-wide, or only [branchId]'s people (web's dashboard branch picker).
  Future<AttendanceOverviewSummary> getAttendanceOverview({String? branchId}) => _client.get(
        '/dashboards/company/attendance-overview${branchId == null ? '' : '?branch_id=${Uri.encodeQueryComponent(branchId)}'}',
        parse: (data) => AttendanceOverviewSummary.fromJson(data as Map<String, dynamic>),
      );

  /// [leaveScope] is 'month' or 'year', web's "This Month" / "This Year" on Leave Statistics.
  /// With [branchId], every figure counts only that branch's people.
  Future<CompanyInsights> getInsights({String leaveScope = 'month', String? branchId}) => _client.get(
        '/dashboards/company/insights?growth_months=6&leave_scope=$leaveScope'
        '${branchId == null ? '' : '&branch_id=${Uri.encodeQueryComponent(branchId)}'}',
        parse: (data) => CompanyInsights.fromJson(data as Map<String, dynamic>),
      );

  /// Active branches for the dashboard's branch picker, in the API's order.
  Future<List<({String id, String name})>> activeBranches() async {
    final env = await _client.getList<Map<String, dynamic>>(
      '/branches',
      query: PageQuery(page: 1, perPage: 100),
      parseItem: (item) => item as Map<String, dynamic>,
    );
    return [
      for (final b in env.data)
        if (b['is_active'] != false) (id: b['id'] as String, name: b['name'] as String? ?? ''),
    ];
  }

  /// How many records of [path] match [filters] right now, from the list's own `pagination.total`
  /// (which already applies the caller's data scope).
  Future<int> countPending(String path, Map<String, dynamic> filters) async {
    final env = await _client.getList<int>(path, query: PageQuery(page: 1, perPage: 1), filters: filters, parseItem: (_) => 0);
    return env.pagination?.total ?? env.data.length;
  }

  /// A queue's total plus its newest [size] rows (web `PENDING_PREVIEW_SIZE`); [kind] tags the rows,
  /// and [timeField] is when each was raised.
  Future<PendingQueue> pendingQueue(String kind, String path, Map<String, dynamic> filters, {String timeField = 'submitted_at', int size = 5}) async {
    final env = await _client.getList<Map<String, dynamic>>(path, query: PageQuery(page: 1, perPage: size), filters: filters, parseItem: (d) => d as Map<String, dynamic>);
    return PendingQueue(
      total: env.pagination?.total ?? env.data.length,
      items: [
        for (final r in env.data)
          PendingItem(kind: kind, id: r['id'] as String, employeeId: r['employee_id'] as String, at: (r[timeField] as String?) ?? ''),
      ],
    );
  }

  /// Display names for [ids], one `GET /employees/{id}` each; an id that can't be read is left out.
  Future<Map<String, String>> employeeNames(Iterable<String> ids) async {
    final out = <String, String>{};
    await Future.wait([
      for (final id in ids.toSet())
        _client.get('/employees/$id', parse: (d) => Employee.fromJson(d as Map<String, dynamic>)).then((e) {
          out[id] = e.fullName.isEmpty ? e.employeeCode : e.fullName;
        }).catchError((_) {}),
    ]);
    return out;
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
