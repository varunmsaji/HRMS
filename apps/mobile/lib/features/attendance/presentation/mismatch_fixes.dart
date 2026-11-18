import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../core/api/api_client.dart';
import '../../../core/api/api_error.dart';
import '../../../core/auth/permissions.dart';
import '../../../core/providers.dart';
import '../../../core/theme/app_colors.dart';
import '../../../core/time.dart';
import '../../auth/presentation/widgets/auth_form_field.dart';
import '../../auth/state/auth_controller.dart';
import '../data/attendance_repository.dart';
import '../domain/attendance_mismatch.dart';
import 'mark_attendance_screen.dart';

/// One thing HR can do about a mismatched day.
class RowFix {
  const RowFix(this.label, this.onPressed, {this.primary = false});
  final String label;
  final VoidCallback onPressed;
  final bool primary;
}

/// What is wrong with a day and how to settle it from the list.
class RowMismatch {
  const RowMismatch(this.reason, this.fixes);
  final String reason;
  final List<RowFix> fixes;
}

/// Opens the on-behalf punch form for [employeeId], already set to [direction] and [time] (a
/// wall-clock `YYYY-MM-DDTHH:mm` in the company zone). True when a punch was recorded.
typedef OpenPunch = Future<bool> Function({required String employeeId, required String direction, required String time});

/// Pending correction requests by `employee|date`, so a day the employee already asked to correct
/// is settled through that request rather than a second fix. Empty when they can't be loaded.
Future<Map<String, String>> loadPendingCorrections(WidgetRef ref) async {
  try {
    final client = ref.read(apiClientProvider);
    final out = <String, String>{};
    for (var page = 1; page <= 10; page++) {
      final env = await client.getList<Map<String, dynamic>>(
        '/regularizations',
        query: PageQuery(page: page, perPage: 100),
        filters: {'request_status': 'SUBMITTED'},
        parseItem: (d) => d as Map<String, dynamic>,
      );
      for (final r in env.data) {
        out['${r['employee_id']}|${r['attendance_date']}'] = r['id'] as String;
      }
      if (env.pagination == null || !env.pagination!.hasNext) break;
    }
    return out;
  } catch (_) {
    return const {};
  }
}

/// Asks for the reason to keep approved leave over punches; null when cancelled. Shared by the day
/// detail screen and the mismatch lists.
Future<String?> askKeepLeaveReason(BuildContext context) async {
  final reason = TextEditingController();
  String? error;
  final ok = await showDialog<bool>(
    context: context,
    builder:
        (ctx) => StatefulBuilder(
          builder:
              (ctx, setLocal) => AlertDialog(
                title: const Text('Keep leave'),
                content: Column(
                  mainAxisSize: MainAxisSize.min,
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    const Text('Confirms the approved leave stands over the punches recorded on this day.'),
                    const SizedBox(height: 12),
                    if (error != null) Padding(padding: const EdgeInsets.only(bottom: 8), child: Text(error!, style: TextStyle(color: Theme.of(ctx).colorScheme.error))),
                    AuthFormField(label: 'Reason', required: true, child: TextField(controller: reason)),
                  ],
                ),
                actions: [
                  TextButton(onPressed: () => Navigator.of(ctx).pop(false), child: const Text('Cancel')),
                  FilledButton(
                    onPressed: () {
                      if (reason.text.trim().isEmpty) return setLocal(() => error = 'A reason is required.');
                      Navigator.of(ctx).pop(true);
                    },
                    child: const Text('Keep leave'),
                  ),
                ],
              ),
        ),
  );
  // Not disposed here: the dialog is still animating out and its field reads the controller.
  return ok == true ? reason.text.trim() : null;
}

/// Builds, for each mismatched day, the one-line reason and the fixes this viewer may use.
/// Mirrors the web list's `mismatchFor`. [onChanged] runs after any fix so the list reloads.
class MismatchFixer {
  MismatchFixer({required this.context, required this.ref, required this.nameOf, required this.pending, required this.openPunch, required this.openDay, required this.onChanged});

  final BuildContext context;
  final WidgetRef ref;
  final String Function(String employeeId) nameOf;

  /// `employee|date` -> request id, from [loadPendingCorrections].
  final Map<String, String> pending;
  final OpenPunch openPunch;
  final void Function(AttendanceDay day) openDay;
  final VoidCallback onChanged;

  String get _zone => ref.read(authControllerProvider).user?.companyTimezone ?? 'Asia/Kolkata';

  /// Starts from the shift's own start or end, but never a moment that has not happened yet.
  String _punchTime(AttendanceDay day, String direction) {
    final scheduled = day.raw[direction == 'IN' ? 'scheduled_start' : 'scheduled_end'] as String?;
    final now = nowInZoneForInput(_zone);
    var time = '${day.attendanceDate}T${direction == 'IN' ? '09:00' : '18:00'}';
    if (scheduled != null) {
      final t = inZone(DateTime.parse(scheduled), _zone);
      String two(int n) => n.toString().padLeft(2, '0');
      time = '${t.year.toString().padLeft(4, '0')}-${two(t.month)}-${two(t.day)}T${two(t.hour)}:${two(t.minute)}';
    }
    return time.compareTo(now) > 0 ? now : time;
  }

