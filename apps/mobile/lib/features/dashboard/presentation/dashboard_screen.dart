import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../core/api/api_error.dart';
import '../../../core/auth/permissions.dart';
import '../../../core/nav/nav_entries.dart' show isPayrollRoute, kPayrollInRelease;
import '../../../core/providers.dart';
import '../../../core/theme/app_colors.dart';
import '../../../core/theme/app_theme.dart';
import '../../../core/widgets/ui.dart';
import '../../../features/shell/more_action.dart';
import '../../auth/state/auth_controller.dart';
import '../data/dashboard_repository.dart';

final dashboardRepositoryProvider = Provider<DashboardRepository>(
  (ref) => DashboardRepository(ref.watch(apiClientProvider)),
);

/// `null` counts (sub-domains that don't exist yet) render as "—", never a
/// fabricated 0 — mirrors `apps/web/src/app/app/dashboard/page.tsx::formatCount`.
String _formatCount(int? value) => value == null ? '—' : value.toString();

String _formatSeatLimit(int? value, {required bool known}) {
  if (!known) return '—';
  if (value == null) return 'Unlimited';
  return value.toString();
}

String _formatTrial(String? endsAt) {
  if (endsAt == null) return '—';
  final parsed = DateTime.tryParse(endsAt);
  if (parsed == null) return endsAt;
  const months = [
    'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec',
  ];
  return '${months[parsed.month - 1]} ${parsed.day}, ${parsed.year}';
}

/// "12 days left" for a trial end date still in the future, else `null`.
String? _trialCountdown(String? endsAt) {
  final parsed = endsAt == null ? null : DateTime.tryParse(endsAt);
  if (parsed == null) return null;
  final days = parsed.difference(DateTime.now()).inDays;
  if (days < 0) return null;
  if (days == 0) return 'Trial ends today';
  return '$days ${days == 1 ? 'day' : 'days'} left in trial';
}

String _greeting() {
  final hour = DateTime.now().hour;
  if (hour < 12) return 'Good morning';
  if (hour < 17) return 'Good afternoon';
  return 'Good evening';
}

/// `ATTENDANCE_FACE` → `Attendance face`; `PAST_DUE` → `Past due`.
String _humanize(String code) {
  final words = code.replaceAll('_', ' ').replaceAll('.', ' ').toLowerCase().trim();
  return words.isEmpty ? code : words[0].toUpperCase() + words.substring(1);
}

String _initials(String name) {
  final parts = name.trim().split(RegExp(r'\s+')).where((p) => p.isNotEmpty).toList();
  if (parts.isEmpty) return '—';
  if (parts.length == 1) return parts.first.substring(0, parts.first.length >= 2 ? 2 : 1).toUpperCase();
  return (parts[0][0] + parts[1][0]).toUpperCase();
}

enum _Tone { success, info, warning, danger, neutral }

_Tone _toneFor(String status) => switch (status.toUpperCase()) {
      'ACTIVE' || 'COMPLETE' => _Tone.success,
      'TRIAL' || 'TRIALING' || 'IN_PROGRESS' => _Tone.info,
      'PENDING_APPROVAL' || 'PAST_DUE' || 'GRACE' => _Tone.warning,
      'SUSPENDED' || 'CANCELLED' || 'CANCELED' || 'EXPIRED' => _Tone.danger,
      _ => _Tone.neutral,
    };

/// Mirrors `apps/web/src/app/app/dashboard/page.tsx` — an at-a-glance view of
/// the company, its plan, and setup progress. Gated on `DASHBOARD.COMPANY.VIEW`
/// (only `COMPANY_ADMIN`/`HR_ADMIN`-shaped users hold it; `landingPathFor`
/// already keeps anyone else off this tab, but a user can still reach it by
/// tapping it directly, so this checks again rather than trusting the caller).
class DashboardScreen extends ConsumerStatefulWidget {
  const DashboardScreen({super.key});

  @override
  ConsumerState<DashboardScreen> createState() => _DashboardScreenState();
}

class _DashboardScreenState extends ConsumerState<DashboardScreen> {
  bool _loading = true;
  CompanyDashboardSummary? _dashboard;
  SubscriptionSummary? _subscription;
  CompanyProfileSummary? _profile;
  ApiError? _error;

