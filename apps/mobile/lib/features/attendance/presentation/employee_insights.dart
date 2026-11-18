import 'dart:async';
import 'dart:math' as math;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api/api_error.dart';
import '../../../core/theme/app_colors.dart';
import '../../../core/time.dart';
import '../../../core/widgets/ui.dart';
import '../../auth/state/auth_controller.dart';
import '../data/attendance_repository.dart';
import '../domain/employee_analytics.dart';
import 'accent_stat_tile.dart';
import 'attendance_day_detail_screen.dart';
import 'attendance_summary.dart' show attendanceBucketLabels;
import 'attendance_widgets.dart' show AttendanceStatusBadge;

const _weekdays = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
const _monthNames = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'];

String monthTitle(String month) => '${_monthNames[int.parse(month.substring(5, 7)) - 1]} ${month.substring(0, 4)}';

String _longDate(String date) {
  final d = DateTime.parse('${date}T00:00:00Z');
  const weekdays = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'];
  return '${weekdays[d.weekday - 1]}, ${d.day} ${_monthNames[d.month - 1]}';
}

/// Shades of the brand colour for days that count as attendance, quieter tones for the rest. Only
/// absences and incomplete days keep a warm accent, because those are the days someone needs to
/// notice (web `SHADE`).
Color bucketShade(ColorScheme s, String bucket) {
  switch (bucket) {
    case 'PRESENT':
      return s.primary;
    case 'REMOTE':
      return s.primary.withValues(alpha: 0.7);
    case 'ON_DUTY':
      return s.primary.withValues(alpha: 0.55);
    case 'HALF_DAY':
      return s.primary.withValues(alpha: 0.4);
    case 'LEAVE':
      return s.primary.withValues(alpha: 0.25);
    case 'ABSENT':
      return s.error.withValues(alpha: 0.8);
    case 'INCOMPLETE':
      return s.tertiary.withValues(alpha: 0.8);
    case 'CONFIG_ERROR':
      return s.error.withValues(alpha: 0.5);
    case 'HOLIDAY':
      return s.onSurfaceVariant.withValues(alpha: 0.3);
    case 'WEEKLY_OFF':
      return s.onSurfaceVariant.withValues(alpha: 0.2);
    case 'NON_WORKING':
      return s.onSurfaceVariant.withValues(alpha: 0.15);
    default:
      return s.onSurfaceVariant.withValues(alpha: 0.1);
  }
}

const _shortLabel = {'NON_WORKING': 'Non-working', 'REMOTE': 'Remote'};
String _label(String b) => _shortLabel[b] ?? attendanceBucketLabels[b] ?? b;

const _stateCopy = {
  TodayState.working: 'Working',
  TodayState.onBreak: 'On a break',
  TodayState.checkedOut: 'Checked out',
  TodayState.notStarted: 'Shift not started',
  TodayState.notCheckedIn: 'Not checked in yet',
  TodayState.onLeave: 'On leave',
  TodayState.holiday: 'Holiday',
  TodayState.weeklyOff: 'Weekly off',
  TodayState.noShift: 'Nothing scheduled today',
  TodayState.notEmployed: 'Not employed on this date',
  TodayState.absent: 'Absent',
};

Color _stateColor(ColorScheme s, TodayState st) {
  switch (st) {
    case TodayState.working:
      return s.primary;
    case TodayState.onBreak:
    case TodayState.notCheckedIn:
      return s.tertiary;
    case TodayState.absent:
      return s.error;
    case TodayState.checkedOut:
    case TodayState.onLeave:
    case TodayState.holiday:
    case TodayState.weeklyOff:
      return s.secondary;
    default:
      return s.onSurfaceVariant;
  }
}

/// Today strip, month tiles, the month calendar and the two charts for one employee, read from the
/// attendance days and punches the API already serves (so the figures match the attendance pages).
/// Mirrors `apps/web/src/components/attendance/employee-insights.tsx`. The server filters by the
/// viewer's data scope: a caller without access sees nothing, not numbers.
class EmployeeInsights extends ConsumerStatefulWidget {
  const EmployeeInsights({super.key, required this.employeeId, this.shiftName, this.now, this.live = true});
  final String employeeId;
  final String? shiftName;

