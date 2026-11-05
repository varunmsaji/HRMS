import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/requests/decision_center_view.dart';
import '../../../core/theme/employee_theme_scope.dart';
import '../../../core/time.dart';
import '../../../core/widgets/ui.dart';
import '../../auth/state/auth_controller.dart';
import '../data/leave_repository.dart';
import '../domain/leave_decision_center.dart';
import 'leave_application_detail_screen.dart';

/// The approver's leave screen — mirrors the web `leave-application/decision-center.tsx`. Deciding
/// reuses the review step on the detail screen, so its rules (loss of pay, approver checks) stay in
/// one place.
class LeaveDecisionCenterPanel extends ConsumerWidget {
  const LeaveDecisionCenterPanel({super.key, this.now});

  /// Overrides the clock (tests). Null = now.
  final DateTime? now;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final me = ref.watch(authControllerProvider).user?.employeeId;
    return DecisionCenterView<LeaveDecisionCenter>(
      tabs: const [('pending', 'Pending approvals'), ('approved', 'Approved leaves'), ('declined', 'Declined & cancelled')],
      load: (tab) => ref.read(leaveRepositoryProvider).getDecisionCenter(tab),
      count: (d, tab) => d.counts[tab] ?? 0,
      forbiddenMessage: 'You do not have permission to review leave requests.',
      narrowHint: 'Use Team to filter further.',
      emptyIcon: Icons.event_busy_outlined,
      stats: (d) {
        final byType = d.onLeaveTodayByType.map((t) => '${t.$2} ${t.$1.replaceFirst(RegExp(r' Leave$'), '')}').join(', ');
        return [
          DecisionStat('Pending requests', '${d.pendingCount}', needsAction: d.pendingCount > 0, note: d.oldestPendingAt == null ? 'Nothing waiting' : 'Oldest submitted ${relativeTime(d.oldestPendingAt!, now: now)}'),
          DecisionStat('On leave today', '${d.onLeaveToday}', note: '${byType.isEmpty ? 'Everyone is in' : byType} · ${d.activeStaff} active staff'),
          DecisionStat('Approved starts, next 7 days', '${d.upcomingStarts7d}', note: d.peakDay == null ? 'No approved leave in the next 7 days' : 'Peak absence: ${d.peakDay} (${d.peakDayAway} away)'),
          DecisionStat('Staff available today', d.availablePct == null ? '—' : '${d.availablePct!.round()}%', note: '${d.onLeaveToday} of ${d.activeStaff} on leave'),
        ];
      },
      cards: (context, d, reload) => [for (final item in d.items) _LeaveCard(item: item, canReview: item.employeeId != me, now: now, reload: reload)],
    );
  }
}

class _LeaveCard extends StatelessWidget {
  const _LeaveCard({required this.item, required this.canReview, required this.now, required this.reload});
  final LeaveDecisionItem item;
  final bool canReview;
  final DateTime? now;
  final VoidCallback reload;

  Future<void> _open(BuildContext context, {bool? review}) async {
    await pushKeepingTheme<void>(context, (_) => LeaveApplicationDetailScreen(applicationId: item.id, reviewOnOpen: review));
    reload();
  }

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final clash = item.clash;
    final paid = item.totalDays - item.lopDays;
    final negative = (item.postApprovalBalance ?? 0) < 0;
    final where = [item.designation, item.department].whereType<String>().join(' • ');
    Widget row(String label, String value, {Color? color}) => Padding(
          padding: const EdgeInsets.symmetric(vertical: 2),
          child: Row(children: [
            Expanded(child: Text(label, style: TextStyle(fontSize: 13, color: scheme.onSurfaceVariant))),
            Text(value, style: TextStyle(fontWeight: FontWeight.w600, color: color)),
          ]),
        );
    return AppCard(
      child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        DecisionCardHeader(
          name: item.employeeName,
          code: item.employeeCode,
          lines: [where.isEmpty ? '—' : where, 'Submitted ${relativeTime(item.submittedAt, now: now)}'],
          status: StatusChip(label: item.isPending ? 'Pending approval' : humanize(item.status), tone: item.isPending ? Tone.warning : toneForStatus(item.status)),
        ),
        const SizedBox(height: 12),
        DecisionBlock(title: 'Leave particulars', children: [
          Text('${item.leaveType} · ${formatDays(item.totalDays)} ${item.totalDays == 1 ? 'day' : 'days'}', style: const TextStyle(fontWeight: FontWeight.w600)),
          const SizedBox(height: 2),
          Text(item.endDate == item.startDate ? item.startDate : '${item.startDate} – ${item.endDate}', style: TextStyle(fontSize: 13, color: scheme.onSurfaceVariant)),
          if (item.reason != null) Padding(padding: const EdgeInsets.only(top: 6), child: Text('Reason: “${item.reason}”', style: const TextStyle(fontSize: 13))),
        ]),
        if (item.isPending && item.currentBalance != null) ...[
          const SizedBox(height: 8),
          DecisionBlock(title: 'Balance deduction', children: [
            row('Current balance', '${formatDays(item.currentBalance)} days'),
            row('Requested deduction', '−${formatDays(paid)} days', color: scheme.error),
            const Divider(height: 12),
            row('Post-approval balance', '${formatDays(item.postApprovalBalance)} days', color: negative ? scheme.error : null),
            const SizedBox(height: 4),
            Text(item.lopDays > 0 ? '${formatDays(item.lopDays)} ${item.lopDays == 1 ? 'day' : 'days'} will be treated as loss of pay.' : 'Covered by the available balance.', style: const TextStyle(fontSize: 12)),
          ]),
        ],
        if (item.isPending) ...[
          const SizedBox(height: 8),
          Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Icon(clash.clash ? Icons.warning_amber_rounded : Icons.check_circle_outline_rounded, size: 18, color: clash.clash ? scheme.error : scheme.primary),
            const SizedBox(width: 6),
            Expanded(child: Text(clash.text, style: const TextStyle(fontSize: 13))),
          ]),
        ],
        const SizedBox(height: 8),
        DecisionCardFooter(
          detailsLabel: 'View details',
          onDetails: () => _open(context),
          approveLabel: 'Approve leave',
          onDecline: item.isPending && canReview ? () => _open(context, review: false) : null,
          onApprove: item.isPending && canReview ? () => _open(context, review: true) : null,
        ),
      ]),
    );
  }
}