  @override
  void initState() {
    super.initState();
    _load();
  }

  /// Mirrors `apps/web/src/hooks/use-api-resource.ts`: each of the three
  /// resources is fetched independently — and concurrently, they don't depend on each other —
  /// and a 404 on any of them ("not implemented yet for this company", e.g. no live
  /// subscription) resolves to `null` data rather than a page-level error. Only a non-404
  /// failure sets [_error], with the same precedence as the web page's
  /// `dashboardError ?? subscriptionError ?? profileError` regardless of which call finishes first.
  Future<void> _load() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    final repository = ref.read(dashboardRepositoryProvider);

    Future<({T? data, ApiError? error})> fetch<T>(Future<T> Function() call) async {
      try {
        return (data: await call(), error: null);
      } on ApiError catch (error) {
        return (data: null, error: error.status == 404 ? null : error);
      } catch (_) {
        return (data: null, error: ApiError(status: 0, code: 'UNKNOWN_ERROR', message: 'Something went wrong.'));
      }
    }

    final (dashboard, subscription, profile) = await (
      fetch(repository.getCompanyDashboard),
      fetch(repository.getSubscription),
      fetch(repository.getCompanyProfile),
    ).wait;

    if (!mounted) return;
    setState(() {
      _dashboard = dashboard.data;
      _subscription = subscription.data;
      _profile = profile.data;
      _error = dashboard.error ?? subscription.error ?? profile.error;
      _loading = false;
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
          message: forbidden ? 'You do not have permission to view the company dashboard.' : _error!.message,
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
    final scheme = Theme.of(context).colorScheme;

    return AnnotatedRegion<SystemUiOverlayStyle>(
      value: SystemUiOverlayStyle.light.copyWith(statusBarColor: Colors.transparent),
      child: Scaffold(
        backgroundColor: scheme.surfaceContainerLow,
        body: RefreshIndicator(
          onRefresh: _load,
          edgeOffset: MediaQuery.paddingOf(context).top,
          child: ListView(
            padding: EdgeInsets.zero,
            physics: const AlwaysScrollableScrollPhysics(),
            children: [
              _DashboardHeader(
                companyName: companyName,
                companyStatus: _profile?.status,
                subscription: dashboard.subscription,
              ),
              // The workforce card overlaps the bottom of the navy header.
              Transform.translate(
                offset: const Offset(0, -36),
                child: Padding(
                  padding: const EdgeInsets.symmetric(horizontal: 16),
                  child: _WorkforceCard(dashboard: dashboard, subscription: _subscription),
                ),
              ),
              Padding(
                padding: const EdgeInsets.fromLTRB(16, 0, 16, 24),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    Transform.translate(
                      offset: const Offset(0, -20),
                      child: _SetupProgressCard(progress: dashboard.setupProgress, companyName: companyName),
                    ),
                    const _SectionTitle('Quick actions'),
                    const _QuickActions(),
                    const SizedBox(height: 24),
                    const _SectionTitle('Subscription'),
                    _SubscriptionCard(subscription: _subscription),
                    const SizedBox(height: 16),
                    Text(
                      'Counts shown as "—" are not available yet for your company.',
                      style: Theme.of(context).textTheme.bodySmall?.copyWith(color: scheme.onSurfaceVariant),
                      textAlign: TextAlign.center,
                    ),
                  ],
                ),
              ),
            ],
          ),
        ),
      ),
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

class _SectionTitle extends StatelessWidget {
  const _SectionTitle(this.label);

  final String label;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(left: 4, bottom: 12),
      child: Text(label, style: Theme.of(context).textTheme.headlineSmall),
    );
  }
}

class _StatusPill extends StatelessWidget {
  const _StatusPill({required this.label, required this.tone, this.onDark = false});

