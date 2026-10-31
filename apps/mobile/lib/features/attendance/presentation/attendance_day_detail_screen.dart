import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api/api_error.dart';
import '../../../core/auth/permissions.dart';
import '../../../core/time.dart';
import '../../auth/presentation/widgets/auth_form_field.dart';
import '../../auth/state/auth_controller.dart';
import '../data/attendance_repository.dart';
import '../../../core/widgets/employee/attendance_history.dart';
import '../../../core/widgets/employee/employee_status_chip.dart';
import '../../../core/widgets/employee/layout.dart';
import '../../../core/widgets/employee/status_map.dart';
import 'attendance_summary.dart';
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

  /// Rows with no value are left out, and a section with none is not drawn at all.
  List<Widget> _facts(String title, List<(String, String)> rows, {String? footnote}) {
    final shown = [for (final r in rows) if (r.$2.isNotEmpty && r.$2 != '—') r];
    if (shown.isEmpty) return const [];
    return [
      EmployeeSectionHeader(title),
      EmployeeListGroup(children: [for (final r in shown) EmployeeFactRow(label: r.$1, value: r.$2)]),
      if (footnote != null) Padding(padding: const EdgeInsets.fromLTRB(16, 6, 16, 0), child: Text(footnote, style: Theme.of(context).textTheme.bodySmall)),
    ];
  }

  static String _nonZero(String minutes) => (minutes == '0h 0m') ? '—' : minutes;
  static String _fraction(String v) => (num.tryParse(v) == 0) ? '—' : v;
  static String _pretty(String v) => v == '—' ? v : humanize(v);

  @override
  Widget build(BuildContext context) {
    final permissions = ref.watch(authControllerProvider).user?.permissions ?? const <String>[];
    final canRecompute = permissions.contains(attendanceRecompute);
    final day = _day;

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
      final flags = <(String, StatusKind)>[
        if (flag('is_late')) ('Late', StatusKind.warning),
        if (flag('is_early_out')) ('Early departure', StatusKind.warning),
        if (flag('is_overtime')) ('Overtime', StatusKind.info),
        if (flag('is_regularized')) ('Regularized', StatusKind.neutral),
        if (flag('is_pending_approval')) ('Pending approval', StatusKind.warning),
        if (flag('worked_on_holiday')) ('Worked on holiday', StatusKind.info),
        if (flag('worked_on_weekly_off')) ('Worked on weekly off', StatusKind.info),
        if (flag('missing_punch')) ('Missing punch', StatusKind.danger),
        if (flag('work_on_leave_flagged') && r['work_on_leave_resolution'] == null) ('Worked on leave — needs HR decision', StatusKind.warning),
        if (flag('work_on_leave_flagged') && r['work_on_leave_resolution'] == 'KEEP_LEAVE') ('Leave kept by HR', StatusKind.neutral),
        if (flag('is_core_hours_breach')) ('Core hours breach', StatusKind.warning),
        if (flag('on_duty')) ('On duty', StatusKind.info),
        if (day.isLocked) ('Locked', StatusKind.neutral),
      ];
      final breaks = ((r['breaks'] as List?) ?? const []).cast<Map<String, dynamic>>();
      final canKeepLeave = canRecompute && flag('work_on_leave_flagged') && r['work_on_leave_resolution'] == null && !day.isLocked;
      final today = businessToday(tz);
      final label = historyStatusLabel(day, today: today);
      final provisional = day.attendanceDate == today && isNotCheckedIn(day) && !day.isLocked;
      final bucketStatus = statusForAttendanceBucket(attendanceBucketOf(day));
      // Today's ABSENT/INCOMPLETE row is the 09:30 sweep's placeholder, not a verdict.
      final headerStatus = provisional ? (kind: StatusKind.warning, label: label, glyph: glyphFor(StatusKind.warning)) : bucketStatus;
      // A worked-time figure only for a closed work period; an open or empty day says what is missing.
      final closed = day.actualFirstIn != null && day.actualLastOut != null && (day.workedMinutes ?? 0) > 0;
      final punchLine = [
        if (day.actualFirstIn != null) 'First in ${formatClockTime(day.actualFirstIn, tz)}',
        if (day.actualLastOut != null) 'Last out ${formatClockTime(day.actualLastOut, tz)}',
      ].join(' · ');
      final headerCaption = closed
          ? 'Worked · $punchLine'
          : (day.actualFirstIn != null ? '$punchLine · no punch-out recorded' : (provisional ? null : 'No punches recorded'));
      final overlay = [
        for (final p in _projections)
          ('Leave ${p.fraction}${p.half != null ? ' · ${p.half}' : ''}', '${p.isPaid ? 'Paid' : 'Unpaid'} · ${p.status}'),
      ];
      body = RefreshIndicator(
        onRefresh: _load,
        child: ListView(
          padding: const EdgeInsets.symmetric(vertical: 16),
          children: [
            EmployeeStatusHeader(
              status: headerStatus,
              title: day.attendanceDate,
              subtitle: '$tz (${zoneLabel(tz)})',
              figure: closed ? formatMinutes(day.workedMinutes) : null,
              figureCaption: headerCaption,
            ),
            if (flags.isNotEmpty)
              Padding(
                padding: const EdgeInsets.fromLTRB(16, 12, 16, 0),
                child: Wrap(spacing: 8, runSpacing: 6, children: [
                  for (final (text, kind) in flags) EmployeeStatusChip(status: (kind: kind, label: text, glyph: glyphFor(kind))),
                ]),
              ),
            if (canRecompute)
              Padding(
                padding: const EdgeInsets.fromLTRB(16, 12, 16, 0),
                child: Wrap(spacing: 8, runSpacing: 8, children: [
                  OutlinedButton(onPressed: (_busy || day.isLocked) ? null : _recompute, child: const Text('Recompute')),
                  if (canKeepLeave) OutlinedButton(onPressed: _busy ? null : _keepLeave, child: const Text('Keep leave')),
                ]),
              ),
            ..._facts('Schedule', [
              ('Day type', _pretty(s('calendar_day_type'))),
              ('Holiday', s('holiday_name')),
              ('Scheduled', r['scheduled_start'] == null ? '—' : '${formatClockTime(r['scheduled_start'] as String?, tz)} – ${formatClockTime(r['scheduled_end'] as String?, tz)}'),
              ('Scheduled time', _nonZero(mins('scheduled_minutes'))),
            ]),
            ..._facts('Actual', [
              ('First in', formatDateTime(day.actualFirstIn, tz)),
              ('Last out', formatDateTime(day.actualLastOut, tz)),
              ('Worked', closed ? mins('worked_minutes') : '—'),
              ('Late', _nonZero(mins('late_minutes'))),
              ('Early departure', _nonZero(mins('early_departure_minutes'))),
              ('Late classification', _pretty(s('late_classification'))),
              ('Early-departure classification', _pretty(s('early_departure_classification'))),
              ('Unpaid break', _nonZero(mins('unpaid_break_minutes'))),
              ('Paid break', _nonZero(mins('paid_break_minutes'))),
              ('Excess break', _nonZero(mins('excess_break_minutes'))),
              for (final b in breaks)
                (
                  'Break',
                  '${formatClockTime(b['break_start'] as String?, tz)} – ${formatClockTime(b['break_end'] as String?, tz)} · ${formatMinutes(b['minutes'] as int?)}${b['is_paid'] == true ? ' · paid' : ''}${b['is_excess'] == true ? ' · excess' : ''}',
                ),
            ]),
            ..._facts('Overtime and pay', [
              ('Overtime detected', _nonZero(mins('ot_minutes_detected'))),
              ('Overtime approved', _nonZero(mins('ot_minutes_approved'))),
              ('Overtime class', _pretty(s('ot_classification'))),
              ('Comp-off earned', _nonZero(mins('comp_off_minutes_earned'))),
              ('Paid day fraction', _fraction(s('paid_day_fraction'))),
              ('Leave fraction', _fraction(s('leave_fraction'))),
              ('Weekly-off fraction', _fraction(s('weekly_off_fraction'))),
              ('Unpaid off fraction', _fraction(s('unpaid_off_fraction'))),
              ('Loss-of-pay fraction', _fraction(s('lop_fraction'))),
              if (flag('work_on_leave_flagged')) ('Work-on-leave decision', _pretty(s('work_on_leave_resolution'))),
            ]),
            if (overlay.isNotEmpty) ..._facts('Approved leave on this date', overlay, footnote: 'Shown for reference; Leave owns the balance and approval.'),
            Padding(
              padding: const EdgeInsets.fromLTRB(16, 24, 16, 0),
              child: EmployeeCalculationDetails(
                rows: [
                  ('Calculation version', s('calculation_version')),
                  ('Calculated at', formatDateTime(r['calculated_at'] as String?, tz)),
                  ('Attendance policy version', s('attendance_policy_version_id')),
                  ('Overtime policy version', s('overtime_policy_version_id')),
                  ('Regularization policy version', s('regularization_policy_version_id')),
                  ('Locked at', day.isLocked ? formatDateTime(r['locked_at'] as String?, tz) : '—'),
                ],
              ),
            ),
          ],
        ),
      );
    }
    return Scaffold(appBar: AppBar(title: const Text('Attendance day')), body: body);
  }
}
