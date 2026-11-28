import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../core/api/api_error.dart';
import '../../../core/auth/permissions.dart';
import '../../../core/nav/nav_entries.dart' show menuAllows;
import '../../../core/providers.dart';
import '../../../core/theme/app_colors.dart';
import '../../../core/theme/app_theme.dart';
import '../../../core/theme/employee_tokens.dart';
import '../../../core/time.dart' show relativeTime;
import '../../../core/widgets/dashboard_kit.dart';
import '../../../core/widgets/ui.dart';
import '../../../features/shell/more_action.dart';
import '../../auth/state/auth_controller.dart';
import '../data/dashboard_repository.dart';
import '../../../core/diagnostics/app_diagnostics.dart';

final dashboardRepositoryProvider = Provider<DashboardRepository>(
  (ref) => DashboardRepository(ref.watch(apiClientProvider)),
);

const _leaveApprove = 'LEAVE.APPLICATION_APPROVE';
const _regularizationApprove = 'ATTENDANCE.REGULARIZATION_APPROVE';
const _overtimeApprove = 'ATTENDANCE.OVERTIME_APPROVE';

String _longDate() {
  const wd = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'];
  const mo = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  final d = DateTime.now();
  return '${wd[d.weekday - 1]}, ${d.day} ${mo[d.month - 1]} ${d.year}';
}

/// Onboarding cases waiting on HR's review (web `ONBOARDING_HR_STATUSES`). Cases waiting on the
/// candidate (invited, in progress, changes requested) are not a decision for HR, so unlike web they
/// are not counted (audit MOB-UX-035).
const _onboardingHrStatuses = ['SUBMITTED', 'UNDER_REVIEW'];

/// Pending approvals by queue — web `usePendingApprovals`; a queue the viewer can't approve (or that
/// fails) is null and omitted.
class _Pending {
  const _Pending({this.leave, this.attendance, this.overtime, this.onboardingHr, this.failed = false});
  final PendingQueue? leave;
  final PendingQueue? attendance;
  final PendingQueue? overtime;
  final int? onboardingHr;

  /// A queue the viewer may approve could not be read: the total is then a lower bound.
  final bool failed;
  int get total => (leave?.total ?? 0) + (attendance?.total ?? 0) + (overtime?.total ?? 0) + (onboardingHr ?? 0);
  bool get any => leave != null || attendance != null || overtime != null || onboardingHr != null || failed;

  /// Every part of [total], so the tile's figure and its hint add up.
  String get breakdown => [
        if (leave != null) '${leave!.total} Leave',
        if (attendance != null) '${attendance!.total} Corrections',
        if (overtime != null) '${overtime!.total} Overtime',
        if (onboardingHr != null) '$onboardingHr Onboarding',
      ].join(' · ');

  /// The four newest waiting requests across leave, regularization and overtime — web `pendingRows`.
  List<PendingItem> get newest {
    final all = [...?leave?.items, ...?attendance?.items, ...?overtime?.items]..sort((a, b) => b.at.compareTo(a.at));
    return all.take(4).toList();
  }
}

/// Web's pending row titles and the queue each opens.
const _pendingTitle = {'leave': 'Leave request', 'regularization': 'Attendance correction', 'overtime': 'Overtime'};
const _pendingRoute = {'leave': '/app/leave-applications', 'regularization': '/app/regularizations', 'overtime': '/app/overtime'};
const _pendingIcon = {'leave': Icons.event_busy_outlined, 'regularization': Icons.schedule_outlined, 'overtime': Icons.more_time_outlined};

/// "01 Oct 2026 – 31 Oct 2026" — web `periodLabel`.
String _periodLabel(String start, String end) {
  const mo = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  String f(String iso) {
    final p = iso.split('-');
    return p.length < 3 ? iso : '${p[2]} ${mo[int.parse(p[1]) - 1]} ${p[0]}';
  }

  return '${f(start)} – ${f(end)}';
}

/// The company dashboard on mobile: the web dashboard's figures in one column. Growth,
/// birthdays and the department table stay web-only (they need the width); every figure shown is
/// the backend's, and a block whose source the viewer can't read is left out, never shown as 0.
class DashboardScreen extends ConsumerStatefulWidget {
  const DashboardScreen({super.key});

