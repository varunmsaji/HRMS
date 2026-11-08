import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../core/api/api_client.dart';
import '../../../core/providers.dart';
import '../../../core/requests/request_screens.dart';
import '../../../core/time.dart';
import '../../../core/widgets/employee/employee_status_chip.dart';
import '../../../core/widgets/employee/layout.dart';
import '../../../core/widgets/employee/status_map.dart';
import '../../auth/state/auth_controller.dart';
import '../data/attendance_repository.dart';
import '../domain/employee_attendance_summary.dart';
import '../domain/request_resources.dart';
import 'attendance_day_detail_screen.dart';
import 'attendance_month_card.dart';
import 'attendance_summary.dart';
import 'employee_attendance_panel.dart';

const _months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

/// "1 Oct" — web `formatShortDate`.
String _short(String iso) => iso.length < 10 ? iso : '${int.parse(iso.substring(8, 10))} ${_months[int.parse(iso.substring(5, 7)) - 1]}';

/// HR / manager view of one employee's attendance — mirrors
/// `apps/web/src/app/app/attendance/employee/[employeeId]/page.tsx` and its `EmployeeMonthView`:
/// today's status and punches, then a month with its calendar, figures, attendance issues and
/// regularization requests. Every list is data-scoped by the server, so a manager only ever sees
/// their own reportees here.
class EmployeeAttendanceProfileScreen extends ConsumerStatefulWidget {
  const EmployeeAttendanceProfileScreen({super.key, required this.employeeId, required this.employeeLabel, this.now});
  final String employeeId;
  final String employeeLabel;

  /// Overrides the clock in tests. Null = now.
  final DateTime? now;

  @override
  ConsumerState<EmployeeAttendanceProfileScreen> createState() => _EmployeeAttendanceProfileScreenState();
}

class _EmployeeAttendanceProfileScreenState extends ConsumerState<EmployeeAttendanceProfileScreen> {
  bool _todayLoading = true;
  String? _todayError;
  AttendanceDay? _today;
  List<Punch> _punches = const [];

  String? _month;
  List<AttendanceDay> _monthDays = const [];

  bool _regsLoading = true;
  bool _regsFailed = false;
  List<Map<String, dynamic>> _regs = const [];

  String get _zone => ref.read(authControllerProvider).user?.companyTimezone ?? 'Asia/Kolkata';
  String get _todayIso => businessToday(_zone, now: widget.now);

  @override
  void initState() {
    super.initState();
    _loadToday();
    _loadRegularizations();
  }

  Future<void> _loadToday() async {
    setState(() {
      _todayLoading = true;
      _todayError = null;
    });
    final repo = ref.read(attendanceRepositoryProvider);
    final today = _todayIso;
    try {
      final days = await repo.listAttendanceDays(employeeId: widget.employeeId, dateFrom: today, dateTo: today);
      var punches = const <Punch>[];
      try {
        punches = await repo.listPunches(employeeId: widget.employeeId, dateFrom: today, dateTo: today);
      } catch (_) {
        // The punch chips are a nicety; the day row says what matters.
      }
      if (mounted) {
        setState(() {
          _today = days.where((d) => d.attendanceDate == today).firstOrNull;
          _punches = [...punches]..sort((a, b) => a.punchTime.compareTo(b.punchTime));
        });
      }
    } catch (_) {
      if (mounted) setState(() => _todayError = "Today's attendance couldn't be loaded.");
    } finally {
      if (mounted) setState(() => _todayLoading = false);
    }
  }

  Future<void> _loadRegularizations() async {
    setState(() {
      _regsLoading = true;
      _regsFailed = false;
    });
    try {
      final env = await ref.read(apiClientProvider).getList<Map<String, dynamic>>(
        '/regularizations',
        query: PageQuery(perPage: 100),
        filters: {'employee_id': widget.employeeId},
        parseItem: (d) => d as Map<String, dynamic>,
      );
      if (mounted) setState(() => _regs = env.data);
    } catch (_) {
      if (mounted) setState(() => _regsFailed = true);
    } finally {
      if (mounted) setState(() => _regsLoading = false);
    }
  }

  void _openDay(AttendanceDay d) => Navigator.of(context).push(MaterialPageRoute(builder: (_) => AttendanceDayDetailScreen(dayId: d.id, initial: d)));

