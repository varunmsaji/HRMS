import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api/api_error.dart';
import '../../../core/auth/permissions.dart';
import '../../../core/time.dart';
import '../../auth/presentation/widgets/auth_form_field.dart';
import '../../auth/state/auth_controller.dart';
import '../data/attendance_repository.dart';
import 'attendance_widgets.dart';
import 'holiday_calendars_screen.dart' show attendanceRepositoryProvider;

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

  Widget _section(String title, List<Widget> children) {
    final scheme = Theme.of(context).colorScheme;
    return Container(
      margin: const EdgeInsets.only(top: 14),
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(border: Border.all(color: scheme.outlineVariant), borderRadius: BorderRadius.circular(12)),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text(title, style: Theme.of(context).textTheme.titleSmall),
        const SizedBox(height: 8),
        ...children,
      ]),
    );
  }

  Widget _kv(String k, String v) => Padding(
        padding: const EdgeInsets.symmetric(vertical: 3),
        child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Expanded(flex: 5, child: Text(k, style: TextStyle(color: Theme.of(context).colorScheme.onSurfaceVariant))),
          Expanded(flex: 5, child: Text(v, textAlign: TextAlign.end)),
        ]),
      );

  @override
  Widget build(BuildContext context) {
    final permissions = ref.watch(authControllerProvider).user?.permissions ?? const <String>[];
    final canRecompute = permissions.contains(attendanceRecompute);
    final day = _day;
    final scheme = Theme.of(context).colorScheme;

    Widget body;
    if (day == null && _loading) {
      body = const Center(child: CircularProgressIndicator());
    } else if (day == null) {
      body = Center(
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: Column(mainAxisSize: MainAxisSize.min, children: [
            Text(_error?.status == 404 ? "This attendance day was not found, or you don't have access to it." : (_error?.message ?? 'Something went wrong.'), textAlign: TextAlign.center),
            const SizedBox(height: 16),
            FilledButton(onPressed: _load, child: const Text('Retry')),
          ]),
        ),
      );
    } else {
      final r = day.raw;
      final tz = day.timezone;
      bool flag(String k) => r[k] == true;
      String s(String k) => (r[k] ?? '—').toString();
      String mins(String k) => formatMinutes(r[k] as int?);
      final badges = <(String, Color)>[
        if (flag('is_late')) ('Late', Colors.orange),
        if (flag('is_early_out')) ('Early departure', Colors.orange),
        if (flag('is_overtime')) ('Overtime', Colors.blue),
        if (flag('is_regularized')) ('Regularized', scheme.onSurfaceVariant),
        if (flag('is_pending_approval')) ('Pending approval', Colors.orange),
        if (flag('worked_on_holiday')) ('Worked on holiday', Colors.blue),
        if (flag('worked_on_weekly_off')) ('Worked on weekly off', Colors.blue),
        if (flag('missing_punch')) ('Missing punch', Colors.red),
        if (flag('work_on_leave_flagged') && r['work_on_leave_resolution'] == null) ('Worked on leave — needs HR decision', Colors.orange),
        if (flag('work_on_leave_flagged') && r['work_on_leave_resolution'] == 'KEEP_LEAVE') ('Leave kept by HR', scheme.onSurfaceVariant),
        if (flag('is_core_hours_breach')) ('Core hours breach', Colors.orange),
        if (flag('on_duty')) ('On duty', Colors.blue),
        if (day.isLocked) ('Locked', scheme.onSurfaceVariant),
      ];
      final breaks = ((r['breaks'] as List?) ?? const []).cast<Map<String, dynamic>>();
      final canKeepLeave = canRecompute && flag('work_on_leave_flagged') && r['work_on_leave_resolution'] == null && !day.isLocked;
      body = RefreshIndicator(
        onRefresh: _load,
        child: ListView(
          padding: const EdgeInsets.all(16),
          children: [
            Text('${day.attendanceDate} — $tz (${zoneLabel(tz)})', style: TextStyle(color: scheme.onSurfaceVariant)),
            const SizedBox(height: 8),
            Wrap(spacing: 6, runSpacing: 6, children: [
              AttendanceStatusBadge(status: day.attendanceStatus),
              for (final (label, color) in badges)
                Container(
                  padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
                  decoration: BoxDecoration(color: color.withValues(alpha: 0.12), borderRadius: BorderRadius.circular(4)),
                  child: Text(label, style: TextStyle(color: color, fontSize: 11, fontWeight: FontWeight.w600)),
                ),
            ]),
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
