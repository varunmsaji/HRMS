import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/auth/auth_types.dart';
import '../../core/auth/surface.dart';
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
    final selected = branches.contains(navigationShell.currentIndex) ? branches.indexOf(navigationShell.currentIndex) : 0;
    final employee = usesEmployeeSurface(user);
    final scheme = Theme.of(context).colorScheme;
    // On the employee surface Home is the root: Back from another tab returns to Home before it
    // leaves the app. Administrators keep the platform behaviour.
    final backToHome = employee && navigationShell.currentIndex != shellHomeBranch;
    return PopScope(
      canPop: !backToHome,
      onPopInvokedWithResult: (didPop, _) {
        if (!didPop && backToHome) navigationShell.goBranch(shellHomeBranch);
      },
      child: Scaffold(
        body: Column(
          children: [
            if (status == 'PENDING_APPROVAL' || status == 'SUSPENDED') CompanyReadOnlyBanner(status: status!),
            Expanded(child: navigationShell),
          ],
        ),
        bottomNavigationBar: DecoratedBox(
          decoration: BoxDecoration(
            border: Border(top: BorderSide(color: scheme.outlineVariant.withValues(alpha: 0.5))),
            // The navy lift belongs to the administrator chrome; the employee surface is flat.
            boxShadow: employee ? null : [BoxShadow(color: AppBrand.navy.withValues(alpha: 0.06), blurRadius: 20, offset: const Offset(0, -4))],
          ),
          // Tab labels are one short word each: past about 1.15x they break mid-word on a 320 dp phone, so
          // the bar (only) stops growing there. Every screen's own text keeps the full scale.
          child: MediaQuery.withClampedTextScaling(maxScaleFactor: 1.15, child: NavigationBar(
            selectedIndex: selected,
            labelBehavior: NavigationDestinationLabelBehavior.alwaysShow,
            onDestinationSelected: (index) {
              HapticFeedback.selectionClick();
              final branch = branches[index];
              navigationShell.goBranch(branch, initialLocation: branch == navigationShell.currentIndex);
            },
            destinations: [for (final branch in branches) (employee ? _employeeDestinations : _destinations)[branch]],
          )),
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

/// Same four tabs on the employee surface: Home and Leave get their own glyphs (redesign §3.3).
const _employeeDestinations = [
  NavigationDestination(icon: Icon(Icons.grid_view_outlined), selectedIcon: Icon(Icons.grid_view_rounded), label: 'Dashboard'),
  NavigationDestination(icon: Icon(Icons.fingerprint_rounded), selectedIcon: Icon(Icons.fingerprint_rounded), label: 'Attendance'),
  NavigationDestination(icon: Icon(Icons.event_available_outlined), selectedIcon: Icon(Icons.event_available_rounded), label: 'Leave'),
  NavigationDestination(icon: Icon(Icons.account_circle_outlined), selectedIcon: Icon(Icons.account_circle_rounded), label: 'Profile'),
];

/// The shell branch indexes to show as tabs, in order. All four, for everyone: the Home tab is
/// the company dashboard for an administrator, the employee Home for a user with an employee
/// record, and the existing explanatory page for a user with neither (`app_router.dart` decides
/// which route inside branch 0 applies).
List<int> visibleShellBranches(UserProfile? user) => [for (var i = 0; i < _shellBranchCount; i++) i];

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