  Widget _todaySection(BuildContext context) {
    final theme = Theme.of(context);
    final tz = _zone;
    if (_todayLoading) return const Padding(padding: EdgeInsets.all(24), child: Center(child: CircularProgressIndicator(strokeWidth: 2.5)));
    if (_todayError != null) {
      return Padding(
        padding: const EdgeInsets.symmetric(horizontal: 16),
        child: Row(children: [Expanded(child: Text(_todayError!)), TextButton(onPressed: _loadToday, child: const Text('Retry'))]),
      );
    }
    final d = _today;
    if (d == null) {
      return Padding(padding: const EdgeInsets.symmetric(horizontal: 16), child: Text('No attendance record for today yet.', style: theme.textTheme.bodyMedium));
    }
    final r = d.raw;
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 16),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Wrap(spacing: 8, crossAxisAlignment: WrapCrossAlignment.center, children: [
          EmployeeStatusChip(status: statusForAttendanceBucket(attendanceBucketOf(d))),
          Text(attendancePresenceLabel(d), style: theme.textTheme.bodyMedium),
        ]),
        const SizedBox(height: 10),
        StatTiles(stats: [
          ('Shift', r['scheduled_start'] == null ? '—' : '${formatClockTime(r['scheduled_start'] as String?, tz)} – ${formatClockTime(r['scheduled_end'] as String?, tz)}'),
          ('Check-in', d.actualFirstIn == null ? '—' : formatClockTime(d.actualFirstIn, tz)),
          ('Check-out', d.actualLastOut == null ? '—' : formatClockTime(d.actualLastOut, tz)),
          ('Worked', d.actualFirstIn == null ? '—' : formatMinutes(d.workedMinutes)),
        ]),
        if (_punches.isNotEmpty) ...[
          const SizedBox(height: 10),
          Semantics(
            label: "Today's punches",
            container: true,
            child: Wrap(spacing: 6, runSpacing: 6, children: [
              for (final p in _punches) Chip(label: Text('${p.direction} ${formatClockTime(p.punchTime, tz)}'), visualDensity: VisualDensity.compact),
            ]),
          ),
        ],
        TextButton(onPressed: () => _openDay(d), child: const Text('Full day detail →')),
      ]),
    );
  }

  List<Widget> _monthSections(BuildContext context) {
    final theme = Theme.of(context);
    final s = AttendanceRangeSummary.compute(_monthDays);
    final issues = [for (final d in _monthDays) if (hasAttendanceException(d)) d]..sort((a, b) => b.attendanceDate.compareTo(a.attendanceDate));
    final note = _regsLoading ? 'Loading requests…' : (_regsFailed ? "Regularization requests couldn't be loaded." : null);
    return [
      Padding(
        padding: const EdgeInsets.fromLTRB(16, 12, 16, 0),
        child: StatTiles(stats: [
          ('Present', '${s.present}'),
          ('Half days', '${s.count('HALF_DAY')}'),
          ('Absent', '${s.count('ABSENT')}'),
          ('On leave', '${s.count('LEAVE')}'),
          ('Holidays / weekly offs', '${s.count('HOLIDAY') + s.count('WEEKLY_OFF')}'),
          ('Late arrivals', '${s.late}'),
          ('Early departures', '${s.earlyOut}'),
          ('Worked', formatMinutes(s.workedMinutes)),
          ('Overtime', s.otDetectedMinutes > 0 ? '${formatMinutes(s.otDetectedMinutes)} (${formatMinutes(s.otApprovedMinutes)} approved)' : 'None'),
        ]),
      ),
      const EmployeeSectionHeader('Attendance issues'),
      if (issues.isEmpty)
        Padding(padding: const EdgeInsets.symmetric(horizontal: 16), child: Text('No attendance issues this month.', style: theme.textTheme.bodyMedium))
      else
        EmployeeListGroup(children: [
          for (final d in issues)
            ListTile(
              onTap: () => _openDay(d),
              title: Text(_short(d.attendanceDate)),
              subtitle: Wrap(spacing: 6, runSpacing: 4, children: [
                EmployeeStatusChip(status: statusForAttendanceBucket(attendanceBucketOf(d))),
                for (final l in attendanceProblemLabels(d)) EmployeeStatusChip(status: (kind: StatusKind.warning, label: l, glyph: glyphFor(StatusKind.warning))),
              ]),
            ),
        ]),
      EmployeeSectionHeader('Regularization requests', actionLabel: 'All requests →', onAction: () => context.push('/app/regularizations')),
      if (note != null)
        Padding(padding: const EdgeInsets.symmetric(horizontal: 16), child: Text(note, style: theme.textTheme.bodyMedium))
      else if (_regs.isEmpty)
        Padding(padding: const EdgeInsets.symmetric(horizontal: 16), child: Text('No regularization requests.', style: theme.textTheme.bodyMedium))
      else
        EmployeeListGroup(children: [
          for (final r in _regs.take(8))
            ListTile(
              title: Text(_short('${r['attendance_date']}')),
              subtitle: Text(regularizationTypeLabels[r['request_type']] ?? '${r['request_type']}'),
              trailing: RequestStatusChip(status: '${r['status']}', labels: requestStatusLabels),
            ),
        ]),
    ];
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: Text(widget.employeeLabel), actions: [
        // The record tab's date-range view, with Calculate today and Record punch for HR.
        IconButton(
          tooltip: 'Attendance history',
          icon: const Icon(Icons.history),
          onPressed: () => Navigator.of(context).push(MaterialPageRoute(
            builder: (_) => Scaffold(appBar: AppBar(title: Text(widget.employeeLabel)), body: EmployeeAttendancePanel(employeeId: widget.employeeId, employeeLabel: widget.employeeLabel)),
          )),
        ),
      ]),
      body: RefreshIndicator(
        onRefresh: () async {
          await Future.wait([_loadToday(), _loadRegularizations()]);
        },
        child: ListView(
          padding: const EdgeInsets.only(bottom: 24),
          children: [
            EmployeeSectionHeader('Today', caption: _short(_todayIso)),
            _todaySection(context),
            const EmployeeSectionHeader('Month'),
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: 16),
              child: AttendanceMonthCard(
                employeeId: widget.employeeId,
                zone: _zone,
                now: widget.now,
                onLoaded: (month, days) => setState(() {
                  _month = month;
                  _monthDays = days;
                }),
              ),
            ),
            if (_month != null) ..._monthSections(context),
          ],
        ),
      ),
    );
  }
}