  @override
  ConsumerState<DashboardScreen> createState() => _DashboardScreenState();
}

class _DashboardScreenState extends ConsumerState<DashboardScreen> {
  bool _loading = true;
  CompanyDashboardSummary? _dashboard;
  CompanyProfileSummary? _profile;
  AttendanceOverviewSummary? _overview;
  CompanyInsights? _insights;
  _Pending _pending = const _Pending();
  Map<String, String> _names = const {};

  /// Web's Leave Statistics switch: 'month' or 'year'.
  String _leaveScope = 'month';

  /// Web's branch picker: null = all branches. Narrows the attendance overview and the insights.
  String? _branchId;
  List<({String id, String name})> _branches = const [];
  bool _insightsLoading = false;
  ApiError? _error;

  /// Blocks the viewer may see whose read failed (not refused): each shows "Couldn't load" with a
  /// retry instead of silently disappearing (audit MOB-UX-033).
  Set<String> _failed = const {};

  @override
  void initState() {
    super.initState();
    _load();
  }

  /// Each resource is fetched independently and concurrently. A 404 ("not available for this
  /// company") resolves to null data; only the core dashboard/profile reads can fail the page.
  /// The extra blocks (attendance, insights, approvals) fail silently into omission.
  Future<void> _load() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    final repository = ref.read(dashboardRepositoryProvider);
    final permissions = ref.read(authControllerProvider).user?.permissions ?? const <String>[];

    Future<({T? data, ApiError? error})> fetch<T>(Future<T> Function() call) async {
      try {
        return (data: await call(), error: null);
      } on ApiError catch (error) {
        return (data: null, error: error.status == 404 ? null : error);
      } catch (_) {
        return (data: null, error: ApiError(status: 0, code: 'UNKNOWN_ERROR', message: 'Something went wrong.'));
      }
    }

    Future<T?> quiet<T>(Future<T> Function() call) async {
      try {
        return await call();
      } catch (_) {
        return null;
      }
    }

    // Like [quiet], but a failure other than "not allowed" or "not available" is remembered under
    // [block], so the panel can say it couldn't load rather than vanish.
    final failed = <String>{};
    Future<T?> soft<T>(String block, Future<T> Function() call) async {
      try {
        return await call();
      } on ApiError catch (e) {
        if (e.status != 403 && e.status != 404) failed.add(block);
        return null;
      } catch (_) {
        failed.add(block);
        return null;
      }
    }

    Future<PendingQueue?> queue(bool allowed, String kind, String path, Map<String, dynamic> filters, {String timeField = 'submitted_at'}) async =>
        allowed ? soft('pending', () => repository.pendingQueue(kind, path, filters, timeField: timeField)) : null;

    // One onboarding bucket spans several statuses and the list filters on one, so the totals add.
    final onboarding = permissions.contains(onboardingReview) && permissions.contains(onboardingView);
    Future<int?> onboardingCount(List<String> statuses) async {
      if (!onboarding) return null;
      final parts = await Future.wait([for (final s in statuses) soft('pending', () => repository.countPending('/onboarding-cases', {'status': s}))]);
      return parts.every((p) => p == null) ? null : parts.fold<int>(0, (sum, p) => sum + (p ?? 0));
    }

    final branchId = _branchId;
    // Best-effort, as on web: without it the picker is simply not shown. Started alongside the
    // rest (a record `.wait` takes at most nine futures).
    final branchesFuture = quiet(repository.activeBranches);
    final (dashboard, profile, overview, insights, leave, attendance, overtime, onboardingHr) = await (
      fetch(repository.getCompanyDashboard),
      fetch(repository.getCompanyProfile),
      permissions.contains(attendanceView) ? soft('attendance', () => repository.getAttendanceOverview(branchId: branchId)) : Future<AttendanceOverviewSummary?>.value(null),
      soft('insights', () => repository.getInsights(leaveScope: _leaveScope, branchId: branchId)),
      queue(permissions.contains(_leaveApprove), 'leave', '/leave-applications', {'application_status': 'SUBMITTED'}),
      queue(permissions.contains(_regularizationApprove), 'regularization', '/regularizations', {'request_status': 'SUBMITTED'}),
      queue(permissions.contains(_overtimeApprove), 'overtime', '/overtime', {'record_status': 'PENDING'}, timeField: 'created_at'),
      onboardingCount(_onboardingHrStatuses),
    ).wait;

