import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api/api_error.dart';
import '../../../core/auth/permissions.dart';
import '../../../core/providers.dart';
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
  /// resources is fetched independently, and a 404 on any of them ("not
  /// implemented yet for this company", e.g. no live subscription) resolves
  /// to `null` data rather than a page-level error — only a non-404 failure
  /// sets [_error], first one wins, same precedence as the web page's
  /// `dashboardError ?? subscriptionError ?? profileError`.
  Future<void> _load() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    final repository = ref.read(dashboardRepositoryProvider);

    Future<T?> fetch<T>(Future<T> Function() call) async {
      try {
        return await call();
      } on ApiError catch (error) {
        if (error.status == 404) return null;
        _error ??= error;
        return null;
      } catch (error) {
        _error ??= ApiError(status: 0, code: 'UNKNOWN_ERROR', message: 'Something went wrong.');
        return null;
      }
    }

    final dashboard = await fetch(repository.getCompanyDashboard);
    final subscription = await fetch(repository.getSubscription);
    final profile = await fetch(repository.getCompanyProfile);

    if (!mounted) return;
    setState(() {
      _dashboard = dashboard;
      _subscription = subscription;
      _profile = profile;
      _loading = false;
    });
  }

  @override
  Widget build(BuildContext context) {
    final hasPermission = ref.watch(authControllerProvider).user?.permissions.contains(dashboardCompanyView) ?? false;

    if (!hasPermission) {
      return const _DashboardScaffold(
        child: Center(
          child: Padding(
            padding: EdgeInsets.all(24),
            child: Text('You do not have permission to view the company dashboard.', textAlign: TextAlign.center),
          ),
        ),
      );
    }

    if (_loading) {
      return const _DashboardScaffold(child: Center(child: CircularProgressIndicator()));
    }

    if (_error != null) {
      return _DashboardScaffold(
        child: Center(
          child: Padding(
            padding: const EdgeInsets.all(24),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                Text(
                  _error!.status == 403 ? 'You do not have permission to view the company dashboard.' : _error!.message,
                  textAlign: TextAlign.center,
                ),
                const SizedBox(height: 16),
                FilledButton(onPressed: _load, child: const Text('Retry')),
              ],
            ),
          ),
        ),
      );
    }

    final dashboard = _dashboard;
    if (dashboard == null) {
      return _DashboardScaffold(
        onRefresh: _load,
        child: const Center(
          child: Padding(
            padding: EdgeInsets.all(24),
            child: Text('Dashboard data is not available yet.', textAlign: TextAlign.center),
          ),
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

    return _DashboardScaffold(
      onRefresh: _load,
      child: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          _SetupProgressCard(progress: dashboard.setupProgress, companyName: companyName),
          const SizedBox(height: 24),
          Text('Overview', style: Theme.of(context).textTheme.labelMedium),
          const SizedBox(height: 12),
          _OverviewGrid(dashboard: dashboard, subscription: _subscription),
          const SizedBox(height: 20),
          _SubscriptionCard(subscription: _subscription),
          const SizedBox(height: 16),
          _CompanyCard(dashboard: dashboard, companyName: companyName, profile: _profile),
        ],
      ),
    );
  }
}

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

class _SetupProgressCard extends StatelessWidget {
  const _SetupProgressCard({required this.progress, required this.companyName});

  final DashboardSetupProgress progress;
  final String companyName;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    if (progress.isComplete) {
      return Container(
        padding: const EdgeInsets.all(16),
        decoration: BoxDecoration(
          color: scheme.secondaryContainer.withValues(alpha: 0.4),
          borderRadius: BorderRadius.circular(12),
          border: Border.all(color: scheme.outlineVariant),
        ),
        child: Row(
          children: [
            const Icon(Icons.check_circle, color: Colors.green),
            const SizedBox(width: 12),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const Text('Setup complete', style: TextStyle(fontWeight: FontWeight.w600)),
                  const SizedBox(height: 2),
                  Text(
                    '$companyName is fully configured. Keep contact and locale details current in the company profile.',
                    style: TextStyle(color: scheme.onSurfaceVariant, fontSize: 13),
                  ),
                ],
              ),
            ),
          ],
        ),
      );
    }
    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: scheme.primaryContainer.withValues(alpha: 0.15),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: scheme.primary.withValues(alpha: 0.2)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Icon(Icons.checklist, color: scheme.primary),
              const SizedBox(width: 12),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text('Finish setting up $companyName', style: const TextStyle(fontWeight: FontWeight.w600)),
                    const SizedBox(height: 2),
                    Text(
                      '${progress.stepsCompleted} of ${progress.stepsTotal} steps complete',
                      style: TextStyle(color: scheme.onSurfaceVariant, fontSize: 13),
                    ),
                  ],
                ),
              ),
            ],
          ),
          const SizedBox(height: 12),
          ClipRRect(
            borderRadius: BorderRadius.circular(999),
            child: LinearProgressIndicator(
              value: progress.stepsTotal == 0 ? 0 : progress.stepsCompleted / progress.stepsTotal,
              minHeight: 6,
              backgroundColor: scheme.surfaceContainerHigh,
            ),
          ),
        ],
      ),
    );
  }
}