  /// The current instant (tests pin it).
  final DateTime? now;

  /// Keep the Today strip current: the clock moves every minute and the punches are re-read every
  /// two. Off in tests.
  final bool live;

  @override
  ConsumerState<EmployeeInsights> createState() => _EmployeeInsightsState();
}

class _EmployeeInsightsState extends ConsumerState<EmployeeInsights> {
  late String _month;
  List<AttendanceDay>? _days;
  AttendanceDay? _todayDay;
  List<Punch>? _punches;
  String? _failed; // 'denied' | 'error'
  late DateTime _now = widget.now ?? DateTime.now();
  String? _selected;
  Timer? _tick;
  Timer? _refresh;

  String get _zone => ref.read(authControllerProvider).user?.companyTimezone ?? 'Asia/Kolkata';
  String get _today => businessToday(_zone, now: _now);
  AttendanceRepository get _repo => ref.read(attendanceRepositoryProvider);

  @override
  void initState() {
    super.initState();
    _month = _today.substring(0, 7);
    _loadToday();
    _loadMonth();
    if (widget.live) {
      _tick = Timer.periodic(const Duration(minutes: 1), (_) => mounted ? setState(() => _now = DateTime.now()) : null);
      _refresh = Timer.periodic(const Duration(minutes: 2), (_) => mounted ? _loadToday() : null);
    }
  }

  @override
  void dispose() {
    _tick?.cancel();
    _refresh?.cancel();
    super.dispose();
  }

  void _fail(Object e) {
    if (!mounted) return;
    setState(() => _failed = (e is ApiError && e.status == 403) ? 'denied' : 'error');
  }

  Future<void> _loadToday() async {
    final today = _today;
    try {
      final results = await Future.wait([
        _repo.listAttendanceDays(employeeId: widget.employeeId, dateFrom: today, dateTo: today),
        _repo.listPunches(employeeId: widget.employeeId, dateFrom: today, dateTo: today),
      ]);
      if (!mounted) return;
      setState(() {
        _todayDay = (results[0] as List<AttendanceDay>).firstOrNull;
        _punches = results[1] as List<Punch>;
      });
    } catch (e) {
      _fail(e);
    }
  }

  Future<void> _loadMonth() async {
    final range = monthRange(_month);
    final month = _month;
    setState(() {
      _days = null;
      _selected = null;
    });
    try {
      final days = await _repo.listAttendanceDays(employeeId: widget.employeeId, dateFrom: range.from, dateTo: range.to);
      if (mounted && month == _month) setState(() => _days = days);
    } catch (e) {
      _fail(e);
    }
  }

  void _goToMonth(String month) {
    setState(() => _month = month);
    _loadMonth();
  }