  final String label;
  final _Tone tone;
  final bool onDark;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final status = Theme.of(context).extension<AppStatusColors>() ?? AppStatusColors.light;
    final (fg, bg) = switch (tone) {
      _Tone.success => (status.success, status.successSubtle),
      _Tone.info => (status.info, status.infoSubtle),
      _Tone.warning => (status.warning, status.warningSubtle),
      _Tone.danger => (status.danger, status.dangerSubtle),
      _Tone.neutral => (scheme.onSurfaceVariant, scheme.surfaceContainerHigh),
    };
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
      decoration: BoxDecoration(
        color: onDark ? Colors.white.withValues(alpha: 0.12) : bg,
        borderRadius: BorderRadius.circular(AppRadii.full),
        border: onDark ? Border.all(color: Colors.white.withValues(alpha: 0.18)) : null,
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Container(width: 7, height: 7, decoration: BoxDecoration(color: fg, shape: BoxShape.circle)),
          const SizedBox(width: 6),
          Text(
            label,
            style: TextStyle(
              fontSize: 12,
              fontWeight: FontWeight.w600,
              color: onDark ? Colors.white.withValues(alpha: 0.9) : fg,
            ),
          ),
        ],
      ),
    );
  }
}

class _DashboardHeader extends StatelessWidget {
  const _DashboardHeader({required this.companyName, required this.companyStatus, required this.subscription});

  final String companyName;
  final String? companyStatus;
  final DashboardSubscription? subscription;

  @override
  Widget build(BuildContext context) {
    final textTheme = Theme.of(context).textTheme;
    final countdown = _trialCountdown(subscription?.trialEndsAt);
    return Container(
      decoration: const BoxDecoration(
        gradient: LinearGradient(
          begin: Alignment.topLeft,
          end: Alignment.bottomRight,
          colors: [AppBrand.navy, AppBrand.navyDeep],
        ),
      ),
      child: Stack(
        children: [
          Positioned(
            right: -50,
            top: -60,
            child: Container(
              width: 200,
              height: 200,
              decoration: BoxDecoration(
                shape: BoxShape.circle,
                border: Border.all(color: AppBrand.blue.withValues(alpha: 0.25), width: 26),
              ),
            ),
          ),
          SafeArea(
            bottom: false,
            child: Padding(
              padding: const EdgeInsets.fromLTRB(20, 12, 8, 60),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(
                    children: [
                      Container(
                        width: 44,
                        height: 44,
                        alignment: Alignment.center,
                        decoration: BoxDecoration(
                          color: AppBrand.blue,
                          borderRadius: BorderRadius.circular(12),
                        ),
                        child: Text(
                          _initials(companyName),
                          style: const TextStyle(color: Colors.white, fontWeight: FontWeight.w700, fontSize: 16),
                        ),
                      ),
                      const SizedBox(width: 12),
                      Expanded(
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Text(
                              _greeting(),
                              style: textTheme.bodyMedium?.copyWith(color: Colors.white.withValues(alpha: 0.7)),
                            ),
                            const SizedBox(height: 2),
                            Text(
                              companyName,
                              maxLines: 1,
                              overflow: TextOverflow.ellipsis,
                              style: textTheme.headlineMedium?.copyWith(color: Colors.white, fontSize: 20),
                            ),
                          ],
                        ),
                      ),
                      IconButton(
                        icon: const Icon(Icons.apps_rounded, color: Colors.white),
                        tooltip: 'More',
                        onPressed: () => context.push('/app/more'),
                      ),
                    ],
                  ),
                  const SizedBox(height: 16),
                  Wrap(
                    spacing: 8,
                    runSpacing: 8,
                    children: [
                      if (companyStatus != null)
                        _StatusPill(label: _humanize(companyStatus!), tone: _toneFor(companyStatus!), onDark: true),
                      if (subscription != null)
                        _StatusPill(
                          label: countdown ?? '${subscription!.planCode} · ${_humanize(subscription!.status)}',
                          tone: _toneFor(subscription!.status),
                          onDark: true,
                        ),
                    ],
                  ),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _WorkforceCard extends StatelessWidget {
  const _WorkforceCard({required this.dashboard, required this.subscription});

  final CompanyDashboardSummary dashboard;
  final SubscriptionSummary? subscription;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final scheme = theme.colorScheme;
    final employees = dashboard.employeeCount;
    final seatLimit = subscription?.seatLimit;
    final seatShare = (employees != null && seatLimit != null && seatLimit > 0) ? (employees / seatLimit).clamp(0.0, 1.0) : null;
    final muted = theme.textTheme.bodyMedium?.copyWith(color: scheme.onSurfaceVariant);
    return _Panel(
      padding: const EdgeInsets.all(20),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text('Total employees', style: muted),
                    const SizedBox(height: 4),
                    Text(
                      _formatCount(employees),
                      style: theme.textTheme.headlineLarge?.copyWith(fontSize: 34, height: 1.1, fontWeight: FontWeight.w700),
                    ),
                  ],
                ),
              ),
              Container(
                width: 44,
                height: 44,
                decoration: BoxDecoration(
                  color: scheme.primary.withValues(alpha: 0.1),
                  borderRadius: BorderRadius.circular(12),
                ),
                child: Icon(Icons.groups_rounded, color: scheme.primary),
              ),
            ],
          ),
          const SizedBox(height: 14),
          if (seatShare != null) ...[
            ClipRRect(
              borderRadius: BorderRadius.circular(AppRadii.full),
              child: LinearProgressIndicator(
                value: seatShare,
                minHeight: 6,
                backgroundColor: scheme.surfaceContainerHigh,
              ),
            ),
            const SizedBox(height: 8),
            Text('$employees of $seatLimit seats used', style: theme.textTheme.bodySmall?.copyWith(color: scheme.onSurfaceVariant)),
          ] else
            Text(
              'Seat limit: ${_formatSeatLimit(seatLimit, known: subscription != null)}',
              style: theme.textTheme.bodySmall?.copyWith(color: scheme.onSurfaceVariant),
            ),
          const SizedBox(height: 16),
          Divider(color: scheme.outlineVariant.withValues(alpha: 0.6)),
          const SizedBox(height: 12),
          Row(
            children: [
              Expanded(
                child: _MiniStat(
                  icon: Icons.business_rounded,
                  label: 'Branches',
                  value: _formatCount(dashboard.branchCount),
                  onTap: () => context.push('/app/branches'),
                ),
              ),
              Container(width: 1, height: 36, color: scheme.outlineVariant.withValues(alpha: 0.6)),
              Expanded(
                child: _MiniStat(
                  icon: Icons.account_tree_rounded,
                  label: 'Departments',
                  value: _formatCount(dashboard.departmentCount),
                  onTap: () => context.push('/app/departments'),
                ),
              ),
            ],
          ),
        ],
      ),
    );
  }
}