    final branches = await branchesFuture;
    if (!mounted) return;
    final pending = _Pending(leave: leave, attendance: attendance, overtime: overtime, onboardingHr: onboardingHr, failed: failed.contains('pending'));
    setState(() {
      _failed = failed;
      _dashboard = dashboard.data;
      _profile = profile.data;
      _overview = overview;
      _insights = insights;
      _branches = branches ?? const [];
      _pending = pending;
      _error = dashboard.error ?? profile.error;
      _loading = false;
    });
    final names = await quiet(() => repository.employeeNames(pending.newest.map((i) => i.employeeId)));
    if (mounted && names != null) setState(() => _names = names);
  }

  Future<void> _setLeaveScope(String scope) async {
    if (scope == _leaveScope) return;
    setState(() {
      _leaveScope = scope;
      _insightsLoading = true;
    });
    CompanyInsights? insights;
    try {
      insights = await ref.read(dashboardRepositoryProvider).getInsights(leaveScope: scope, branchId: _branchId);
    } catch (e, s) {
      // Keep the figures already shown; the switch shows the period they cover.
      AppDiagnostics.instance.recordHandled(e, s);
    }
    if (!mounted || scope != _leaveScope) return;
    setState(() {
      if (insights != null) _insights = insights;
      _insightsLoading = false;
    });
  }

  /// Re-reads only what the branch narrows (attendance overview and insights), as web does.
  Future<void> _setBranch(String? branchId) async {
    if (branchId == _branchId) return;
    setState(() {
      _branchId = branchId;
      _insightsLoading = true;
    });
    final repository = ref.read(dashboardRepositoryProvider);
    final canAttendance = ref.read(authControllerProvider).user?.permissions.contains(attendanceView) ?? false;
    Future<T?> quiet<T>(Future<T> Function() call) async {
      try {
        return await call();
      } catch (_) {
        return null;
      }
    }

    final (overview, insights) = await (
      canAttendance ? quiet(() => repository.getAttendanceOverview(branchId: branchId)) : Future<AttendanceOverviewSummary?>.value(null),
      quiet(() => repository.getInsights(leaveScope: _leaveScope, branchId: branchId)),
    ).wait;
    if (!mounted || branchId != _branchId) return;
    setState(() {
      // A failed read keeps nothing stale for the new branch: it is omitted, like on first load.
      _overview = overview;
      _insights = insights;
      _insightsLoading = false;
    });
  }

  @override
  Widget build(BuildContext context) {
    final hasPermission = ref.watch(authControllerProvider).user?.permissions.contains(dashboardCompanyView) ?? false;

    if (!hasPermission) {
      return const _DashboardScaffold(
        child: StateMessage(
          icon: Icons.lock_outline_rounded,
          tone: Tone.warning,
          title: 'No access',
          message: 'You do not have permission to view the company dashboard.',
        ),
      );
    }

    if (_loading) {
      return const _DashboardScaffold(child: ListSkeleton(count: 4));
    }

    if (_error != null) {
      final forbidden = _error!.status == 403;
      return _DashboardScaffold(
        child: StateMessage(
          icon: forbidden ? Icons.lock_outline_rounded : Icons.cloud_off_rounded,
          tone: forbidden ? Tone.warning : Tone.danger,
          title: forbidden ? 'No access' : 'Couldn\'t load the dashboard',
          message: forbidden ? 'You do not have permission to view the company dashboard.' : describeApiError(_error!),
          actionLabel: forbidden ? null : 'Try again',
          onAction: _load,
        ),
      );
    }

    final dashboard = _dashboard;
    if (dashboard == null) {
      return _DashboardScaffold(
        onRefresh: _load,
        child: const StateMessage(
          icon: Icons.space_dashboard_outlined,
          title: 'Dashboard not ready yet',
          message: 'Company stats appear here once your plan is set up. Pull down to refresh.',
        ),
      );
    }

    final session = ref.watch(authControllerProvider).session;
    String? sessionCompanyName;
    if (session != null) {
      for (final company in session.companies) {
        if (company.id == session.companyId) {
          sessionCompanyName = company.name;
          break;
        }
      }
    }
    final companyName = _profile?.name ?? sessionCompanyName ?? 'Your company';
    final t = EmployeeTokens.of(context);
    final overview = _overview;
    final insights = _insights;
    final permissions = ref.watch(authControllerProvider).user?.permissions ?? const <String>[];
    const leaveColours = <Color>[Color(0xFF1668E3), Color(0xFF16A34A), Color(0xFFF59E0B), Color(0xFF8B5CF6), Color(0xFF0EA5E9), Color(0xFF64748B)];

    return Scaffold(
      backgroundColor: t.canvas,
      body: RefreshIndicator(
        onRefresh: _load,
        edgeOffset: MediaQuery.paddingOf(context).top,
        child: ListView(
          padding: EdgeInsets.zero,
          physics: const AlwaysScrollableScrollPhysics(),
          children: [
            DashHeader(
              title: 'Dashboard',
              subtitle: "Here's what's happening in $companyName today.",
              detail: _longDate(),
              leading: CompanyBadge(name: companyName, logoUrl: _profile?.logoUrl),
              trailing: const MoreAction(onDark: true),
            ),
            const SizedBox(height: 16),
            if (_branches.length > 1)
              Padding(
                padding: const EdgeInsets.fromLTRB(16, 0, 16, 12),
                child: Row(children: [
                  Icon(Icons.apartment_outlined, size: 18, color: Theme.of(context).colorScheme.primary),
                  const SizedBox(width: 8),
                  const Text('Branch', style: TextStyle(fontWeight: FontWeight.w600)),
                  const SizedBox(width: 12),
                  Expanded(
                    child: DropdownButton<String?>(
                      key: const Key('dashboard-branch'),
                      isExpanded: true,
                      value: _branchId,
                      onChanged: _setBranch,
                      items: [
                        const DropdownMenuItem<String?>(value: null, child: Text('All branches')),
                        for (final b in _branches) DropdownMenuItem<String?>(value: b.id, child: Text(b.name, overflow: TextOverflow.ellipsis)),
                      ],
                    ),
                  ),
                ]),
              ),
            if (!dashboard.setupProgress.isComplete)
              Padding(padding: const EdgeInsets.fromLTRB(16, 0, 16, 16), child: _SetupProgressCard(progress: dashboard.setupProgress, companyName: companyName)),
            // What needs a decision comes first, then today's figures, then the charts (audit
            // MOB-UX-008).
            if (_pending.any)
              DashPanel(
                title: 'Waiting for you',
                caption: _pending.total == 0 ? null : '${_pending.total}${_pending.failed ? '+' : ''} awaiting your decision${_pending.breakdown.isEmpty ? '' : ' · ${_pending.breakdown}'}',
                actionLabel: 'View all',
                // Every kind in one place, not just leave (MOB-UX-001).
                onAction: () => context.push('/app/approvals'),
                child: _pending.newest.isEmpty
                    ? (_pending.failed
                        ? _PanelRetry(onRetry: _load)
                        : Padding(padding: const EdgeInsets.symmetric(vertical: 8), child: Text(_pending.total > 0 ? 'Open the Approvals inbox to see them.' : 'Nothing waiting for you.', style: Theme.of(context).textTheme.bodySmall)))
                    : Column(children: [
                        for (final p in _pending.newest)
                          DashListRow(
                            icon: _pendingIcon[p.kind]!,
                            title: _pendingTitle[p.kind]!,
                            caption: '${_names[p.employeeId] ?? 'Employee'}${p.at.isEmpty ? '' : ' · ${relativeTime(p.at)}'}',
                            // The request itself, not its list (MOB-UX-003).
                            onTap: () => context.push('${_pendingRoute[p.kind]!}/${p.id}'),
                          ),
                      ]),
              ),
            if (_pending.any) const SizedBox(height: 16),
            StatGrid(tiles: [
              StatTile(
                icon: Icons.groups_outlined,
                label: 'Total Employees',
                // Web counts from today's attendance overview; without attendance access, the company count.
                value: '${overview?.total ?? dashboard.employeeCount ?? '—'}',
                hint: _hint(trendOf(overview?.total, insights?.headcountPrevMonthEnd, 'vs last month'), overview == null ? null : '${overview.expectedEmployees} expected to work today'),
              ),
              if (overview != null)
                StatTile(
                  icon: Icons.check_circle_outline,
                  label: 'Present Today',
                  value: '${overview.present}',
                  hint: _hint(trendOf(overview.present, insights?.yesterdayPresent, 'vs yesterday'), overview.halfDay > 0 ? '${overview.halfDay} half-day, counted separately' : (overview.late > 0 ? '${overview.late} late arrivals' : null)),
                  accent: const Color(0xFF16A34A),
                  onTap: () => context.push('/app/team-attendance'),
                ),
              if (overview != null)
                StatTile(
                  icon: Icons.beach_access_outlined,
                  label: 'On Leave Today',
                  value: '${overview.onLeave}',
                  hint: _hint(trendOf(overview.onLeave, insights?.yesterdayOnLeave, 'vs yesterday'), overview.halfDayLeave > 0 ? '${overview.halfDayLeave} half-day' : null),
                  accent: const Color(0xFF8B5CF6),
                  onTap: () => context.push('/app/team-attendance'),
                ),
            ]),
            if (overview != null)
              DashPanel(
                title: 'Attendance Overview',
                actionLabel: 'View all',
                onAction: () => context.push('/app/team-attendance'),
                child: overview.nobodyRecorded
                    ? _NoCheckIns(overview: overview)
                    : DonutChart(centerLabel: 'People', segments: [
                        DonutSegment('Present', overview.present, const Color(0xFF16A34A)),
                        DonutSegment('Half day', overview.halfDay, const Color(0xFF84CC16)),
                        DonutSegment('On leave', overview.onLeave, const Color(0xFF8B5CF6)),
                        DonutSegment('Absent', overview.absent, const Color(0xFFEF4444)),
                        DonutSegment('WFH', overview.remoteWork, const Color(0xFF0D9488)),
                        DonutSegment('On duty', overview.onDuty, const Color(0xFF0EA5E9)),
                        DonutSegment('Others', overview.others, const Color(0xFF94A3B8)),
                      ]),
              ),
            if (_failed.contains('attendance'))
              DashPanel(title: 'Attendance Overview', child: _PanelRetry(onRetry: _load)),
            if (insights == null && _failed.contains('insights'))
              DashPanel(title: 'Leave Statistics', child: _PanelRetry(onRetry: _load)),
            if (insights != null)
              DashPanel(
                title: 'Leave Statistics',
                caption: insights.leavePeriodStart != null && insights.leavePeriodEnd != null ? _periodLabel(insights.leavePeriodStart!, insights.leavePeriodEnd!) : null,
                child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
                  SegmentedButton<String>(
                    segments: const [ButtonSegment(value: 'month', label: Text('This Month')), ButtonSegment(value: 'year', label: Text('This Year'))],
                    selected: {_leaveScope},
                    showSelectedIcon: false,
                    onSelectionChanged: _insightsLoading ? null : (v) => _setLeaveScope(v.first),
                  ),
                  const SizedBox(height: 12),
                  if (insights.leaveByType.isEmpty)
                    Padding(padding: const EdgeInsets.symmetric(vertical: 16), child: Text('No approved leave in this period.', textAlign: TextAlign.center, style: Theme.of(context).textTheme.bodySmall))
                  else
                    DonutChart(centerLabel: 'Days', segments: [
                      for (var i = 0; i < insights.leaveByType.length; i++)
                        DonutSegment(insights.leaveByType[i].name.replaceAll(RegExp(r' Leave$'), ''), insights.leaveByType[i].days, leaveColours[i % leaveColours.length]),
                    ]),
                ]),
              ),
            if (insights != null && insights.recentActivities.isNotEmpty)
              DashPanel(
                title: 'Recent Activities',
                child: Column(children: [
                  for (final a in insights.recentActivities.take(4))
                    DashListRow(icon: Icons.history, title: a.subject == null ? a.title : '${a.title} · ${a.subject}', caption: a.detail),
                ]),
              ),
            Padding(padding: const EdgeInsets.fromLTRB(16, 16, 16, 0), child: _QuickActions(permissions: permissions)),
            const SizedBox(height: 24),
          ],
        ),
      ),
    );
  }
}

