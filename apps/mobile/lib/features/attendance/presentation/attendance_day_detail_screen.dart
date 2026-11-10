import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api/api_client.dart';
import '../../../core/api/api_error.dart';
import '../../../core/auth/permissions.dart';
import '../../../core/forms/choice_sources.dart';
import '../../../core/forms/spec_form_screen.dart';
import '../../../core/providers.dart';
import '../../../core/requests/request_screens.dart';
import '../../../core/theme/employee_theme_scope.dart';
import '../../../core/time.dart';
import '../../auth/presentation/widgets/auth_form_field.dart';
import '../../auth/state/auth_controller.dart';
import '../data/attendance_repository.dart';
import '../domain/request_resources.dart';
import '../../../core/widgets/employee/attendance_history.dart';
import '../../../core/widgets/employee/employee_status_chip.dart';
import '../../../core/widgets/employee/layout.dart';
import '../../../core/widgets/employee/status_map.dart';
import 'attendance_summary.dart';
import '../../../core/widgets/ui.dart';

/// Mirrors `apps/web/src/app/app/attendance/[id]/page.tsx` — one computed attendance day:
/// schedule, actuals and breaks, overtime and pay facts, the leave overlay, and the audit trail,
/// with recompute and keep-leave for HR, and the corrections raised for the day with a way to raise
/// one (web `components/attendance/day/day-regularization.tsx`). Every timestamp is shown in the zone the day was
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

  /// Correction requests for this employee and date; null = not loaded or not visible to the viewer.
  List<Map<String, dynamic>>? _corrections;

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
      await _loadCorrections(day);
    } catch (e) {
      if (mounted) setState(() => _error = e is ApiError ? e : ApiError(status: 0, code: 'UNKNOWN_ERROR', message: 'Something went wrong.'));
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  /// Best effort, as on web: a viewer who can't list requests just sees none.
  Future<void> _loadCorrections(AttendanceDay day) async {
    try {
      final env = await ref.read(apiClientProvider).getList<Map<String, dynamic>>(
        '/regularizations',
        query: PageQuery(perPage: 100),
        filters: {'employee_id': day.employeeId, 'date_from': day.attendanceDate, 'date_to': day.attendanceDate},
        parseItem: (d) => d as Map<String, dynamic>,
      );
      if (mounted) setState(() => _corrections = [for (final r in env.data) if (r['attendance_date'] == day.attendanceDate) r]);
    } catch (_) {
      if (mounted) setState(() => _corrections = null);
    }
  }

  /// `SELF` on the viewer's own day, `ON_BEHALF` for someone else's, null when they can't raise one.
  /// Mirrors web's `requestMode`.
  String? _requestMode(AttendanceDay day) {
    final user = ref.read(authControllerProvider).user;
    final perms = user?.permissions ?? const <String>[];
    final own = user?.employeeId != null && user!.employeeId == day.employeeId;
    if (own) return perms.contains(attendanceRegularizationRequest) ? 'SELF' : null;
    // The API treats a request naming the caller's own employee as a self request.
    if (perms.contains(attendanceRegularizationRequestOnBehalf)) return 'ON_BEHALF';
    return null;
  }

  Future<void> _requestCorrection(AttendanceDay day, String mode) async {
    final client = ref.read(apiClientProvider);
    final user = ref.read(authControllerProvider).user;
    final zone = user?.companyTimezone ?? 'Asia/Kolkata';
    final denied = ref.read(deniedChoiceSourcesProvider(user?.id ?? '').notifier);
    // The employee is fixed by the day, so the form never asks for one (web locks the field).
    final saved = await openSpecForm(
      context,
      title: 'Raise a regularization request',
      spec: regularizationSpec(false),
      defaults: {'attendance_date': day.attendanceDate},
      submitLabel: 'Submit request',
      loadChoiceSet: () async {
        final set = await loadChoicesTolerant(client, optional: regularizationConfig.optionalChoiceKeys, knownDenied: denied.state);
        final newlyDenied = {for (final e in set.unavailable.entries) if (e.value == ChoiceUnavailable.denied) e.key};
        if (newlyDenied.difference(denied.state).isNotEmpty) denied.state = {...denied.state, ...newlyDenied};
        return set;
      },
      onSubmit: (payload, _) async => client.post<Object?>(
        '/regularizations',
        body: buildRegularizationBody({...payload, if (mode == 'ON_BEHALF') 'employee_id': day.employeeId}, zone),
        parse: (_) => null,
      ),
    );
    if (saved && mounted) {
      _toast('Regularization request submitted');
      await _loadCorrections(day);
    }
  }

  List<Widget> _correctionsSection(AttendanceDay day) {
    final list = _corrections ?? const <Map<String, dynamic>>[];
    final mode = _requestMode(day);
    if (list.isEmpty && mode == null) return const [];
    final open = list.any((r) => r['status'] == 'SUBMITTED');
    final r = day.raw;
    final needsCorrection = r['missing_punch'] == true || r['is_late'] == true || r['is_early_out'] == true || r['attendance_status'] == 'INCOMPLETE';
    final theme = Theme.of(context);
    return [
      const EmployeeSectionHeader('Corrections'),
      if (list.isEmpty)
        Padding(padding: const EdgeInsets.fromLTRB(16, 0, 16, 8), child: Text('No correction has been requested for this day.', style: theme.textTheme.bodySmall))
      else
        EmployeeListGroup(children: [
          for (final c in list)
            ListTile(
              title: Text(regularizationTypeLabels[c['request_type']] ?? '${c['request_type']}'),
              subtitle: c['submitted_at'] == null ? null : Text('submitted ${relativeTime(c['submitted_at'] as String)}'),
              trailing: RequestStatusChip(status: '${c['status']}', labels: requestStatusLabels),
              onTap: () async {
                await pushKeepingTheme<void>(context, (_) => RequestDetailScreen(config: regularizationConfig, requestId: c['id'] as String, initial: c));
                await _loadCorrections(day);
              },
            ),
        ]),
      if (mode != null && !open)
        Padding(
          padding: const EdgeInsets.fromLTRB(16, 8, 16, 0),
          child: needsCorrection
              ? FilledButton(onPressed: () => _requestCorrection(day, mode), child: const Text('Request a correction'))
              : OutlinedButton(onPressed: () => _requestCorrection(day, mode), child: const Text('Request a correction')),
        ),
    ];
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
              ('Calendar day type', _pretty(s('calendar_day_type'))),
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
              ('OT classification', _pretty(s('ot_classification'))),
              ('Comp-off earned', _nonZero(mins('comp_off_minutes_earned'))),
              ('Paid day fraction', _fraction(s('paid_day_fraction'))),
              ('Leave fraction', _fraction(s('leave_fraction'))),
              ('Weekly-off fraction', _fraction(s('weekly_off_fraction'))),
              ('Unpaid off fraction', _fraction(s('unpaid_off_fraction'))),
              ('LOP fraction', _fraction(s('lop_fraction'))),
              if (flag('work_on_leave_flagged')) ('Work-on-leave decision', _pretty(s('work_on_leave_resolution'))),
            ]),
            ..._correctionsSection(day),
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