  @override
  Widget build(BuildContext context) {
    if (_failed == 'denied') return const SizedBox.shrink();
    final scheme = Theme.of(context).colorScheme;
    if (_failed == 'error') {
      return AppCard(child: Text('Attendance figures could not be loaded right now.', key: const Key('insights-error'), style: TextStyle(color: scheme.onSurfaceVariant)));
    }
    final today = _today;
    final status = _punches == null ? null : todayStatus(_todayDay, _punches!, _now);
    return Column(key: const Key('employee-insights'), crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      _todayCard(context, status),
      const SizedBox(height: 14),
      _monthCard(context, today),
    ]);
  }

  // ---- Today ----------------------------------------------------------------------------------

  Widget _todayCard(BuildContext context, TodayStatus? status) {
    final scheme = Theme.of(context).colorScheme;
    if (status == null) return const AppCard(child: SizedBox(height: 64, child: Center(child: CircularProgressIndicator(strokeWidth: 2))));
    final zone = _zone;
    final color = _stateColor(scheme, status.state);
    final sub = switch (status.state) {
      TodayState.working || TodayState.onBreak => 'In since ${formatClockTime(status.firstIn, zone)}',
      TodayState.checkedOut => 'Left at ${formatClockTime(status.lastOut, zone)}',
      TodayState.notStarted when status.minutesToShiftStart != null => 'Starts in ${formatCountdown(status.minutesToShiftStart!)}',
      TodayState.notCheckedIn => 'Shift began at ${formatClockTime(status.scheduledStart, zone)}',
      TodayState.noShift when _todayDay == null => "Today's attendance has not been calculated yet.",
      _ => '',
    };
    final ends = status.minutesToShiftEnd;
    return AppCard(
      key: const Key('insights-today'),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [
          Container(width: 12, height: 12, decoration: BoxDecoration(color: color, shape: BoxShape.circle)),
          const SizedBox(width: 10),
          Expanded(
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text('TODAY', style: TextStyle(fontSize: 11, fontWeight: FontWeight.w700, letterSpacing: 0.6, color: scheme.onSurfaceVariant)),
              Text(
                '${_stateCopy[status.state]}${status.state == TodayState.holiday && status.holidayName != null ? ' · ${status.holidayName}' : ''}',
                key: const Key('insights-today-state'),
                style: TextStyle(fontSize: 18, fontWeight: FontWeight.w700, color: color),
              ),
              if (sub.isNotEmpty) Text(sub, style: TextStyle(color: scheme.onSurfaceVariant)),
            ]),
          ),
        ]),
        const SizedBox(height: 14),
        Wrap(spacing: 24, runSpacing: 12, children: [
          _fact(context, 'Shift', '${widget.shiftName ?? 'Not set'}${status.scheduledStart != null && status.scheduledEnd != null ? '\n${formatClockTime(status.scheduledStart, zone)}–${formatClockTime(status.scheduledEnd, zone)}' : ''}'),
          _fact(context, 'First in / last out', '${status.firstIn != null ? formatClockTime(status.firstIn, zone) : '—'} / ${status.state == TodayState.checkedOut && status.lastOut != null ? formatClockTime(status.lastOut, zone) : '—'}'),
          _fact(context, 'Worked today', status.workedMinutes != null ? formatMinutes(status.workedMinutes) : '—'),
          _fact(context, 'Shift ends', ends == null ? '—' : ends > 0 ? 'in ${formatCountdown(ends)}' : 'Over'),
        ]),
      ]),
    );
  }

  Widget _fact(BuildContext context, String label, String value) {
    final scheme = Theme.of(context).colorScheme;
    return Column(crossAxisAlignment: CrossAxisAlignment.start, mainAxisSize: MainAxisSize.min, children: [
      Text(label, style: TextStyle(fontSize: 12, color: scheme.onSurfaceVariant)),
      const SizedBox(height: 2),
      Text(value, style: const TextStyle(fontWeight: FontWeight.w700, fontFeatures: [FontFeature.tabularFigures()])),
    ]);
  }

  // ---- Month ----------------------------------------------------------------------------------

  Widget _monthCard(BuildContext context, String today) {
    final days = _days;
    final thisMonth = today.substring(0, 7);
    return AppCard(
      key: const Key('insights-month'),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [
          Expanded(child: Text(monthTitle(_month), style: const TextStyle(fontSize: 16, fontWeight: FontWeight.w700))),
          IconButton(tooltip: 'Previous month', icon: const Icon(Icons.chevron_left), onPressed: () => _goToMonth(shiftMonth(_month, -1))),
          TextButton(onPressed: _month == thisMonth ? null : () => _goToMonth(thisMonth), child: const Text('This month')),
          IconButton(tooltip: 'Next month', icon: const Icon(Icons.chevron_right), onPressed: _month.compareTo(thisMonth) >= 0 ? null : () => _goToMonth(shiftMonth(_month, 1))),
        ]),
        if (days == null)
          const SizedBox(height: 120, child: Center(child: CircularProgressIndicator(strokeWidth: 2)))
        else ...[
          _tiles(context, monthStats(days, today)),
          const SizedBox(height: 16),
          _calendar(context, days, today),
          const SizedBox(height: 16),
          _statusBreakdown(context, statusBreakdown(days, today)),
          const SizedBox(height: 14),
          _hoursChart(context, dailyHours(days, today)),
          if (_selected != null) ...[const SizedBox(height: 14), _dayDetail(context, monthWeeks(_month, days, today).expand((w) => w).whereType<CalendarCell>().where((c) => c.date == _selected).firstOrNull)],
        ],
      ]),
    );
  }

  Widget _tiles(BuildContext context, MonthStats s) {
    final scheme = Theme.of(context).colorScheme;
    final c = Theme.of(context).extension<AppStatusColors>() ?? AppStatusColors.light;
    final primarySubtle = scheme.primary.withValues(alpha: 0.12);
    return AccentStatGrid(keyPrefix: 'insights-tile-', stats: [
      AccentStat(
        'Days worked',
        formatWorkedDays(s.daysWorked),
        icon: Icons.event_available_rounded,
        accent: c.success,
        accentSubtle: c.successSubtle,
        hint: 'of ${s.expectedDays} working days',
        progress: s.expectedDays > 0 ? s.daysWorked / s.expectedDays * 100 : null,
      ),
      AccentStat(
        'Absent',
        '${s.absent}',
        icon: Icons.person_off_rounded,
        accent: c.danger,
        accentSubtle: c.dangerSubtle,
        tone: s.absent > 0 ? scheme.error : null,
        hint: s.leave > 0 ? '${s.leave} on leave' : 'No leave taken',
      ),
      AccentStat(
        'Late arrivals',
        '${s.lateDays}',
        icon: Icons.schedule_rounded,
        accent: c.warning,
        accentSubtle: c.warningSubtle,
        tone: s.lateDays > 0 ? c.warning : null,
        hint: s.lateDays > 0 ? '${formatMinutes(s.lateMinutes)} in total' : 'None',
      ),
      AccentStat(
        'Punctuality',
        s.punctuality == null ? '—' : '${s.punctuality}%',
        icon: Icons.track_changes_rounded,
        accent: scheme.primary,
        accentSubtle: primarySubtle,
        hint: 'days on time',
        progress: s.punctuality?.toDouble(),
        showPercent: false,
      ),
      AccentStat(
        'Hours worked',
        formatMinutes(s.workedMinutes),
        icon: Icons.timer_outlined,
        accent: c.info,
        accentSubtle: c.infoSubtle,
        hint: s.missingPunch > 0 ? '${s.missingPunch} missing a punch' : null,
      ),
      AccentStat('Average a day', s.avgWorkedMinutes == null ? '—' : formatMinutes(s.avgWorkedMinutes), icon: Icons.speed_rounded, accent: c.info, accentSubtle: c.infoSubtle),
      AccentStat(
        'Overtime',
        formatMinutes(s.otApprovedMinutes),
        icon: Icons.trending_up_rounded,
        accent: c.onLeave,
        accentSubtle: c.onLeaveSubtle,
        hint: s.otDetectedMinutes > s.otApprovedMinutes ? '${formatMinutes(s.otDetectedMinutes)} detected' : 'approved',
      ),
      AccentStat(
        'Early exits',
        '${s.earlyOutDays}',
        icon: Icons.logout_rounded,
        accent: c.warning,
        accentSubtle: c.warningSubtle,
        tone: s.earlyOutDays > 0 ? c.warning : null,
        hint: s.earlyOutDays > 0 ? '${formatMinutes(s.earlyOutMinutes)} in total' : 'None',
      ),
    ]);
  }

  Widget _calendar(BuildContext context, List<AttendanceDay> days, String today) {
    final scheme = Theme.of(context).colorScheme;
    final weeks = monthWeeks(_month, days, today);
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Row(children: [for (final w in _weekdays) Expanded(child: Center(child: Text(w, style: TextStyle(fontSize: 12, fontWeight: FontWeight.w600, color: scheme.onSurfaceVariant))))]),
      const SizedBox(height: 4),
      for (final week in weeks)
        Padding(
          padding: const EdgeInsets.only(bottom: 4),
          child: Row(children: [
            for (final cell in week)
              Expanded(
                child: cell == null
                    ? const SizedBox(height: 40)
                    : Padding(
                        padding: const EdgeInsets.symmetric(horizontal: 2),
                        child: _cell(context, cell),
                      ),
              ),
          ]),
        ),
      const SizedBox(height: 8),
      Wrap(spacing: 12, runSpacing: 4, children: [
        for (final b in const ['PRESENT', 'REMOTE', 'HALF_DAY', 'ABSENT', 'LEAVE', 'HOLIDAY', 'WEEKLY_OFF'])
          Row(mainAxisSize: MainAxisSize.min, children: [
            Container(
              constraints: const BoxConstraints(minWidth: 18),
              padding: const EdgeInsets.symmetric(horizontal: 3, vertical: 1),
              decoration: BoxDecoration(color: bucketShade(scheme, b), borderRadius: BorderRadius.circular(4)),
              child: Text(bucketGlyphs[b]!, textAlign: TextAlign.center, style: const TextStyle(fontSize: 9, fontWeight: FontWeight.w700)),
            ),
            const SizedBox(width: 4),
            Text(attendanceBucketLabels[b]!, style: TextStyle(fontSize: 12, color: scheme.onSurfaceVariant)),
          ]),
      ]),
    ]);
  }

  Widget _cell(BuildContext context, CalendarCell cell) {
    final scheme = Theme.of(context).colorScheme;
    final shown = cell.bucket != null && !cell.isFuture;
    final selected = _selected == cell.date;
    return Semantics(
      button: true,
      selected: selected,
      label: '${cell.date}, ${cell.bucket != null ? attendanceBucketLabels[cell.bucket] : cell.isFuture ? 'upcoming' : 'no record'}',
      child: InkWell(
        key: Key('cal-${cell.date}'),
        borderRadius: BorderRadius.circular(8),
        onTap: () => setState(() => _selected = selected ? null : cell.date),
        child: Opacity(
          opacity: cell.isFuture ? 0.5 : 1,
          child: Container(
            height: 40,
            decoration: BoxDecoration(
              color: shown ? bucketShade(scheme, cell.bucket!).withValues(alpha: 0.35) : scheme.surfaceContainerHighest.withValues(alpha: 0.5),
              borderRadius: BorderRadius.circular(8),
              border: Border.all(color: selected ? scheme.onSurface : cell.isToday ? scheme.primary : Colors.transparent, width: selected || cell.isToday ? 2 : 1),
            ),
            child: Column(mainAxisAlignment: MainAxisAlignment.center, children: [
              Text('${cell.dayOfMonth}', style: const TextStyle(fontSize: 12, fontWeight: FontWeight.w600, height: 1.1)),
              if (shown) Text(bucketGlyphs[cell.bucket!]!, style: const TextStyle(fontSize: 9, fontWeight: FontWeight.w700, height: 1.1)),
            ]),
          ),
        ),
      ),
    );
  }

  Widget _dayDetail(BuildContext context, CalendarCell? cell) {
    final scheme = Theme.of(context).colorScheme;
    if (cell == null) return const SizedBox.shrink();
    final day = cell.day;
    final zone = _zone;
    return Container(
      key: const Key('insights-day-detail'),
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(color: scheme.surfaceContainerHighest.withValues(alpha: 0.4), borderRadius: BorderRadius.circular(12), border: Border.all(color: scheme.outlineVariant)),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [
          Expanded(child: Text(_longDate(cell.date), style: const TextStyle(fontWeight: FontWeight.w700))),
          if (day != null) AttendanceStatusBadge(status: day.attendanceStatus),
        ]),
        if (day == null)
          Padding(padding: const EdgeInsets.only(top: 8), child: Text(cell.isFuture ? 'This day has not happened yet.' : 'No attendance record for this day.', style: TextStyle(color: scheme.onSurfaceVariant)))
        else ...[
          const SizedBox(height: 10),
          Wrap(spacing: 24, runSpacing: 10, children: [
            _fact(context, 'First in', formatClockTime(day.actualFirstIn, zone)),
            _fact(context, 'Last out', formatClockTime(day.actualLastOut, zone)),
            _fact(context, 'Worked', formatMinutes(day.workedMinutes)),
            _fact(context, 'Late / early out',
                '${day.raw['is_late'] == true ? formatMinutes((day.raw['late_minutes'] as num?)?.toInt()) : '—'} / ${day.raw['is_early_out'] == true ? formatMinutes((day.raw['early_departure_minutes'] as num?)?.toInt()) : '—'}'),
          ]),
          if (day.raw['holiday_name'] != null) Padding(padding: const EdgeInsets.only(top: 8), child: Text('${day.raw['holiday_name']}', style: TextStyle(color: scheme.onSurfaceVariant))),
          Align(
            alignment: Alignment.centerLeft,
            child: TextButton(
              onPressed: () => Navigator.of(context).push(MaterialPageRoute(builder: (_) => AttendanceDayDetailScreen(dayId: day.id, initial: day))),
              child: const Text('Open the full day'),
            ),
          ),
        ],
      ]),
    );
  }

  // ---- Charts ---------------------------------------------------------------------------------

  Widget _statusBreakdown(BuildContext context, List<({String bucket, int count})> items) {
    final scheme = Theme.of(context).colorScheme;
    final total = items.fold<int>(0, (n, i) => n + i.count);
    if (total == 0) return const SizedBox.shrink();
    int count(String b) => items.where((i) => i.bucket == b).firstOrNull?.count ?? 0;
    final worked = ['PRESENT', 'REMOTE', 'ON_DUTY'].fold<double>(0, (n, b) => n + count(b)) + count('HALF_DAY') * 0.5;
    final expected = ['PRESENT', 'REMOTE', 'ON_DUTY', 'HALF_DAY', 'ABSENT', 'LEAVE', 'INCOMPLETE'].fold<int>(0, (n, b) => n + count(b));
    final pct = expected == 0 ? null : (worked / expected * 100).round();
    return Container(
      key: const Key('insights-breakdown'),
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(color: scheme.primaryContainer.withValues(alpha: 0.3), borderRadius: BorderRadius.circular(12)),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [
          SizedBox(
            width: 96,
            height: 96,
            child: CustomPaint(
              painter: _RingPainter(pct: pct, track: scheme.primaryContainer, color: scheme.primary),
              child: Center(
                child: Column(mainAxisSize: MainAxisSize.min, children: [
                  Text(pct == null ? '—' : '$pct%', key: const Key('insights-ring-pct'), style: const TextStyle(fontSize: 20, fontWeight: FontWeight.w700)),
                  Text('attendance', style: TextStyle(fontSize: 10, color: scheme.onSurfaceVariant)),
                ]),
              ),
            ),
          ),
          const SizedBox(width: 16),
          Expanded(
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              const Text('Days by status', style: TextStyle(fontWeight: FontWeight.w700)),
              Text('${formatWorkedDays(worked)} of $expected working days attended', style: TextStyle(fontSize: 12, color: scheme.onSurfaceVariant)),
            ]),
          ),
        ]),
        const SizedBox(height: 12),
        for (final i in items)
          Padding(
            padding: const EdgeInsets.symmetric(vertical: 3),
            child: Row(children: [
              Container(width: 10, height: 10, decoration: BoxDecoration(color: bucketShade(scheme, i.bucket), shape: BoxShape.circle)),
              const SizedBox(width: 8),
              Expanded(child: Text(_label(i.bucket), style: TextStyle(color: scheme.onSurfaceVariant))),
              Text('${i.count}', style: const TextStyle(fontWeight: FontWeight.w700)),
            ]),
          ),
        const SizedBox(height: 8),
        ClipRRect(
          borderRadius: BorderRadius.circular(99),
          child: SizedBox(
            height: 8,
            child: Row(children: [for (final i in items) Expanded(flex: i.count, child: Container(margin: const EdgeInsets.only(right: 2), color: bucketShade(scheme, i.bucket)))]),
          ),
        ),
      ]),
    );
  }

  Widget _hoursChart(BuildContext context, ({List<DailyHoursBar> bars, int? scheduledMinutes}) data) {
    final scheme = Theme.of(context).colorScheme;
    if (data.bars.isEmpty) return const SizedBox.shrink();
    final top = math.max(math.max(data.scheduledMinutes ?? 0, data.bars.map((b) => b.minutes).reduce(math.max)), 60) * 1.2;
    const plotHeight = 112.0;
    return Container(
      key: const Key('insights-hours'),
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(border: Border.all(color: scheme.outlineVariant), borderRadius: BorderRadius.circular(12)),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        const Text('Hours each day', style: TextStyle(fontWeight: FontWeight.w700)),
        const SizedBox(height: 18),
        SizedBox(
          height: plotHeight,
          child: Stack(children: [
            if (data.scheduledMinutes != null)
              Positioned(
                left: 0,
                right: 0,
                bottom: data.scheduledMinutes! / top * plotHeight,
                child: Column(crossAxisAlignment: CrossAxisAlignment.end, children: [
                  Text('Shift ${formatMinutes(data.scheduledMinutes)}', style: TextStyle(fontSize: 10, fontWeight: FontWeight.w600, color: scheme.primary)),
                  SizedBox(height: 1, width: double.infinity, child: CustomPaint(painter: _DashPainter(scheme.primary.withValues(alpha: 0.6)))),
                ]),
              ),
            Row(crossAxisAlignment: CrossAxisAlignment.end, children: [
              for (final b in data.bars)
                Expanded(
                  child: Tooltip(
                    message: '${b.date}: ${formatMinutes(b.minutes)}${b.isLate ? ' (late)' : ''}',
                    child: Column(mainAxisAlignment: MainAxisAlignment.end, children: [
                      if (b.isLate) Container(margin: const EdgeInsets.only(bottom: 3), width: 6, height: 6, decoration: BoxDecoration(color: scheme.tertiary, shape: BoxShape.circle)),
                      Container(
                        key: Key('hours-bar-${b.date}'),
                        margin: const EdgeInsets.symmetric(horizontal: 1.5),
                        height: math.max(2, b.minutes / top * plotHeight),
                        decoration: BoxDecoration(
                          borderRadius: const BorderRadius.vertical(top: Radius.circular(5)),
                          color: b.isLate ? scheme.primary.withValues(alpha: 0.4) : scheme.primary,
                        ),
                      ),
                    ]),
                  ),
                ),
            ]),
          ]),
        ),
        const SizedBox(height: 4),
        Row(children: [for (final b in data.bars) Expanded(child: Center(child: Text('${b.dayOfMonth}', style: TextStyle(fontSize: 9, color: scheme.onSurfaceVariant))))]),
        const SizedBox(height: 6),
        Row(children: [
          Container(width: 6, height: 6, decoration: BoxDecoration(color: scheme.tertiary, shape: BoxShape.circle)),
          const SizedBox(width: 6),
          Text('Late arrival', style: TextStyle(fontSize: 12, color: scheme.onSurfaceVariant)),
        ]),
      ]),
    );
  }
}

