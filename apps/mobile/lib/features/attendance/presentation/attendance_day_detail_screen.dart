import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api/api_error.dart';
import '../../../core/auth/permissions.dart';
import '../../../core/time.dart';
import '../../auth/presentation/widgets/auth_form_field.dart';
import '../../auth/state/auth_controller.dart';
import '../data/attendance_repository.dart';
import 'attendance_widgets.dart';
import '../../../core/widgets/ui.dart';

/// Mirrors `apps/web/src/app/app/attendance/[id]/page.tsx` — one computed attendance day:
/// schedule, actuals and breaks, overtime and pay facts, the leave overlay, and the audit trail,
/// with recompute and keep-leave for HR. Every timestamp is shown in the zone the day was
/// computed in (TZ-07), never the device's.
class AttendanceDayDetailScreen extends ConsumerStatefulWidget {
  const AttendanceDayDetailScreen({super.key, required this.dayId, this.initial});

  final String dayId;

  /// Shown immediately while the full record loads.
  final AttendanceDay? initial;

  @override
  ConsumerState<AttendanceDayDetailScreen> createState() => _AttendanceDayDetailScreenState();
}

class _AttendanceDayDetailScreenState extends ConsumerState<AttendanceDayDetailScreen> {
  bool _loading = true;
  bool _busy = false;
  ApiError? _error;
  AttendanceDay? _day;
  List<LeaveDayProjection> _projections = const [];

  AttendanceRepository get _repo => ref.read(attendanceRepositoryProvider);

  @override
  void initState() {
    super.initState();
    _day = widget.initial;
    _load();
  }