  void _toast(String message) {
    if (context.mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(message)));
  }

  Future<void> _keepLeave(AttendanceDay day) async {
    final reason = await askKeepLeaveReason(context);
    if (reason == null) return;
    try {
      await ref.read(attendanceRepositoryProvider).keepLeaveOverPunches(day.id, reason: reason);
      _toast('Leave kept.');
      onChanged();
    } catch (e) {
      _toast(e is ApiError ? e.message : 'Something went wrong.');
    }
  }

  /// Null for a fine day.
  RowMismatch? forDay(AttendanceDay day) {
    final mismatch = mismatchOf(day);
    if (mismatch == null) return null;
    final user = ref.read(authControllerProvider).user;
    final permissions = user?.permissions ?? const <String>[];
    // The server refuses on-behalf entries for yourself; the way out is a correction request.
    final canPunch = permissions.contains(attendancePunchOnBehalf) && day.employeeId != user?.employeeId;
    final label = nameOf(day.employeeId);
    final fixes = <RowFix>[];
    final request = pending['${day.employeeId}|${day.attendanceDate}'];
    if (request != null) {
      final approver = permissions.contains(attendanceRegularizationApprove);
      fixes.add(RowFix(approver ? 'Review correction request' : 'View correction request', () => context.push('/app/regularizations/$request'), primary: true));
    } else if (mismatch.kind == MismatchKind.workOnLeave) {
      if (permissions.contains(attendanceRecompute) && !day.isLocked) fixes.add(RowFix('Keep leave', () => _keepLeave(day), primary: true));
      fixes.add(RowFix('Cancel leave', () => context.push('/app/leave-applications')));
    } else if (mismatch.kind == MismatchKind.noPunches && canPunch) {
      fixes.add(
        RowFix('Mark present', () async {
          if (await openMarkAttendance(context, employees: [(value: day.employeeId, label: label)], date: day.attendanceDate)) onChanged();
        }, primary: true),
      );
    } else if ((mismatch.kind == MismatchKind.missingOut || mismatch.kind == MismatchKind.missingIn || mismatch.kind == MismatchKind.incomplete) && canPunch) {
      final direction = day.actualFirstIn != null ? 'OUT' : 'IN';
      fixes.add(
        RowFix(direction == 'IN' ? 'Add punch-in' : 'Add punch-out', () async {
          if (await openPunch(employeeId: day.employeeId, direction: direction, time: _punchTime(day, direction))) onChanged();
        }, primary: true),
      );
    }
    fixes.add(RowFix('Open day', () => openDay(day), primary: fixes.isEmpty));
    return RowMismatch(mismatch.reason, fixes);
  }
}

/// The reason line and the fix buttons under a mismatched day.
class MismatchFixBlock extends StatelessWidget {
  const MismatchFixBlock({super.key, required this.mismatch});
  final RowMismatch mismatch;

  @override
  Widget build(BuildContext context) {
    final warning = (Theme.of(context).extension<AppStatusColors>() ?? AppStatusColors.light).warning;
    return Padding(
      padding: const EdgeInsets.only(top: 8),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Padding(padding: const EdgeInsets.only(top: 2), child: Icon(Icons.warning_amber_rounded, size: 16, color: warning)),
              const SizedBox(width: 6),
              Expanded(child: Text(mismatch.reason, style: TextStyle(fontSize: 12.5, color: warning, fontWeight: FontWeight.w600))),
            ],
          ),
          const SizedBox(height: 8),
          Wrap(
            spacing: 8,
            runSpacing: 6,
            children: [
              for (final fix in mismatch.fixes)
                fix.primary
                    ? FilledButton(style: FilledButton.styleFrom(visualDensity: VisualDensity.compact), onPressed: fix.onPressed, child: Text(fix.label))
                    : OutlinedButton(style: OutlinedButton.styleFrom(visualDensity: VisualDensity.compact), onPressed: fix.onPressed, child: Text(fix.label)),
            ],
          ),
        ],
      ),
    );
  }
}

/// "N days don't add up and need fixing", with a switch to show only those.
class MismatchBanner extends StatelessWidget {
  const MismatchBanner({super.key, required this.count, required this.narrowed, required this.onToggle});
  final int count;
  final bool narrowed;
  final VoidCallback onToggle;

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).extension<AppStatusColors>() ?? AppStatusColors.light;
    return Container(
      margin: const EdgeInsets.only(bottom: 10),
      padding: const EdgeInsets.fromLTRB(12, 6, 4, 6),
      decoration: BoxDecoration(color: colors.warningSubtle, borderRadius: BorderRadius.circular(12), border: Border.all(color: colors.warning.withValues(alpha: 0.4))),
      child: Row(
        children: [
          Icon(Icons.warning_amber_rounded, size: 18, color: colors.warning),
          const SizedBox(width: 8),
          Expanded(child: Text(count == 1 ? "1 day doesn't add up and needs fixing." : "$count days don't add up and need fixing.", style: const TextStyle(fontSize: 13, fontWeight: FontWeight.w600))),
          TextButton(onPressed: onToggle, child: Text(narrowed ? 'Show everyone' : 'Show only these')),
        ],
      ),
    );
  }
}
