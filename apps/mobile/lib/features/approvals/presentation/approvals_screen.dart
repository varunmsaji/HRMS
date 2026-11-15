import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../core/time.dart' show relativeTime;
import '../../../core/widgets/ui.dart';
import '../../auth/state/auth_controller.dart';
import '../data/approvals_repository.dart';

/// Waiting-for-a-decision count for the Home and Dashboard cards; null while unknown or when the
/// user approves nothing. Invalidate it after deciding something.
final pendingApprovalsCountProvider = FutureProvider.autoDispose<int?>((ref) async {
  final user = ref.watch(authControllerProvider).user;
  final permissions = user?.permissions ?? const <String>[];
  if (!canApproveAnything(permissions)) return null;
  return ref.watch(approvalsRepositoryProvider).count(permissions, myEmployeeId: user?.employeeId);
});

/// The approvals inbox (MOB-UX-001): every request this user may decide — leave, attendance
/// corrections, overtime and onboarding review — in one place, newest first within each kind. A row
/// opens the request itself, where the existing approve/reject step runs; "See all" opens that
/// kind's full screen with its filters and decision centre.
class ApprovalsScreen extends ConsumerStatefulWidget {
  const ApprovalsScreen({super.key});

  @override
  ConsumerState<ApprovalsScreen> createState() => _ApprovalsScreenState();
}

class _ApprovalsScreenState extends ConsumerState<ApprovalsScreen> {
  List<ApprovalQueue>? _queues;
  bool _loading = true;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    setState(() => _loading = _queues == null);
    final user = ref.read(authControllerProvider).user;
    final queues = await ref.read(approvalsRepositoryProvider).load(user?.permissions ?? const <String>[], myEmployeeId: user?.employeeId);
    if (!mounted) return;
    setState(() {
      _queues = queues;
      _loading = false;
    });
    ref.invalidate(pendingApprovalsCountProvider);
  }

  Future<void> _open(String route) async {
    await context.push(route);
    if (mounted) _load();
  }

  @override
  Widget build(BuildContext context) {
    final queues = _queues;
    Widget body;
    if (_loading || queues == null) {
      body = const ListSkeleton(count: 5);
    } else if (queues.isEmpty) {
      body = const StateMessage(
        icon: Icons.lock_outline_rounded,
        tone: Tone.warning,
        title: 'Nothing to approve',
        message: 'Your account does not approve any requests.',
      );
    } else {
      final waiting = queues.fold<int>(0, (s, q) => s + q.total);
      final anyFailed = queues.any((q) => q.failed);
      body = RefreshIndicator(
        onRefresh: _load,
        child: ListView(
          physics: const AlwaysScrollableScrollPhysics(),
          padding: const EdgeInsets.fromLTRB(16, 8, 16, 32),
          children: [
            if (waiting == 0 && !anyFailed)
              const Padding(
                padding: EdgeInsets.only(top: 48),
                child: StateMessage(icon: Icons.task_alt_rounded, tone: Tone.success, title: 'You\'re all caught up', message: 'Nothing is waiting for your decision.'),
              )
            else
              for (final q in queues) ...[
                if (q.failed || q.total > 0) _Section(queue: q, onOpen: _open, onRetry: _load),
              ],
          ],
        ),
      );
    }
    return Scaffold(appBar: AppBar(title: const Text('Approvals')), body: body);
  }
}

String _kindTitle(ApprovalKind kind) => switch (kind) {
      ApprovalKind.leave => 'Leave',
      ApprovalKind.correction => 'Attendance corrections',
      ApprovalKind.overtime => 'Overtime',
      ApprovalKind.onboarding => 'Onboarding',
    };

IconData _kindIcon(ApprovalKind kind) => switch (kind) {
      ApprovalKind.leave => Icons.event_busy_outlined,
      ApprovalKind.correction => Icons.edit_note_rounded,
      ApprovalKind.overtime => Icons.more_time_outlined,
      ApprovalKind.onboarding => Icons.person_add_alt_outlined,
    };

class _Section extends StatelessWidget {
  const _Section({required this.queue, required this.onOpen, required this.onRetry});

  final ApprovalQueue queue;
  final Future<void> Function(String route) onOpen;
  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final muted = theme.colorScheme.onSurfaceVariant;
    final shown = queue.items.length;
    return Padding(
      padding: const EdgeInsets.only(bottom: 20),
      child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        Row(children: [
          Icon(_kindIcon(queue.kind), size: 20, color: theme.colorScheme.primary),
          const SizedBox(width: 8),
          Expanded(
            child: Semantics(
              header: true,
              child: Text(
                queue.failed ? _kindTitle(queue.kind) : '${_kindTitle(queue.kind)} · ${queue.total}',
                style: theme.textTheme.titleMedium?.copyWith(fontWeight: FontWeight.w700),
              ),
            ),
          ),
          if (!queue.failed) TextButton(onPressed: () => onOpen(listRouteFor(queue.kind)), child: const Text('See all')),
        ]),
        const SizedBox(height: 6),
        if (queue.failed)
          AppCard(
            child: Row(children: [
              Expanded(child: Text('Couldn\'t load these requests.', style: TextStyle(color: muted))),
              TextButton(onPressed: onRetry, child: const Text('Try again')),
            ]),
          )
        else ...[
          for (final item in queue.items)
            Padding(
              padding: const EdgeInsets.only(bottom: 10),
              child: ListRowCard(
                leading: InitialsAvatar(name: item.name ?? item.title),
                title: item.name == null || item.name!.isEmpty ? item.title : '${item.name} · ${item.title}',
                subtitle: [item.subtitle, if (item.at.isNotEmpty) relativeTime(item.at)].where((s) => s.isNotEmpty).join(' · '),
                onTap: () => onOpen(item.route),
              ),
            ),
          if (queue.total > shown && shown > 0)
            Text('Showing the newest $shown of ${queue.total}. See all to filter the rest.', style: theme.textTheme.bodySmall?.copyWith(color: muted)),
        ],
      ]),
    );
  }
}
