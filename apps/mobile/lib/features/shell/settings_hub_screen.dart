import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';

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

class SettingsHubScreen extends StatelessWidget {
  const SettingsHubScreen({super.key});

  @override
  Widget build(BuildContext context) {
    final groups = [_quickLinks, ..._settingsGroups];
    return Scaffold(
      appBar: AppBar(title: const Text('More')),
      body: ListView.builder(
        padding: const EdgeInsets.symmetric(vertical: 8),
        itemCount: groups.length,
        itemBuilder: (context, groupIndex) {
          final group = groups[groupIndex];
          return Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Padding(
                padding: const EdgeInsets.fromLTRB(16, 16, 16, 4),
                child: Text(
                  group.label.toUpperCase(),
                  style: Theme.of(context).textTheme.labelSmall?.copyWith(
                        color: Theme.of(context).colorScheme.onSurfaceVariant,
                        letterSpacing: 0.6,
                      ),
                ),
              ),
              for (final item in group.items)
                ListTile(
                  leading: Icon(item.icon),
                  title: Text(item.label),
                  trailing: const Icon(Icons.chevron_right, size: 20),
                  onTap: () => context.push(item.route),
                ),
            ],
          );
        },
      ),
    );
  }
}