/// A panel whose figures could not be read: says so, with a retry (audit MOB-UX-033).
class _PanelRetry extends StatelessWidget {
  const _PanelRetry({required this.onRetry});
  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.symmetric(vertical: 4),
        child: Row(children: [
          Icon(Icons.cloud_off_rounded, size: 18, color: Theme.of(context).colorScheme.error),
          const SizedBox(width: 8),
          Expanded(child: Text('Couldn\'t load this.', style: Theme.of(context).textTheme.bodyMedium)),
          TextButton(onPressed: onRetry, child: const Text('Try again')),
        ]),
      );
}

/// A trend ("+5% vs yesterday") and a note on one line, either optional.
String? _hint(({int pct, String label})? trend, String? note) {
  final parts = [if (trend != null) trendText(trend), if (note != null) note];
  return parts.isEmpty ? null : parts.join(' · ');
}

/// Web `NoCheckIns`: nobody is in a tracked status yet, so no chart.
class _NoCheckIns extends StatelessWidget {
  const _NoCheckIns({required this.overview});
  final AttendanceOverviewSummary overview;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 16),
      child: Column(children: [
        Icon(Icons.monitor_heart_outlined, color: theme.colorScheme.onSurfaceVariant),
        const SizedBox(height: 8),
        Text('No check-ins recorded yet', style: theme.textTheme.bodyMedium?.copyWith(fontWeight: FontWeight.w600)),
        const SizedBox(height: 2),
        Text('${overview.total} employees · ${overview.expectedEmployees} expected to work today', textAlign: TextAlign.center, style: theme.textTheme.bodySmall),
      ]),
    );
  }
}

