import 'package:flutter/material.dart';

import '../../../core/theme/employee_tokens.dart';
import '../../../core/widgets/employee/layout.dart';
import '../../leave/data/leave_repository.dart';
import '../state/home_providers.dart';

/// "12 – 14 Nov" or "12 Nov" for an ISO date range.
String shortDateRange(String startIso, String endIso) {
  const mo = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  final s = DateTime.tryParse(startIso);
  final e = DateTime.tryParse(endIso);
  if (s == null || e == null) return startIso == endIso ? startIso : '$startIso – $endIso';
  if (startIso == endIso) return '${s.day} ${mo[s.month - 1]}';
  if (s.month == e.month) return '${s.day} – ${e.day} ${mo[e.month - 1]}';
  return '${s.day} ${mo[s.month - 1]} – ${e.day} ${mo[e.month - 1]}';
}

/// A leave decision the employee has not dismissed yet. Fed by the application's own
/// `reviewed_at` (there is no notification feed), so it only appears for a recent decision.
class DecisionBanner extends StatelessWidget {
  const DecisionBanner({super.key, required this.application, required this.onView, required this.onDismiss});

  final LeaveApplication application;
  final VoidCallback onView;
  final VoidCallback onDismiss;

  @override
  Widget build(BuildContext context) {
    final t = EmployeeTokens.of(context);
    final theme = Theme.of(context);
    final verb = application.status == 'APPROVED' ? 'approved' : 'rejected';
    return Container(
      margin: const EdgeInsets.fromLTRB(16, 8, 16, 0),
      padding: const EdgeInsets.fromLTRB(12, 12, 4, 8),
      decoration: BoxDecoration(color: t.actionSubtle, borderRadius: BorderRadius.circular(EmployeeTokens.radiusSurface)),
      child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Padding(padding: const EdgeInsets.only(top: 2), child: Icon(Icons.info_outline, size: 20, color: t.action)),
        const SizedBox(width: 12),
        Expanded(
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text('Your leave request was $verb for ${shortDateRange(application.startDate, application.endDate)}.', style: theme.textTheme.bodyMedium?.copyWith(color: t.ink)),
            InkWell(
              onTap: onView,
              child: Padding(
                padding: const EdgeInsets.symmetric(vertical: 8),
                child: Text('View details →', style: theme.textTheme.labelLarge?.copyWith(color: t.action, fontWeight: FontWeight.w600)),
              ),
            ),
          ]),
        ),
        IconButton(onPressed: onDismiss, tooltip: 'Dismiss', icon: Icon(Icons.close, size: 20, color: t.inkSecondary)),
      ]),
    );
  }
}

/// "Shift assigned" and "Work location", side by side. A card whose fact is unknown is omitted.
class WorkProfileCards extends StatelessWidget {
  const WorkProfileCards({super.key, required this.profile});
  final HomeWorkProfile profile;

  @override
  Widget build(BuildContext context) {
    final cards = <Widget>[
      if (profile.shiftName != null)
        _WorkCard(
          icon: Icons.schedule,
          label: 'Shift assigned',
          title: profile.shiftName!,
          detail: profile.shiftStart != null && profile.shiftEnd != null ? '${profile.shiftStart} – ${profile.shiftEnd}' : null,
        ),
      if (profile.locationName != null)
        _WorkCard(icon: Icons.apartment_outlined, label: 'Work location', title: profile.locationName!, detail: profile.locationDetail),
    ];
    if (cards.isEmpty) return const SizedBox.shrink();
    return Padding(
      padding: const EdgeInsets.fromLTRB(16, 12, 16, 0),
      child: IntrinsicHeight(
        child: Row(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          for (var i = 0; i < cards.length; i++) ...[
            if (i > 0) const SizedBox(width: 12),
            Expanded(child: cards[i]),
          ],
        ]),
      ),
    );
  }
}

class _WorkCard extends StatelessWidget {
  const _WorkCard({required this.icon, required this.label, required this.title, this.detail});
  final IconData icon;
  final String label;
  final String title;
  final String? detail;

  @override
  Widget build(BuildContext context) {
    final t = EmployeeTokens.of(context);
    final theme = Theme.of(context);
    return Semantics(
      container: true,
      label: '$label: $title${detail == null ? '' : ', $detail'}',
      excludeSemantics: true,
      child: Container(
        padding: const EdgeInsets.all(12),
        decoration: BoxDecoration(color: t.sheet, borderRadius: BorderRadius.circular(EmployeeTokens.radiusSurface), border: Border.all(color: t.line)),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Row(children: [
            Icon(icon, size: 14, color: t.inkSecondary),
            const SizedBox(width: 6),
            Expanded(child: Text(label.toUpperCase(), style: theme.textTheme.labelSmall?.copyWith(color: t.inkSecondary), maxLines: 1, overflow: TextOverflow.ellipsis)),
          ]),
          const SizedBox(height: 8),
          Text(title, style: theme.textTheme.titleSmall?.copyWith(fontWeight: FontWeight.w700, color: t.ink), maxLines: 2, overflow: TextOverflow.ellipsis),
          if (detail != null) ...[
            const SizedBox(height: 2),
            Text(detail!, style: theme.textTheme.bodySmall?.copyWith(color: t.inkSecondary), maxLines: 2, overflow: TextOverflow.ellipsis),
          ],
        ]),
      ),
    );
  }
}

