import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/auth/auth_types.dart';
import '../../core/auth/permissions.dart';
import '../../core/theme/app_theme.dart';
import '../auth/state/auth_controller.dart';

/// Bottom navigation chrome for the authenticated app — mirrors the Stitch
/// "Mobile Dashboard" screen's tab bar (Dashboard / Attendance / Leave /
/// Profile). Used as a `StatefulShellRoute.indexedStack` branch container so
/// each tab keeps its own navigation state across switches.
class AppShell extends ConsumerWidget {
  const AppShell({super.key, required this.navigationShell});

  final StatefulNavigationShell navigationShell;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final user = ref.watch(authControllerProvider).user;
    final status = user?.companyStatus;
    final branches = visibleShellBranches(user);
    // The current branch can be hidden (e.g. a deep link to the dashboard); show the first tab.
    final selected = branches.contains(navigationShell.currentIndex) ? branches.indexOf(navigationShell.currentIndex) : 0;
    return Scaffold(
      body: Column(
        children: [
          if (status == 'PENDING_APPROVAL' || status == 'SUSPENDED') CompanyReadOnlyBanner(status: status!),
          Expanded(child: navigationShell),
        ],
      ),
      bottomNavigationBar: DecoratedBox(
        decoration: BoxDecoration(
          border: Border(top: BorderSide(color: Theme.of(context).colorScheme.outlineVariant.withValues(alpha: 0.5))),
          boxShadow: [
            BoxShadow(color: AppBrand.navy.withValues(alpha: 0.06), blurRadius: 20, offset: const Offset(0, -4)),
          ],
        ),
        child: NavigationBar(
          selectedIndex: selected,
          labelBehavior: NavigationDestinationLabelBehavior.alwaysShow,
          onDestinationSelected: (index) {
            HapticFeedback.selectionClick();
            final branch = branches[index];
            navigationShell.goBranch(branch, initialLocation: branch == navigationShell.currentIndex);
          },
          destinations: [for (final branch in branches) _destinations[branch]],
        ),
      ),
    );
  }
}

/// Branch indexes of the `StatefulShellRoute` in `app_router.dart`, in tab order.
const shellHomeBranch = 0;
const _shellBranchCount = 4;

const _destinations = [
  NavigationDestination(icon: Icon(Icons.space_dashboard_outlined), selectedIcon: Icon(Icons.space_dashboard_rounded), label: 'Home'),
  NavigationDestination(icon: Icon(Icons.fingerprint_rounded), selectedIcon: Icon(Icons.fingerprint_rounded), label: 'Attendance'),
  NavigationDestination(icon: Icon(Icons.beach_access_outlined), selectedIcon: Icon(Icons.beach_access_rounded), label: 'Leave'),
  NavigationDestination(icon: Icon(Icons.person_outline_rounded), selectedIcon: Icon(Icons.person_rounded), label: 'Profile'),
];

/// Whether the Home tab (the company dashboard) is worth showing. It needs
/// `DASHBOARD.COMPANY.VIEW`; an employee without it would only land on "No access". A user with
/// neither the permission nor an employee record keeps it — it is the only tab that explains
/// their situation — and so does a user whose profile hasn't loaded.
bool showHomeTab(UserProfile? user) =>
    user == null || user.permissions.contains(dashboardCompanyView) || user.employeeId == null;

/// The shell branch indexes to show as tabs, in order.
List<int> visibleShellBranches(UserProfile? user) => [
      for (var i = 0; i < _shellBranchCount; i++)
        if (i != shellHomeBranch || showHomeTab(user)) i,
    ];

/// Read-only notice for a company the platform has not (yet) cleared for changes. The API
/// enforces it regardless of what this shows.
class CompanyReadOnlyBanner extends StatelessWidget {
  const CompanyReadOnlyBanner({super.key, required this.status});

  final String status;

  @override
  Widget build(BuildContext context) {
    final pending = status == 'PENDING_APPROVAL';
    final scheme = Theme.of(context).colorScheme;
    return Material(
      color: scheme.tertiaryContainer,
      child: SafeArea(
        bottom: false,
        child: Padding(
          padding: const EdgeInsets.fromLTRB(16, 10, 16, 10),
          child: Row(
            children: [
              Icon(pending ? Icons.hourglass_top_rounded : Icons.lock_outline_rounded, size: 18, color: scheme.onTertiaryContainer),
              const SizedBox(width: 10),
              Expanded(
                child: Text(
                  pending
                      ? 'Your company is awaiting approval. You can view data, but changes are disabled.'
                      : 'Your company is suspended. You can view data, but changes are disabled.',
                  style: TextStyle(color: scheme.onTertiaryContainer, fontSize: 13, fontWeight: FontWeight.w500, height: 1.3),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