/// Used for the permission/loading/error/empty states, which keep a plain app bar.
class _DashboardScaffold extends StatelessWidget {
  const _DashboardScaffold({required this.child, this.onRefresh});

  final Widget child;
  final Future<void> Function()? onRefresh;

  @override
  Widget build(BuildContext context) {
    final body = onRefresh == null ? child : RefreshIndicator(onRefresh: onRefresh!, child: child);
    return Scaffold(
      appBar: AppBar(
        title: const Text('Dashboard'),
        automaticallyImplyLeading: false,
        actions: const [MoreAction()],
      ),
      body: body,
    );
  }
}

/// A soft card surface shared by every dashboard section.
class _Panel extends StatelessWidget {
  const _Panel({required this.child, this.padding = const EdgeInsets.all(16)});

  final Widget child;
  final EdgeInsetsGeometry padding;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final dark = scheme.brightness == Brightness.dark;
    return Container(
      padding: padding,
      decoration: BoxDecoration(
        color: dark ? scheme.surfaceContainer : scheme.surfaceContainerLowest,
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: scheme.outlineVariant.withValues(alpha: 0.6)),
        boxShadow: [
          if (!dark) BoxShadow(color: AppBrand.navy.withValues(alpha: 0.05), blurRadius: 12, offset: const Offset(0, 2)),
        ],
      ),
      child: child,
    );
  }
}