  Future<void> _load() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final day = await _repo.getAttendanceDay(widget.dayId);
      var projections = const <LeaveDayProjection>[];
      try {
        projections = await _repo.listLeaveProjections(employeeId: day.employeeId, dateFrom: day.attendanceDate, dateTo: day.attendanceDate);
      } catch (_) {
        // Best effort — a caller without projection visibility just sees no overlay.
      }
      if (mounted) {
        setState(() {
          _day = day;
          _projections = projections;
        });
      }
    } catch (e) {
      if (mounted) setState(() => _error = e is ApiError ? e : ApiError(status: 0, code: 'UNKNOWN_ERROR', message: 'Something went wrong.'));
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  void _toast(String m) => ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(m)));

  Future<void> _recompute() async {
    final yes = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Recompute this day?'),
        content: const Text('Recalculates the day from its punches, shift and policies.'),
        actions: [
          TextButton(onPressed: () => Navigator.of(ctx).pop(false), child: const Text('Cancel')),
          FilledButton(onPressed: () => Navigator.of(ctx).pop(true), child: const Text('Recompute')),
        ],
      ),
    );
    if (yes != true) return;
    setState(() => _busy = true);
    try {
      final day = await _repo.recomputeAttendanceDay(widget.dayId);
      if (mounted) setState(() => _day = day);
      _toast('Attendance day recomputed.');
    } catch (e) {
      _toast(e is ApiError ? e.message : 'Something went wrong.');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _keepLeave() async {
    final reason = TextEditingController();
    String? error;
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => StatefulBuilder(
        builder: (ctx, setLocal) => AlertDialog(
          title: const Text('Keep leave'),
          content: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.start, children: [
            const Text('Confirms the approved leave stands over the punches recorded on this day.'),
            const SizedBox(height: 12),
            if (error != null) Padding(padding: const EdgeInsets.only(bottom: 8), child: Text(error!, style: TextStyle(color: Theme.of(ctx).colorScheme.error))),
            AuthFormField(label: 'Reason', required: true, child: TextField(controller: reason)),
          ]),
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
    if (ok != true) return;
    setState(() => _busy = true);
    try {
      final day = await _repo.keepLeaveOverPunches(widget.dayId, reason: reason.text.trim());
      if (mounted) setState(() => _day = day);
      _toast('Leave kept.');
    } catch (e) {
      _toast(e is ApiError ? e.message : 'Something went wrong.');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Widget _section(String title, List<Widget> children, {IconData? icon}) => DetailSection(title: title, icon: icon, children: children);

  Widget _kv(String k, String v) => KeyValueRow(k, v == '—' ? null : v);

  Widget _heroStat(String label, String value) => Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text(label, style: const TextStyle(color: Colors.white60, fontSize: 11)),
        Text(value, style: const TextStyle(color: Colors.white, fontWeight: FontWeight.w700)),
      ]);

  @override
  Widget build(BuildContext context) {
    final permissions = ref.watch(authControllerProvider).user?.permissions ?? const <String>[];
    final canRecompute = permissions.contains(attendanceRecompute);
    final day = _day;
    final scheme = Theme.of(context).colorScheme;

    Widget body;
    if (day == null && _loading) {
      body = const ListSkeleton();
    } else if (day == null) {
      body = StateMessage(icon: Icons.error_outline_rounded, tone: Tone.danger, title: 'Something went wrong', message: _error?.status == 404 ? "This attendance day was not found, or you don't have access to it." : (_error?.message ?? 'Something went wrong.'), actionLabel: 'Retry', onAction: _load);
    } else {
      final r = day.raw;
      final tz = day.timezone;
      bool flag(String k) => r[k] == true;
      String s(String k) => (r[k] ?? '—').toString();
      String mins(String k) => formatMinutes(r[k] as int?);
      final badges = <(String, Tone)>[
        if (flag('is_late')) ('Late', Tone.warning),
        if (flag('is_early_out')) ('Early departure', Tone.warning),
        if (flag('is_overtime')) ('Overtime', Tone.info),
        if (flag('is_regularized')) ('Regularized', Tone.neutral),
        if (flag('is_pending_approval')) ('Pending approval', Tone.warning),
        if (flag('worked_on_holiday')) ('Worked on holiday', Tone.info),
        if (flag('worked_on_weekly_off')) ('Worked on weekly off', Tone.info),
        if (flag('missing_punch')) ('Missing punch', Tone.danger),
        if (flag('work_on_leave_flagged') && r['work_on_leave_resolution'] == null) ('Worked on leave — needs HR decision', Tone.warning),
        if (flag('work_on_leave_flagged') && r['work_on_leave_resolution'] == 'KEEP_LEAVE') ('Leave kept by HR', Tone.neutral),
        if (flag('is_core_hours_breach')) ('Core hours breach', Tone.warning),
        if (flag('on_duty')) ('On duty', Tone.info),
        if (day.isLocked) ('Locked', Tone.neutral),
      ];
      final breaks = ((r['breaks'] as List?) ?? const []).cast<Map<String, dynamic>>();
      final canKeepLeave = canRecompute && flag('work_on_leave_flagged') && r['work_on_leave_resolution'] == null && !day.isLocked;
      body = RefreshIndicator(
        onRefresh: _load,
        child: ListView(
          padding: const EdgeInsets.all(16),
          children: [
            HeroCard(
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Row(children: [
                  const Icon(Icons.event_rounded, size: 18, color: Colors.white70),
                  const SizedBox(width: 8),
                  Expanded(child: Text('${day.attendanceDate} — $tz (${zoneLabel(tz)})', style: const TextStyle(color: Colors.white, fontWeight: FontWeight.w700, fontSize: 14))),
                  const SizedBox(width: 8),
                  AttendanceStatusBadge(status: day.attendanceStatus),
                ]),
                const SizedBox(height: 14),
                Row(children: [
                  _heroStat('First in', formatClockTime(day.actualFirstIn, tz)),
                  const SizedBox(width: 28),
                  _heroStat('Last out', formatClockTime(day.actualLastOut, tz)),
                ]),
              ]),
            ),
            if (badges.isNotEmpty)
              Padding(
                padding: const EdgeInsets.only(top: 12),
                child: Wrap(spacing: 6, runSpacing: 6, children: [for (final (label, tone) in badges) StatusChip(label: label, tone: tone, dot: false)]),
              ),
            if (canRecompute)
              Padding(
                padding: const EdgeInsets.only(top: 12),
                child: Wrap(spacing: 8, runSpacing: 8, children: [
                  OutlinedButton(onPressed: (_busy || day.isLocked) ? null : _recompute, child: const Text('Recompute')),
                  if (canKeepLeave) OutlinedButton(onPressed: _busy ? null : _keepLeave, child: const Text('Keep leave')),
                ]),
              ),
            _section('Schedule', [
              _kv('Calendar day type', s('calendar_day_type')),
              _kv('Holiday', s('holiday_name')),
              _kv('Scheduled', r['scheduled_start'] == null ? '—' : '${formatClockTime(r['scheduled_start'] as String?, tz)} – ${formatClockTime(r['scheduled_end'] as String?, tz)}'),
              _kv('Scheduled minutes', mins('scheduled_minutes')),
            ]),
            _section('Actual', [
              _kv('First in', formatDateTime(day.actualFirstIn, tz)),
              _kv('Last out', formatDateTime(day.actualLastOut, tz)),
              _kv('Worked', mins('worked_minutes')),
              _kv('Unpaid break', mins('unpaid_break_minutes')),
              _kv('Paid break', mins('paid_break_minutes')),
              _kv('Excess break', mins('excess_break_minutes')),
              _kv('Late', mins('late_minutes')),
              _kv('Early departure', mins('early_departure_minutes')),
              _kv('Late classification', s('late_classification')),
              _kv('Early-departure classification', s('early_departure_classification')),
              for (final b in breaks)
                Padding(
                  padding: const EdgeInsets.only(top: 6),
                  child: Text('Break ${formatClockTime(b['break_start'] as String?, tz)} – ${formatClockTime(b['break_end'] as String?, tz)} · ${formatMinutes(b['minutes'] as int?)}${b['is_paid'] == true ? ' · paid' : ''}${b['is_excess'] == true ? ' · excess' : ''}', style: TextStyle(color: scheme.onSurfaceVariant)),
                ),
            ]),
            _section('Overtime & pay facts', [
              _kv('OT detected', mins('ot_minutes_detected')),
              _kv('OT approved', mins('ot_minutes_approved')),
              _kv('OT classification', s('ot_classification')),
              _kv('Comp-off earned', mins('comp_off_minutes_earned')),
              _kv('Paid day fraction', s('paid_day_fraction')),
              _kv('Leave fraction', s('leave_fraction')),
              _kv('Weekly-off fraction', s('weekly_off_fraction')),
              _kv('Unpaid off fraction', s('unpaid_off_fraction')),
              _kv('LOP fraction', s('lop_fraction')),
              if (flag('work_on_leave_flagged')) _kv('Work-on-leave decision', s('work_on_leave_resolution')),
            ]),
            if (_projections.isNotEmpty)
              _section('Leave overlay (approved leave for this date)', [
                for (final p in _projections) _kv('Leave application ${p.leaveApplicationId.substring(0, 8)}', '${p.fraction}${p.half != null ? ' · ${p.half}' : ''} · ${p.isPaid ? 'paid' : 'unpaid'} · ${p.status}'),
                Text('Provenance only — Leave owns entitlement, balance and approval.', style: TextStyle(fontSize: 12, color: scheme.onSurfaceVariant)),
              ]),
            _section('Calculation & audit', [
              _kv('Calculation version', s('calculation_version')),
              _kv('Calculated at', formatDateTime(r['calculated_at'] as String?, tz)),
              _kv('Attendance policy version', s('attendance_policy_version_id')),
              _kv('Overtime policy version', s('overtime_policy_version_id')),
              _kv('Regularization policy version', s('regularization_policy_version_id')),
              _kv('Locked at', day.isLocked ? formatDateTime(r['locked_at'] as String?, tz) : '—'),
            ]),
          ],
        ),
      );
    }
    return Scaffold(appBar: AppBar(title: const Text('Attendance day')), body: body);
  }
}