class _MiniStat extends StatelessWidget {
  const _MiniStat({required this.icon, required this.label, required this.value, required this.onTap});

  final IconData icon;
  final String label;
  final String value;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final scheme = theme.colorScheme;
    return InkWell(
      onTap: onTap,
      borderRadius: BorderRadius.circular(10),
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
        child: Row(
          children: [
            Icon(icon, size: 20, color: scheme.onSurfaceVariant),
            const SizedBox(width: 10),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(value, style: theme.textTheme.headlineSmall?.copyWith(fontSize: 18, fontWeight: FontWeight.w700)),
                  Text(label, style: theme.textTheme.bodySmall?.copyWith(color: scheme.onSurfaceVariant)),
                ],
              ),
            ),
          ],
        ),
      ),
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

class _QuickActions extends StatelessWidget {
  const _QuickActions();

  static const _actions = [
    _QuickAction('Employees', Icons.people_alt_outlined, '/app/employees', Color(0xFF2563EB)),
    _QuickAction('Onboarding', Icons.person_add_alt_1_outlined, '/app/onboarding', Color(0xFF0D9488)),
    _QuickAction('Attendance', Icons.fact_check_outlined, '/app/team-attendance', Color(0xFF16A34A)),
    _QuickAction('Leave', Icons.beach_access_outlined, '/app/leave-balances', Color(0xFF8B5CF6)),
    _QuickAction('Payroll', Icons.payments_outlined, '/app/payroll/pay-runs', Color(0xFFF59E0B)),
    _QuickAction('Rosters', Icons.event_available_outlined, '/app/rosters', Color(0xFF0EA5E9)),
    _QuickAction('Requests', Icons.edit_note_rounded, '/app/regularizations', Color(0xFFEF4444)),
    _QuickAction('Company', Icons.apartment_outlined, '/app/company', Color(0xFF64748B)),
  ];

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final dark = theme.brightness == Brightness.dark;
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
          for (final action in _actions.where((a) => kPayrollInRelease || !isPayrollRoute(a.route)))
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

class _DetailRow extends StatelessWidget {
  const _DetailRow({required this.label, required this.child});