class _SetupProgressCard extends StatelessWidget {
  const _SetupProgressCard({required this.progress, required this.companyName});

  final DashboardSetupProgress progress;
  final String companyName;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final scheme = theme.colorScheme;
    final status = theme.extension<AppStatusColors>() ?? AppStatusColors.light;
    if (progress.isComplete) {
      return _Panel(
        child: Row(
          children: [
            Container(
              width: 40,
              height: 40,
              decoration: BoxDecoration(color: status.successSubtle, shape: BoxShape.circle),
              child: Icon(Icons.check_rounded, color: status.success),
            ),
            const SizedBox(width: 12),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text('Setup complete', style: theme.textTheme.headlineSmall),
                  const SizedBox(height: 2),
                  Text(
                    '$companyName is fully configured. Keep contact and locale details current in the company profile.',
                    style: theme.textTheme.bodyMedium?.copyWith(color: scheme.onSurfaceVariant),
                  ),
                ],
              ),
            ),
          ],
        ),
      );
    }
    final share = progress.stepsTotal == 0 ? 0.0 : progress.stepsCompleted / progress.stepsTotal;
    return _Panel(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Row(
            children: [
              SizedBox(
                width: 56,
                height: 56,
                child: Stack(
                  fit: StackFit.expand,
                  children: [
                    CircularProgressIndicator(
                      value: share,
                      strokeWidth: 6,
                      strokeCap: StrokeCap.round,
                      backgroundColor: scheme.surfaceContainerHigh,
                    ),
                    Center(
                      child: Text(
                        '${(share * 100).round()}%',
                        style: theme.textTheme.labelMedium?.copyWith(fontWeight: FontWeight.w700),
                      ),
                    ),
                  ],
                ),
              ),
              const SizedBox(width: 16),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text('Finish setting up $companyName', style: theme.textTheme.headlineSmall),
                    const SizedBox(height: 2),
                    Text(
                      '${progress.stepsCompleted} of ${progress.stepsTotal} steps complete',
                      style: theme.textTheme.bodyMedium?.copyWith(color: scheme.onSurfaceVariant),
                    ),
                  ],
                ),
              ),
            ],
          ),
          const SizedBox(height: 16),
          FilledButton.icon(
            onPressed: () => context.push('/app/setup'),
            style: FilledButton.styleFrom(
              minimumSize: const Size.fromHeight(44),
              shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(AppRadii.xl)),
            ),
            icon: const Icon(Icons.arrow_forward_rounded, size: 18),
            label: const Text('Continue setup'),
          ),
        ],
      ),
    );
  }
}