class _OverviewGrid extends StatelessWidget {
  const _OverviewGrid({required this.dashboard, required this.subscription});

  final CompanyDashboardSummary dashboard;
  final SubscriptionSummary? subscription;

  @override
  Widget build(BuildContext context) {
    final tiles = [
      _StatTile(label: 'Employees', value: _formatCount(dashboard.employeeCount), icon: Icons.groups, emphasis: true),
      _StatTile(label: 'Branches', value: _formatCount(dashboard.branchCount), icon: Icons.apartment),
      _StatTile(label: 'Departments', value: _formatCount(dashboard.departmentCount), icon: Icons.layers),
      _StatTile(
        label: 'Seat limit',
        value: _formatSeatLimit(subscription?.seatLimit, known: subscription != null),
        icon: Icons.groups_2,
      ),
      _StatTile(
        label: 'Plan',
        value: dashboard.subscription?.planCode ?? '—',
        hint: dashboard.subscription?.status ?? 'No live subscription',
        icon: Icons.credit_card,
      ),
    ];
    return GridView.count(
      crossAxisCount: 2,
      shrinkWrap: true,
      physics: const NeverScrollableScrollPhysics(),
      mainAxisSpacing: 12,
      crossAxisSpacing: 12,
      childAspectRatio: 1.5,
      children: tiles,
    );
  }
}

class _StatTile extends StatelessWidget {
  const _StatTile({required this.label, required this.value, this.hint, required this.icon, this.emphasis = false});