class _RingPainter extends CustomPainter {
  _RingPainter({required this.pct, required this.track, required this.color});
  final int? pct;
  final Color track;
  final Color color;

  @override
  void paint(Canvas canvas, Size size) {
    final rect = Rect.fromCircle(center: size.center(Offset.zero), radius: size.width / 2 - 6);
    final base = Paint()
      ..style = PaintingStyle.stroke
      ..strokeWidth = 9
      ..color = track;
    canvas.drawArc(rect, 0, math.pi * 2, false, base);
    if (pct != null && pct! > 0) {
      canvas.drawArc(rect, -math.pi / 2, math.pi * 2 * (pct! / 100), false, base..color = color..strokeCap = StrokeCap.round);
    }
  }

  @override
  bool shouldRepaint(_RingPainter old) => old.pct != pct || old.color != color || old.track != track;
}

class _DashPainter extends CustomPainter {
  _DashPainter(this.color);
  final Color color;

  @override
  void paint(Canvas canvas, Size size) {
    final paint = Paint()
      ..color = color
      ..strokeWidth = 1;
    for (var x = 0.0; x < size.width; x += 8) {
      canvas.drawLine(Offset(x, 0), Offset(math.min(x + 4, size.width), 0), paint);
    }
  }

  @override
  bool shouldRepaint(_DashPainter old) => old.color != color;
}