class _QuickAction {
  const _QuickAction(this.label, this.icon, this.route, this.color);
  final String label;
  final IconData icon;
  final String route;
  final Color color;
}

/// Only the shortcuts the viewer can open, as web's action tiles; each follows the menu's rule.
class _QuickActions extends StatelessWidget {
  const _QuickActions({required this.permissions});

  final List<String> permissions;

  static const _actions = [
    _QuickAction('Employees', Icons.people_alt_outlined, '/app/employees', Color(0xFF2563EB)),
    _QuickAction('Onboarding', Icons.person_add_alt_1_outlined, '/app/onboarding', Color(0xFF0D9488)),
    _QuickAction('Attendance', Icons.fact_check_outlined, '/app/team-attendance', Color(0xFF16A34A)),
    _QuickAction('Balances', Icons.beach_access_outlined, '/app/leave-balances', Color(0xFF8B5CF6)),
    _QuickAction('Payroll', Icons.payments_outlined, '/app/payroll/pay-runs', Color(0xFFF59E0B)),
    _QuickAction('Rosters', Icons.event_available_outlined, '/app/schedule', Color(0xFF0EA5E9)),
    _QuickAction('Corrections', Icons.edit_note_rounded, '/app/regularizations', Color(0xFFEF4444)),
    _QuickAction('Company', Icons.apartment_outlined, '/app/company', Color(0xFF64748B)),
  ];

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final dark = theme.brightness == Brightness.dark;
    final shown = [for (final a in _actions) if (menuAllows(a.route, permissions)) a];
    if (shown.isEmpty) return const SizedBox.shrink();
    return _Panel(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 16),
      child: GridView.count(
        crossAxisCount: 4,
        padding: EdgeInsets.zero,
        shrinkWrap: true,
        physics: const NeverScrollableScrollPhysics(),
        mainAxisSpacing: 12,
        childAspectRatio: 0.9,
        children: [
          for (final action in shown)
            InkWell(
              onTap: () => context.push(action.route),
              borderRadius: BorderRadius.circular(12),
              child: Column(
                mainAxisAlignment: MainAxisAlignment.center,
                children: [
                  Container(
                    width: 48,
                    height: 48,
                    decoration: BoxDecoration(
                      color: action.color.withValues(alpha: dark ? 0.2 : 0.1),
                      borderRadius: BorderRadius.circular(14),
                    ),
                    child: Icon(action.icon, color: dark ? Color.lerp(action.color, Colors.white, 0.3) : action.color),
                  ),
                  const SizedBox(height: 8),
                  Text(
                    action.label,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: theme.textTheme.bodySmall?.copyWith(fontWeight: FontWeight.w500, color: theme.colorScheme.onSurface),
                  ),
                ],
              ),
            ),
        ],
      ),
    );
  }
}

