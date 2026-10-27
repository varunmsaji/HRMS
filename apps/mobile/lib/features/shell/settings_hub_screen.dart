import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';

import '../../core/theme/app_theme.dart';
import '../../core/widgets/ui.dart';

class _HubItem {
  const _HubItem(this.label, this.icon, this.route);
  final String label;
  final IconData icon;
  final String route;
}

class _HubGroup {
  const _HubGroup(this.label, this.items);
  final String label;
  final List<_HubItem> items;
}

/// Mirrors `apps/web/src/components/layout/nav-items.ts`'s `NAV_ITEMS` (the
/// items not already in the bottom nav) plus `SETTINGS_NAV_GROUPS` in full —
/// the single navigation hub for everything that doesn't fit the 4-tab
/// bottom nav. Reached via the "More" action on each tab's app bar.
const _quickLinks = _HubGroup('Quick links', [
  _HubItem('Employees', Icons.people_outline, '/app/employees'),
  _HubItem('Onboarding', Icons.person_add_alt, '/app/onboarding'),
  _HubItem('Team Attendance', Icons.groups_outlined, '/app/team-attendance'),
  _HubItem('Attendance Insights', Icons.insights_outlined, '/app/attendance-insights'),
  _HubItem('Shift Rosters', Icons.event_available, '/app/rosters'),
  _HubItem('Regularizations', Icons.edit_note, '/app/regularizations'),
  _HubItem('Overtime', Icons.alarm_on_outlined, '/app/overtime'),
  _HubItem('Leave Balances', Icons.account_balance_wallet_outlined, '/app/leave-balances'),
  _HubItem('Payroll', Icons.payments_outlined, '/app/payroll/pay-runs'),
  _HubItem('My Payslips', Icons.description_outlined, '/app/me/payslips'),
]);

const _settingsGroups = [
  _HubGroup('Organisation', [
    _HubItem('Company', Icons.apartment_outlined, '/app/company'),
    _HubItem('Branches', Icons.business_outlined, '/app/branches'),
    _HubItem('Departments', Icons.account_tree_outlined, '/app/departments'),
    _HubItem('Designations', Icons.work_outline, '/app/designations'),
    _HubItem('Grades', Icons.layers_outlined, '/app/grades'),
    _HubItem('Legal Entities', Icons.gavel_outlined, '/app/legal-entities'),
  ]),
  _HubGroup('Attendance & Time', [
    _HubItem('Shifts', Icons.schedule_outlined, '/app/shifts'),
    _HubItem('Attendance Periods', Icons.lock_clock_outlined, '/app/attendance-periods'),
    _HubItem('Roster Calendar', Icons.calendar_view_month_outlined, '/app/roster-calendar'),
    _HubItem('Work Calendars', Icons.date_range_outlined, '/app/work-calendars'),
    _HubItem('Holiday Calendars', Icons.calendar_month_outlined, '/app/holiday-calendars'),
    _HubItem('Weekly-Off Patterns', Icons.event_busy_outlined, '/app/weekly-off-patterns'),
    _HubItem('Attendance Policies', Icons.assignment_outlined, '/app/attendance-policies'),
    _HubItem('Overtime Policies', Icons.timer_outlined, '/app/overtime-policies'),
    _HubItem('Regularization Policies', Icons.history_edu_outlined, '/app/regularization-policies'),
  ]),
  _HubGroup('Leave', [
    _HubItem('Leave Types', Icons.sell_outlined, '/app/leave-types'),
    _HubItem('Leave Policies', Icons.assignment_turned_in_outlined, '/app/leave-policies'),
    _HubItem('Leave Combination Rules', Icons.merge_type_outlined, '/app/leave-combination-rules'),
    _HubItem('Leave Year', Icons.event_repeat_outlined, '/app/leave-year-setting'),
    _HubItem('Statutory Minimums', Icons.balance_outlined, '/app/statutory-leave-minimums'),
  ]),
  _HubGroup('Payroll', [
    _HubItem('Salary Components', Icons.attach_money_outlined, '/app/payroll/salary-components'),
    _HubItem('Salary Structures', Icons.view_list_outlined, '/app/payroll/salary-structures'),
    _HubItem('Statutory Rates', Icons.account_balance_outlined, '/app/payroll/statutory-rates'),
  ]),
  _HubGroup('Policies', [
    _HubItem('Policy Assignments', Icons.link_outlined, '/app/policy-assignments'),
    _HubItem('Policy Resolution', Icons.search_outlined, '/app/policy-resolution'),
  ]),
  _HubGroup('Administration', [
    _HubItem('Setup', Icons.checklist_outlined, '/app/setup'),
    _HubItem('Users', Icons.manage_accounts_outlined, '/app/users'),
  ]),
];

class SettingsHubScreen extends StatefulWidget {
  const SettingsHubScreen({super.key});

  @override
  State<SettingsHubScreen> createState() => _SettingsHubScreenState();
}

class _SettingsHubScreenState extends State<SettingsHubScreen> {
  String _query = '';

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final query = _query.trim().toLowerCase();
    final searching = query.isNotEmpty;
    final matches = [
      for (final g in [_quickLinks, ..._settingsGroups])
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
            const SectionHeader('Quick links'),
            GridView.count(
              crossAxisCount: 2,
              shrinkWrap: true,
              physics: const NeverScrollableScrollPhysics(),
              mainAxisSpacing: 10,
              crossAxisSpacing: 10,
              childAspectRatio: 2.5,
              children: [for (final item in _quickLinks.items) _QuickTile(item: item)],
            ),
            for (final group in _settingsGroups) ...[
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
          ],
        ],
      ),
    );
  }
}

class _QuickTile extends StatelessWidget {
  const _QuickTile({required this.item});

  final _HubItem item;

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

  final List<_HubItem> items;
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
