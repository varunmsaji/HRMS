import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/auth/surface.dart';
import '../../core/nav/nav_entries.dart';
import '../../core/theme/app_theme.dart';
import '../../core/widgets/ui.dart';
import '../auth/state/auth_controller.dart';

class SettingsHubScreen extends ConsumerStatefulWidget {
  const SettingsHubScreen({super.key});

  @override
  ConsumerState<SettingsHubScreen> createState() => _SettingsHubScreenState();
}

class _SettingsHubScreenState extends ConsumerState<SettingsHubScreen> {
  String _query = '';

  Future<void> _confirmSignOut() async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Sign out?'),
        content: const Text('You will need to sign in again to use the app.'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('Cancel')),
          FilledButton(onPressed: () => Navigator.pop(ctx, true), child: const Text('Sign out')),
        ],
      ),
    );
    if (ok == true) await ref.read(authControllerProvider.notifier).logout();
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final query = _query.trim().toLowerCase();
    final searching = query.isNotEmpty;
    // What this user may open (core/nav/nav_entries.dart). An employee gets one short list in
    // employee wording; everyone else gets the existing structure minus what they cannot use.
    final user = ref.watch(authControllerProvider).user;
    final permissions = user?.permissions ?? const <String>[];
    final employeeMenu = usesEmployeeSurface(user);
    // An employee-surface user may also hold manager permissions (Employees, Team attendance, ...):
    // those entries follow the employee ones, using the same structure administrators see.
    final groups = employeeMenu
        ? [
            NavGroup('Your work', [for (final e in visibleEmployeeEntries(permissions)) NavEntry(e.employeeLabel ?? e.label, e.icon, e.route)]),
            for (final g in visibleNavGroups(permissions))
              if (g.items.any((e) => e.guarded)) NavGroup(g.label, [for (final e in g.items) if (e.guarded) e]),
          ]
        : visibleNavGroups(permissions);

    final matches = [
      for (final g in groups)
        for (final item in g.items)
          if (item.label.toLowerCase().contains(query) || g.label.toLowerCase().contains(query)) (g.label, item),
    ];

    return Scaffold(
      appBar: AppBar(title: const Text('More')),
      body: ListView(
        padding: const EdgeInsets.fromLTRB(16, 4, 16, 32),
        children: [
          AppSearchField(hint: 'Search settings and tools', onChanged: (v) => setState(() => _query = v)),
          const SizedBox(height: 20),
          if (searching) ...[
            if (matches.isEmpty)
              const Padding(
                padding: EdgeInsets.only(top: 48),
                child: StateMessage(icon: Icons.search_off_rounded, title: 'No matches', message: 'Try a different word.'),
              )
            else
              _GroupCard(items: [for (final m in matches) m.$2], subtitles: [for (final m in matches) m.$1]),
          ] else ...[
            for (final group in groups)
              if (employeeMenu && group == groups.first) ...[
                if (group.items.isNotEmpty) ...[
                  const SectionHeader('Your work'),
                  _GroupCard(items: group.items),
                ],
              ] else if (group.label == navQuickLinks.label) ...[
                  const SectionHeader('Quick links'),
                  GridView.count(
                    crossAxisCount: 2,
                    shrinkWrap: true,
                    physics: const NeverScrollableScrollPhysics(),
                    mainAxisSpacing: 10,
                    crossAxisSpacing: 10,
                    childAspectRatio: 2.5,
                    children: [for (final item in group.items) _QuickTile(item: item)],
                  ),
                ] else ...[
                  const SizedBox(height: 20),
                  Padding(
                    padding: const EdgeInsets.fromLTRB(4, 0, 4, 8),
                    child: Text(
                      group.label.toUpperCase(),
                      style: theme.textTheme.labelSmall?.copyWith(color: theme.colorScheme.onSurfaceVariant, letterSpacing: 0.8),
                    ),
                  ),
                  _GroupCard(items: group.items),
                ],
            const SizedBox(height: 24),
            AppCard(
              padding: EdgeInsets.zero,
              onTap: _confirmSignOut,
              child: Padding(
                padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 14),
                child: Row(
                  children: [
                    Icon(Icons.logout_rounded, color: theme.colorScheme.error),
                    const SizedBox(width: 14),
                    Text('Sign out', style: theme.textTheme.bodyLarge?.copyWith(fontWeight: FontWeight.w600, color: theme.colorScheme.error)),
                  ],
                ),
              ),
            ),
          ],
        ],
      ),
    );
  }
}

class _QuickTile extends StatelessWidget {
  const _QuickTile({required this.item});

  final NavEntry item;

  @override
  Widget build(BuildContext context) {
    return AppCard(
      padding: const EdgeInsets.all(12),
      onTap: () => context.push(item.route),
      child: Row(
        children: [
          IconBadge(icon: item.icon, size: 38),
          const SizedBox(width: 10),
          Expanded(
            child: Text(
              item.label,
              maxLines: 2,
              overflow: TextOverflow.ellipsis,
              style: Theme.of(context).textTheme.bodyMedium?.copyWith(fontWeight: FontWeight.w600, height: 1.2),
            ),
          ),
        ],
      ),
    );
  }
}

class _GroupCard extends StatelessWidget {
  const _GroupCard({required this.items, this.subtitles});

  final List<NavEntry> items;
  final List<String>? subtitles;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return AppCard(
      padding: EdgeInsets.zero,
      child: Column(
        children: [
          for (var i = 0; i < items.length; i++) ...[
            if (i > 0) Divider(height: 1, indent: 62, color: theme.colorScheme.outlineVariant.withValues(alpha: 0.5)),
            InkWell(
              borderRadius: i == 0
                  ? const BorderRadius.vertical(top: Radius.circular(AppRadii.card))
                  : i == items.length - 1
                      ? const BorderRadius.vertical(bottom: Radius.circular(AppRadii.card))
                      : BorderRadius.zero,
              onTap: () => context.push(items[i].route),
              child: Padding(
                padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 11),
                child: Row(
                  children: [
                    IconBadge(icon: items[i].icon, size: 34, tone: Tone.neutral),
                    const SizedBox(width: 14),
                    Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(items[i].label, style: theme.textTheme.bodyLarge?.copyWith(fontWeight: FontWeight.w500)),
                          if (subtitles != null)
                            Text(subtitles![i], style: theme.textTheme.bodySmall?.copyWith(color: theme.colorScheme.onSurfaceVariant)),
                        ],
                      ),
                    ),
                    Icon(Icons.chevron_right_rounded, size: 22, color: theme.colorScheme.outline),
                  ],
                ),
              ),
            ),
          ],
        ],
      ),
    );
  }
}
