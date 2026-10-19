import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

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
    final status = ref.watch(authControllerProvider).user?.companyStatus;
    return Scaffold(
      body: Column(
        children: [
          if (status == 'PENDING_APPROVAL' || status == 'SUSPENDED') CompanyReadOnlyBanner(status: status!),
          Expanded(child: navigationShell),
        ],
      ),
      bottomNavigationBar: NavigationBar(
        selectedIndex: navigationShell.currentIndex,
        onDestinationSelected: (index) => navigationShell.goBranch(
          index,
          initialLocation: index == navigationShell.currentIndex,
        ),
        destinations: const [
          NavigationDestination(icon: Icon(Icons.dashboard_outlined), selectedIcon: Icon(Icons.dashboard), label: 'Dashboard'),
          NavigationDestination(icon: Icon(Icons.calendar_month_outlined), selectedIcon: Icon(Icons.calendar_month), label: 'Attendance'),
          NavigationDestination(icon: Icon(Icons.beach_access_outlined), selectedIcon: Icon(Icons.beach_access), label: 'Leave'),
          NavigationDestination(icon: Icon(Icons.person_outline), selectedIcon: Icon(Icons.person), label: 'Profile'),
        ],
      ),
    );
  }
}

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
          padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
          child: Row(
            children: [
              Icon(Icons.lock_outline, size: 18, color: scheme.onTertiaryContainer),
              const SizedBox(width: 10),
              Expanded(
                child: Text(
                  pending
                      ? 'Your company is awaiting approval. You can view data, but changes are disabled.'
                      : 'Your company is suspended. You can view data, but changes are disabled.',
                  style: TextStyle(color: scheme.onTertiaryContainer, fontSize: 13),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