class QuickAction {
  const QuickAction({required this.label, required this.icon, required this.onTap});
  final String label;
  final IconData icon;
  final VoidCallback onTap;
}

/// Two-column grid of shortcuts. The caller decides which to offer from the user's permissions.
class QuickActionsGrid extends StatelessWidget {
  const QuickActionsGrid({super.key, required this.actions});
  final List<QuickAction> actions;

  @override
  Widget build(BuildContext context) {
    final t = EmployeeTokens.of(context);
    final theme = Theme.of(context);
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 16),
      child: LayoutBuilder(builder: (context, c) {
        final w = (c.maxWidth - 12) / 2;
        return Wrap(spacing: 12, runSpacing: 12, children: [
          for (final a in actions)
            SizedBox(
              width: w,
              child: Material(
                color: t.sheet,
                shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(EmployeeTokens.radiusSurface), side: BorderSide(color: t.line)),
                child: InkWell(
                  borderRadius: BorderRadius.circular(EmployeeTokens.radiusSurface),
                  onTap: a.onTap,
                  child: ConstrainedBox(
                    constraints: const BoxConstraints(minHeight: 88),
                    child: Padding(
                      padding: const EdgeInsets.all(12),
                      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                        Container(
                          padding: const EdgeInsets.all(8),
                          decoration: BoxDecoration(color: t.actionSubtle, borderRadius: BorderRadius.circular(8)),
                          child: Icon(a.icon, size: 20, color: t.action),
                        ),
                        const SizedBox(height: 12),
                        Text(a.label, style: theme.textTheme.titleSmall?.copyWith(fontWeight: FontWeight.w600, color: t.ink)),
                      ]),
                    ),
                  ),
                ),
              ),
            ),
        ]);
      }),
    );
  }
}

/// One leave type: name, balance out of what was credited this year, and a bar for what is left.
class LeaveBalanceBars extends StatelessWidget {
  const LeaveBalanceBars({super.key, required this.items});
  final List<({String name, num balance, num? total})> items;

  static String _fmt(num n) => n == n.roundToDouble() ? n.toInt().toString() : n.toString();

  @override
  Widget build(BuildContext context) {
    final t = EmployeeTokens.of(context);
    final theme = Theme.of(context);
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 16),
      child: LayoutBuilder(builder: (context, c) {
        final cols = items.length.clamp(1, 3);
        final w = (c.maxWidth - 12 * (cols - 1)) / cols;
        return Wrap(spacing: 12, runSpacing: 12, children: [
          for (final i in items)
            SizedBox(
              width: w,
              child: Semantics(
                container: true,
                label: '${i.name}: ${_fmt(i.balance)}${i.total == null ? '' : ' of ${_fmt(i.total!)}'} days',
                excludeSemantics: true,
                child: Container(
                  padding: const EdgeInsets.all(12),
                  decoration: BoxDecoration(color: t.sheet, borderRadius: BorderRadius.circular(EmployeeTokens.radiusSurface), border: Border.all(color: t.line)),
                  child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                    Text(i.name, style: theme.textTheme.bodySmall?.copyWith(color: t.inkSecondary), maxLines: 1, overflow: TextOverflow.ellipsis),
                    const SizedBox(height: 4),
                    Text.rich(TextSpan(children: [
                      TextSpan(text: _fmt(i.balance), style: theme.textTheme.titleLarge?.copyWith(fontWeight: FontWeight.w700, color: t.ink)),
                      if (i.total != null) TextSpan(text: ' /${_fmt(i.total!)}d', style: theme.textTheme.bodySmall?.copyWith(color: t.inkSecondary)),
                    ])),
                    if (i.total != null && i.total! > 0) ...[
                      const SizedBox(height: 8),
                      ClipRRect(
                        borderRadius: BorderRadius.circular(4),
                        child: LinearProgressIndicator(value: (i.balance / i.total!).clamp(0, 1).toDouble(), minHeight: 6, backgroundColor: t.line, color: t.action),
                      ),
                      const SizedBox(height: 6),
                      Text('${(i.balance / i.total! * 100).round()}% remaining', style: theme.textTheme.labelSmall?.copyWith(color: t.inkSecondary)),
                    ],
                  ]),
                ),
              ),
            ),
        ]);
      }),
    );
  }
}

/// Newest-first activity, each a one-line fact the server already holds.
class RecentActivityList extends StatelessWidget {
  const RecentActivityList({super.key, required this.items});
  final List<HomeActivity> items;

  @override
  Widget build(BuildContext context) {
    final t = EmployeeTokens.of(context);
    final theme = Theme.of(context);
    return EmployeeListGroup(children: [
      for (final a in items)
        Padding(
          padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
          child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Container(
              padding: const EdgeInsets.all(6),
              decoration: BoxDecoration(color: t.actionSubtle, shape: BoxShape.circle),
              child: Icon(a.icon, size: 16, color: t.action),
            ),
            const SizedBox(width: 12),
            Expanded(
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Text(a.title, style: theme.textTheme.bodyMedium?.copyWith(fontWeight: FontWeight.w600, color: t.ink)),
                Text(a.caption, style: theme.textTheme.bodySmall?.copyWith(color: t.inkSecondary)),
              ]),
            ),
          ]),
        ),
    ]);
  }
}