  final String label;
  final String value;
  final String? hint;
  final IconData icon;
  final bool emphasis;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    return Container(
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: scheme.surfaceContainerLowest,
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: scheme.outlineVariant),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              Expanded(
                child: Text(
                  label.toUpperCase(),
                  style: TextStyle(fontSize: 11, fontWeight: FontWeight.w600, color: scheme.onSurfaceVariant, letterSpacing: 0.4),
                ),
              ),
              Container(
                width: 28,
                height: 28,
                decoration: BoxDecoration(
                  color: emphasis ? scheme.primaryContainer.withValues(alpha: 0.3) : scheme.surfaceContainerHigh,
                  borderRadius: BorderRadius.circular(8),
                ),
                child: Icon(icon, size: 16, color: emphasis ? scheme.primary : scheme.onSurfaceVariant),
              ),
            ],
          ),
          const Spacer(),
          Text(value, style: const TextStyle(fontSize: 22, fontWeight: FontWeight.w700)),
          if (hint != null) Text(hint!, style: TextStyle(fontSize: 11, color: scheme.onSurfaceVariant)),
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
      padding: const EdgeInsets.symmetric(vertical: 8),
      child: Row(
        mainAxisAlignment: MainAxisAlignment.spaceBetween,
        children: [
          Text(label, style: TextStyle(color: scheme.onSurfaceVariant)),
          child,
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
    final scheme = Theme.of(context).colorScheme;
    final subscription = this.subscription;
    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: scheme.surfaceContainerLowest,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: scheme.outlineVariant),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text('Subscription', style: Theme.of(context).textTheme.headlineSmall),
          const SizedBox(height: 8),
          if (subscription == null)
            Text('No live subscription is available.', style: TextStyle(color: scheme.onSurfaceVariant))
          else ...[
            _DetailRow(label: 'Plan', child: Text('${subscription.planName} (${subscription.planCode})')),
            Divider(color: scheme.outlineVariant),
            _DetailRow(
              label: 'Status',
              child: Container(
                padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
                decoration: BoxDecoration(color: scheme.surfaceContainerHigh, borderRadius: BorderRadius.circular(4)),
                child: Text(subscription.status.toUpperCase(), style: const TextStyle(fontSize: 11, fontWeight: FontWeight.w600)),
              ),
            ),
            Divider(color: scheme.outlineVariant),
            _DetailRow(label: 'Trial ends', child: Text(_formatTrial(subscription.trialEndsAt))),
            Divider(color: scheme.outlineVariant),
            _DetailRow(label: 'Seat limit', child: Text(_formatSeatLimit(subscription.seatLimit, known: true))),
            if (subscription.features.isNotEmpty) ...[
              const SizedBox(height: 12),
              Text('FEATURES', style: TextStyle(fontSize: 11, fontWeight: FontWeight.w600, color: scheme.onSurfaceVariant)),
              const SizedBox(height: 8),
              for (final feature in subscription.features)
                Padding(
                  padding: const EdgeInsets.symmetric(vertical: 4),
                  child: Row(
                    children: [
                      Icon(
                        feature.isEnabled ? Icons.check_circle : Icons.cancel_outlined,
                        size: 16,
                        color: feature.isEnabled ? Colors.green : scheme.onSurfaceVariant.withValues(alpha: 0.5),
                      ),
                      const SizedBox(width: 8),
                      Expanded(
                        child: Text('${feature.code}  ·  ${feature.source.replaceAll('_', ' ').toLowerCase()}'),
                      ),
                      Text(
                        feature.isEnabled ? 'On${feature.limitValue != null ? ' · ${feature.limitValue}' : ''}' : 'Off',
                        style: TextStyle(color: scheme.onSurfaceVariant),
                      ),
                    ],
                  ),
                ),
            ],
          ],
        ],
      ),
    );
  }
}

class _CompanyCard extends StatelessWidget {
  const _CompanyCard({required this.dashboard, required this.companyName, required this.profile});

  final CompanyDashboardSummary dashboard;
  final String companyName;
  final CompanyProfileSummary? profile;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final initials = companyName.trim().isEmpty ? '—' : companyName.trim().substring(0, companyName.trim().length >= 2 ? 2 : 1).toUpperCase();
    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: scheme.surfaceContainerLowest,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: scheme.outlineVariant),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text('Company', style: Theme.of(context).textTheme.headlineSmall),
          const SizedBox(height: 12),
          Row(
            children: [
              Container(
                width: 40,
                height: 40,
                alignment: Alignment.center,
                decoration: BoxDecoration(color: scheme.primaryContainer.withValues(alpha: 0.3), borderRadius: BorderRadius.circular(8)),
                child: Text(initials, style: TextStyle(fontWeight: FontWeight.w700, color: scheme.primary)),
              ),
              const SizedBox(width: 12),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(companyName, style: const TextStyle(fontWeight: FontWeight.w600), overflow: TextOverflow.ellipsis),
                    Text(profile?.id ?? '—', style: TextStyle(fontSize: 12, color: scheme.onSurfaceVariant), overflow: TextOverflow.ellipsis),
                  ],
                ),
              ),
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
                decoration: BoxDecoration(color: scheme.surfaceContainerHigh, borderRadius: BorderRadius.circular(4)),
                child: Text((profile?.status ?? '—').toUpperCase(), style: const TextStyle(fontSize: 11, fontWeight: FontWeight.w600)),
              ),
            ],
          ),
          Divider(color: scheme.outlineVariant, height: 24),
          _DetailRow(label: 'Branches', child: Text(_formatCount(dashboard.branchCount))),
          Divider(color: scheme.outlineVariant),
          _DetailRow(label: 'Departments', child: Text(_formatCount(dashboard.departmentCount))),
          Divider(color: scheme.outlineVariant),
          _DetailRow(label: 'Employees', child: Text(_formatCount(dashboard.employeeCount))),
          const SizedBox(height: 12),
          Text(
            'Organisation structure, attendance, leave, and payroll will appear here as those modules ship. Counts shown as "—" are not available yet.',
            style: TextStyle(fontSize: 12, color: scheme.onSurfaceVariant),
          ),
        ],
      ),
    );
  }
}