  final String label;
  final Widget child;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 10),
      child: Row(
        mainAxisAlignment: MainAxisAlignment.spaceBetween,
        children: [
          Text(label, style: TextStyle(color: scheme.onSurfaceVariant)),
          const SizedBox(width: 12),
          Flexible(child: DefaultTextStyle.merge(style: const TextStyle(fontWeight: FontWeight.w600), textAlign: TextAlign.end, child: child)),
        ],
      ),
    );
  }
}

class _SubscriptionCard extends StatelessWidget {
  const _SubscriptionCard({required this.subscription});

  final SubscriptionSummary? subscription;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final scheme = theme.colorScheme;
    final subscription = this.subscription;
    if (subscription == null) {
      return _Panel(
        child: Row(
          children: [
            Icon(Icons.credit_card_off_outlined, color: scheme.onSurfaceVariant),
            const SizedBox(width: 12),
            Expanded(child: Text('No live subscription is available.', style: TextStyle(color: scheme.onSurfaceVariant))),
          ],
        ),
      );
    }
    final enabled = subscription.features.where((f) => f.isEnabled).toList();
    final disabledCount = subscription.features.length - enabled.length;
    final divider = Divider(color: scheme.outlineVariant.withValues(alpha: 0.6), height: 1);
    return _Panel(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Container(
                width: 40,
                height: 40,
                decoration: BoxDecoration(
                  color: scheme.primary.withValues(alpha: 0.1),
                  borderRadius: BorderRadius.circular(12),
                ),
                child: Icon(Icons.workspace_premium_outlined, color: scheme.primary),
              ),
              const SizedBox(width: 12),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(subscription.planName, style: theme.textTheme.headlineSmall),
                    Text(subscription.planCode, style: theme.textTheme.bodySmall?.copyWith(color: scheme.onSurfaceVariant)),
                  ],
                ),
              ),
              _StatusPill(label: _humanize(subscription.status), tone: _toneFor(subscription.status)),
            ],
          ),
          const SizedBox(height: 8),
          _DetailRow(label: 'Trial ends', child: Text(_formatTrial(subscription.trialEndsAt))),
          divider,
          _DetailRow(label: 'Seat limit', child: Text(_formatSeatLimit(subscription.seatLimit, known: true))),
          if (subscription.features.isNotEmpty) ...[
            divider,
            const SizedBox(height: 14),
            Text('Included features', style: theme.textTheme.labelMedium?.copyWith(color: scheme.onSurfaceVariant)),
            const SizedBox(height: 10),
            Wrap(
              spacing: 8,
              runSpacing: 8,
              children: [
                for (final feature in enabled)
                  Container(
                    padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
                    decoration: BoxDecoration(
                      color: scheme.surfaceContainerLow,
                      borderRadius: BorderRadius.circular(AppRadii.full),
                      border: Border.all(color: scheme.outlineVariant.withValues(alpha: 0.6)),
                    ),
                    child: Row(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        Icon(Icons.check_rounded, size: 14, color: scheme.primary),
                        const SizedBox(width: 4),
                        Text(
                          '${_humanize(feature.code)}${feature.limitValue != null ? ' · ${feature.limitValue}' : ''}',
                          style: theme.textTheme.bodySmall?.copyWith(fontWeight: FontWeight.w500, color: scheme.onSurface),
                        ),
                      ],
                    ),
                  ),
              ],
            ),
            if (disabledCount > 0) ...[
              const SizedBox(height: 10),
              Text(
                '$disabledCount ${disabledCount == 1 ? 'feature is' : 'features are'} not included in this plan.',
                style: theme.textTheme.bodySmall?.copyWith(color: scheme.onSurfaceVariant),
              ),
            ],
          ],
        ],
      ),
    );
  }
}
