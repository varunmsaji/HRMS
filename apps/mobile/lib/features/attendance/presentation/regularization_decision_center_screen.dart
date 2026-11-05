import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/providers.dart';
import '../../../core/requests/decision_center_view.dart';
import '../../../core/requests/request_screens.dart';
import '../../../core/theme/employee_theme_scope.dart';
import '../../../core/time.dart';
import '../../../core/widgets/ui.dart';
import '../../auth/state/auth_controller.dart';
import '../domain/regularization_decision_center.dart';
import '../domain/request_resources.dart';

/// The approver's attendance-correction screen — mirrors the web
/// `regularization/decision-center.tsx`: what the system recorded beside what is being asked for.
/// Deciding reuses the review step on the detail screen.
class RegularizationDecisionCenterPanel extends ConsumerWidget {
  const RegularizationDecisionCenterPanel({super.key, this.now});

  /// Overrides the clock (tests). Null = now.
  final DateTime? now;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final me = ref.watch(authControllerProvider).user?.employeeId;
    final zone = ref.watch(authControllerProvider).user?.companyTimezone ?? 'Asia/Kolkata';
    return DecisionCenterView<RegularizationDecisionCenter>(
      tabs: const [('pending', 'Pending review'), ('approved', 'Approved history'), ('declined', 'Declined')],
      load: (tab) => ref.read(apiClientProvider).get('/regularizations/decision-center?tab=$tab', parse: (d) => RegularizationDecisionCenter.fromJson(d as Map<String, dynamic>)),
      count: (d, tab) => d.counts[tab] ?? 0,
      forbiddenMessage: 'You do not have permission to review regularizations.',
      narrowHint: 'Use Team to filter further.',
      emptyIcon: Icons.edit_note,
      stats: (d) => [
        DecisionStat('Pending decisions', '${d.pendingCount}', needsAction: d.pendingCount > 0, note: d.oldestPendingAt == null ? 'Nothing waiting' : 'Oldest submitted ${relativeTime(d.oldestPendingAt!, now: now)}'),
        DecisionStat('Regularization rate (last 30 days)', d.windowRatePct == null ? '—' : '${d.windowRatePct}%', note: '${d.windowRegularizedDays} of ${d.windowExpectedDays} working days regularized'),
        DecisionStat('Approved / declined', '${d.counts['approved'] ?? 0} / ${d.counts['declined'] ?? 0}', note: 'All time, within your access'),
      ],
      cards: (context, d, reload) => [for (final item in d.items) _RegularizationCard(item: item, canReview: item.employeeId != me, zone: item.timezone ?? zone, now: now, reload: reload)],
    );
  }
}

class _RegularizationCard extends StatelessWidget {
  const _RegularizationCard({required this.item, required this.canReview, required this.zone, required this.now, required this.reload});
  final RegularizationDecisionItem item;
  final bool canReview;
  final String zone;
  final DateTime? now;
  final VoidCallback reload;

  Future<void> _open(BuildContext context, {bool? review}) async {
    await pushKeepingTheme<void>(context, (_) => RequestDetailScreen(config: regularizationConfig, requestId: item.id, reviewOnOpen: review));
    reload();
  }

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final where = [item.designation, item.department].whereType<String>().join(' • ');
    final reqIn = item.requestedTime('IN');
    final reqOut = item.requestedTime('OUT');
    final status = item.recordedStatus == null ? 'not recorded' : item.recordedStatus!.replaceAll('_', ' ').toLowerCase();
    final late = (item.recordedLateMinutes ?? 0) > 0 ? ' · ${item.recordedLateMinutes}m late' : '';
    Widget cells(List<(String, String, Color?)> values) => Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
          for (final (label, value, color) in values)
            Expanded(
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Text(label, style: TextStyle(fontSize: 11, color: scheme.onSurfaceVariant)),
                const SizedBox(height: 2),
                Text(value, style: TextStyle(fontSize: 13, fontWeight: FontWeight.w600, color: color)),
              ]),
            ),
        ]);
    return AppCard(
      child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        DecisionCardHeader(
          name: item.employeeName,
          code: item.employeeCode,
          lines: [
            where.isEmpty ? '—' : where,
            'Dispute: ${item.attendanceDate}${item.shiftName == null ? '' : ' · Shift: ${item.shiftName}'}',
            'Submitted ${relativeTime(item.submittedAt, now: now)}',
          ],
          status: StatusChip(label: item.isPending ? item.stageLabel : humanize(item.status), tone: item.isPending ? Tone.warning : toneForStatus(item.status)),
        ),
        const SizedBox(height: 12),
        DecisionBlock(title: 'Recorded by system', children: [
          cells([
            ('Punch in', formatClockTime(item.recordedFirstIn, zone), null),
            ('Punch out', item.recordedLastOut == null ? 'Missing' : formatClockTime(item.recordedLastOut, zone), item.recordedLastOut == null ? scheme.error : null),
            ('Worked', formatMinutes(item.recordedWorkedMinutes), null),
          ]),
          const SizedBox(height: 6),
          Text('Status $status$late', style: TextStyle(fontSize: 12, color: scheme.onSurfaceVariant)),
        ]),
        const SizedBox(height: 8),
        DecisionBlock(title: 'Requested correction', trailing: regularizationTypeLabels[item.requestType] ?? item.requestType, children: [
          cells([
            ('Punch in', reqIn == null ? 'No change' : formatClockTime(reqIn, zone), null),
            ('Punch out', reqOut == null ? 'No change' : formatClockTime(reqOut, zone), null),
            ('Projected', item.requestedSpanMinutes == null ? '—' : formatMinutes(item.requestedSpanMinutes), null),
          ]),
          const SizedBox(height: 6),
          Text('Projected is the span between the first in and last out; final hours are recalculated on approval.', style: TextStyle(fontSize: 12, color: scheme.onSurfaceVariant)),
        ]),
        if (item.reason != null) ...[
          const SizedBox(height: 8),
          Text('Employee reason: “${item.reason}”', style: const TextStyle(fontSize: 13)),
        ],
        const SizedBox(height: 8),
        DecisionCardFooter(
          detailsLabel: 'View full audit trail',
          onDetails: () => _open(context),
          approveLabel: 'Approve',
          onDecline: item.isPending && canReview ? () => _open(context, review: false) : null,
          onApprove: item.isPending && canReview ? () => _open(context, review: true) : null,
        ),
      ]),
    );
  }
}
