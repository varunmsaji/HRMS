import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../core/api/api_client.dart';
import '../../../core/api/api_error.dart';
import '../../../core/auth/permissions.dart' show attendanceViewAll;
import '../../../core/forms/choice_sources.dart';
import '../../../core/forms/form_spec.dart' show Choice;
import '../../../core/providers.dart';
import '../../../core/time.dart';
import '../../auth/state/auth_controller.dart';
import '../data/attendance_repository.dart';
import '../domain/attendance_export.dart';
import '../domain/attendance_insights.dart';
import '../domain/attendance_mismatch.dart' show attentionRank;
import '../domain/attendance_pulse.dart';
import '../domain/attendance_totals.dart';
import '../domain/pattern_alerts.dart';
import 'attendance_export_dialog.dart';
import 'attendance_period_detail_screen.dart';
import 'attendance_reports_screen.dart';
import 'attendance_day_detail_screen.dart';
import 'attendance_mismatches_screen.dart';
import 'employee_attendance_profile_screen.dart';
import 'attendance_summary.dart';
import 'insight_charts.dart';
import '../../../core/widgets/ui.dart';

typedef _Rec = Map<String, dynamic>;

/// A section that loads independently: one failing or permission-denied panel never blanks the
/// rest (same rule as the web `useSection`).
class _Loaded<T> {
  _Loaded.ok(this.data) : error = null;
  _Loaded.fail(this.error) : data = null;
  final T? data;
  final String? error;
}

String _msg(Object e) => e is ApiError ? (e.status == 403 ? "You don't have permission to view this." : describeApiError(e)) : 'Something went wrong.';

/// Mirrors the organisation view of `apps/web/src/app/app/attendance/page.tsx`, which has three
/// tabs. **Today**: the attendance rate beside five tappable figures (each opens Team attendance
/// narrowed to them), needs attention, payroll readiness when the period needs a look, and the
/// attendance grid. **Trends**: departments and branches, the trend, punctuality, absence and
/// leave, work hours, overtime. **Reports**: the six reports. The attendance periods and the
/// monthly summary are on the Attendance Periods screen, as on web.
///
/// As on web, everything covers the range widened to at least 14 days ([windowRangeIso]); range
/// panels read only the range, trends read the window. The totals (rate, figures, trend,
/// punctuality, weekday pattern, department / branch breakdown) are the backend's
/// (`GET /v1/attendance/summary`); the per-person panels read the attendance days. Web's "who's in"
/// list is the Team attendance screen here.
class AttendanceInsightsScreen extends ConsumerStatefulWidget {
  const AttendanceInsightsScreen({super.key});

  @override
  ConsumerState<AttendanceInsightsScreen> createState() => _AttendanceInsightsScreenState();
}

class _AttendanceInsightsScreenState extends ConsumerState<AttendanceInsightsScreen> {
  InsightsRange _range = InsightsRange.month;
  TrendMetric _metric = TrendMetric.presentPct;
  bool _weekly = false;
  /// The muster as the employee × day grid (wide) rather than a list for one day (the phone default).
  bool _musterGrid = false;
  String? _musterDay;

  bool _loading = true;
  String? _error;
  /// Every day in the fetched window (the range widened to at least 14 days).
  List<AttendanceDay> _days = const [];
  /// Null until loaded; truncated when the window holds more days than the page ceiling.
  DaysCoverage? _coverage;
  Map<String, String> _names = const {};
  _Loaded<List<_Rec>> _overtime = _Loaded.ok(const []);
  _Loaded<List<_Rec>> _regularizations = _Loaded.ok(const []);
  _Loaded<List<_Rec>> _periods = _Loaded.ok(const []);

  /// The window's totals, counted by the backend; null until loaded.
  _Loaded<AttendanceTotals>? _totals;
  bool _byBranch = false;

  /// People with a repeating pattern, up to the end of the range. Null when the caller may not see
  /// it (the card is then left out); an error shows on the card only.
  _Loaded<PatternAlerts>? _patterns;

  /// The organisation view. Web offers the payroll report only there (`showPayroll`).
  bool get _canViewAll => (ref.read(authControllerProvider).user?.permissions ?? const <String>[]).contains(attendanceViewAll);

  String get _zone => ref.read(authControllerProvider).user?.companyTimezone ?? 'Asia/Kolkata';
  String get _today => businessToday(_zone);
  ({String from, String to}) get _bounds => resolveInsightsRange(_range, _today);
  ({String from, String to}) get _window => windowRangeIso(_bounds.from, _bounds.to);
  List<AttendanceDay> get _rangeDays => rowsBetween(_days, _bounds.from, _bounds.to);

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<List<_Rec>> _all(String path, {Map<String, dynamic>? filters}) async {
    final client = ref.read(apiClientProvider);
    final out = <_Rec>[];
    for (var page = 1; page <= 50; page++) {
      final env = await client.getList<_Rec>(path, query: PageQuery(page: page, perPage: 100), filters: filters, parseItem: (d) => d as _Rec);
      out.addAll(env.data);
      if (env.pagination == null || !env.pagination!.hasNext) break;
    }
    return out;
  }

  Future<_Loaded<List<_Rec>>> _section(Future<List<_Rec>> Function() load) => _loaded(load);

  Future<_Loaded<T>> _loaded<T>(Future<T> Function() load) async {
    try {
      return _Loaded<T>.ok(await load());
    } catch (e) {
      return _Loaded<T>.fail(_msg(e));
    }
  }

  Future<void> _load() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    final w = _window;
    try {
      final repo = ref.read(attendanceRepositoryProvider);
      final daysFuture = repo.listAttendanceDaysCovered(dateFrom: w.from, dateTo: w.to);
      final totalsFuture = _loaded(() => repo.attendanceSummary(dateFrom: w.from, dateTo: w.to));
      final patternsFuture = () async {
        try {
          return _Loaded<PatternAlerts>.ok(await repo.patternAlerts(asOf: _bounds.to));
        } catch (e) {
          return e is ApiError && e.status == 403 ? null : _Loaded<PatternAlerts>.fail(_msg(e));
        }
      }();
      final namesFuture = loadChoices(ref.read(apiClientProvider), const ['employees']).then((c) => {for (final e in c['employees'] ?? const <Choice>[]) e.value: e.label}).catchError((_) => <String, String>{});
      final otFuture = _section(() => _all('/overtime', filters: {'date_from': w.from, 'date_to': w.to}));
      final regFuture = _section(() => _all('/regularizations', filters: {'request_status': 'SUBMITTED'}));
      final periodFuture = _section(() => _all('/attendance-periods'));
      final days = await daysFuture;
      final totals = await totalsFuture;
      final names = await namesFuture;
      final patterns = await patternsFuture;
      final ot = await otFuture;
      final regs = await regFuture;
      final periods = await periodFuture;
      if (!mounted) return;
      setState(() {
        _days = days.days;
        _coverage = days;
        _names = names;
        _overtime = ot;
        _regularizations = regs;
        _periods = periods;
        _totals = totals;
        _patterns = patterns;
      });
    } catch (e) {
      if (mounted) setState(() => _error = _msg(e));
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  /// The employee's attendance profile, as web links each name to `/app/attendance/employee/[id]`.
  void _openEmployee(String employeeId) => Navigator.of(context).push(MaterialPageRoute(builder: (_) => EmployeeAttendanceProfileScreen(employeeId: employeeId, employeeLabel: _name(employeeId))));

  void _openPeriod(_Rec p) => Navigator.of(context).push(MaterialPageRoute(builder: (_) => AttendancePeriodDetailScreen(periodId: p['id'] as String, initial: p)));

  String _name(String id) => _names[id] ?? 'Employee ${id.substring(0, id.length < 8 ? id.length : 8)}';

  Widget _card(String title, Widget child, {String? subtitle}) => Padding(
        padding: const EdgeInsets.only(bottom: 12),
        child: AppCard(
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text(title, style: Theme.of(context).textTheme.titleMedium?.copyWith(fontWeight: FontWeight.w700)),
            if (subtitle != null) Text(subtitle, style: TextStyle(fontSize: 12, color: Theme.of(context).colorScheme.onSurfaceVariant)),
            const SizedBox(height: 10),
            child,
          ]),
        ),
      );

  Widget _stat(String label, String value, [String? hint, double width = 150]) => Container(
        width: width,
        padding: const EdgeInsets.all(12),
        decoration: BoxDecoration(color: Theme.of(context).colorScheme.surfaceContainerLow, borderRadius: BorderRadius.circular(14)),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(label, style: TextStyle(fontSize: 11.5, color: Theme.of(context).colorScheme.onSurfaceVariant)),
          const SizedBox(height: 2),
          Text(value, style: const TextStyle(fontSize: 18, fontWeight: FontWeight.w800)),
          if (hint != null && hint.isNotEmpty) Text(hint, style: TextStyle(fontSize: 11, color: Theme.of(context).colorScheme.onSurfaceVariant)),
        ]),
      );

  Widget _sectionError(String message) => Text(message, style: TextStyle(color: Theme.of(context).colorScheme.error));

  // ---- sections -----------------------------------------------------------------------------

  /// Overtime records inside the selected range (they are fetched over the wider window).
  List<_Rec> get _rangeOvertime {
    final b = _bounds;
    return [
      for (final r in _overtime.data ?? const <_Rec>[])
        if ('${r['attendance_date']}'.compareTo(b.from) >= 0 && '${r['attendance_date']}'.compareTo(b.to) <= 0) r,
    ];
  }

  List<AttentionItem> get _attentionItems => buildAttentionItems(
        rows: _rangeDays,
        pendingRegularizations: _regularizations.data?.length ?? 0,
        pendingOvertime: _rangeOvertime.where((r) => r['status'] == 'PENDING').length,
        blockedPeriods: (_periods.data ?? const []).where((p) => p['status'] == 'OPEN' && p['last_validation_status'] == 'BLOCKED').length,
      );

  Widget _needsAttention() {
    final items = _attentionItems;
    final scheme = Theme.of(context).colorScheme;
    Color sev(Severity s) => switch (s) {
          Severity.critical => scheme.error,
          Severity.high => Colors.deepOrange,
          Severity.medium => Colors.amber.shade800,
          Severity.low => scheme.onSurfaceVariant,
        };
    return _card(
      'Needs attention',
      items.isEmpty
          ? const Text('Nothing needs attention in this range.')
          : Column(children: [
              for (final i in items)
                ListTile(
                  dense: true,
                  contentPadding: EdgeInsets.zero,
                  leading: Icon(Icons.circle, size: 12, color: sev(i.severity)),
                  title: Text(i.label),
                  subtitle: Text('${i.hint}${i.employees != null ? ' · ${i.employees} employee${i.employees == 1 ? '' : 's'}' : ''}', style: const TextStyle(fontSize: 12)),
                  trailing: Text('${i.count} ${i.unit}', style: const TextStyle(fontWeight: FontWeight.w600)),
                  onTap: i.route != null
                      ? () => context.push(i.route!)
                      : i.fixable
                          ? () => Navigator.of(context).push(MaterialPageRoute(builder: (_) => AttendanceMismatchesScreen(from: _bounds.from, to: _bounds.to)))
                          : null,
                ),
            ]),
    );
  }

  /// "Patterns to look at": people who keep being late or absent. A prompt to look, not a finding;
  /// each names the days behind it and opens the person's attendance profile (web `PatternAlertsPanel`).
  Widget _patternAlerts() {
    final loaded = _patterns;
    if (loaded == null) return const SizedBox.shrink();
    final data = loaded.data;
    if (data == null) return _card('Patterns to look at', _sectionError(loaded.error ?? 'Pattern alerts could not be loaded.'));
    final t = data.thresholds;
    return _card(
      'Patterns to look at',
      data.alerts.isEmpty
          ? const Text('No patterns found. Nobody has crossed a threshold.')
          : Column(children: [
              for (final a in data.alerts)
                ListTile(
                  dense: true,
                  contentPadding: EdgeInsets.zero,
                  onTap: () => _openEmployee(a.employeeId),
                  title: Text(_name(a.employeeId)),
                  subtitle: Text('${a.label}: ${a.describe(t)}\n${a.dates.map(shortDate).join(', ')}${a.count > a.dates.length ? ' and ${a.count - a.dates.length} earlier' : ''}', style: const TextStyle(fontSize: 12)),
                  isThreeLine: true,
                ),
            ]),
      subtitle: 'People who keep being late or absent: ${t.lateDays}+ late days, ${t.absentDays}+ absent days or ${t.incompleteDays}+ missing punches in ${t.windowDays} days, or the same weekday ${t.weekdayAbsences}+ times in ${t.weekdayWindowDays} days. A prompt to look, not a finding.',
    );
  }

  /// The totals, or a card saying why they are missing (that card only, not the whole screen).
  AttendanceTotals? get _t => _totals?.data;
  Widget _totalsUnavailable(String title) => _card(title, _sectionError(_totals?.error ?? 'Attendance totals could not be loaded.'));

  Widget _trend() {
    final t = _t;
    if (t == null) return _totalsUnavailable('Attendance trend');
    final w = _window;
    final points = buildTrend(t.daily, w.from, w.to, _metric, weekly: _weekly);
    final isHours = _metric == TrendMetric.avgHours;
    return _card(
      'Attendance trend',
      Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Wrap(spacing: 6, runSpacing: 4, children: [
          for (final m in TrendMetric.values) ChoiceChip(label: Text(trendMetricLabels[m]!), selected: _metric == m, onSelected: (_) => setState(() => _metric = m)),
        ]),
        SwitchListTile(dense: true, contentPadding: EdgeInsets.zero, title: const Text('Group by week'), value: _weekly, onChanged: (v) => setState(() => _weekly = v)),
        MiniColumnChart(
          bars: [for (final p in points) ChartBar(p.label, p.value)],
          format: (v) => isHours ? '${v.toStringAsFixed(1)}h' : '${v.round()}%',
          maxValue: isHours ? null : 100,
        ),
      ]),
    );
  }

  /// Absence and leave over the range, with the weekday pattern (web "Absence & leave").
  Widget _absenceLeave() {
    final rows = _rangeDays;
    final absent = rows.where((d) => attendanceBucketOf(d) == 'ABSENT').length;
    final leave = rows.where((d) => attendanceBucketOf(d) == 'LEAVE').length;
    final repeat = repeatAbsences(rows);
    return _card(
      'Absence & leave',
      subtitle: '$_rangeLabel — operational view; Leave stays the system of record.',
      Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Wrap(spacing: 8, runSpacing: 8, children: [_stat('Absent days', '$absent'), _stat('Leave days', '$leave')]),
        const SizedBox(height: 8),
        Text('Repeat absences ($repeatAbsenceThreshold+ absent days)', style: Theme.of(context).textTheme.labelLarge),
        if (repeat.isEmpty) const Padding(padding: EdgeInsets.only(top: 4), child: Text('None in this range.')),
        for (final r in repeat.take(10))
          ListTile(dense: true, contentPadding: EdgeInsets.zero, onTap: () => _openEmployee(r.employeeId), title: Text(_name(r.employeeId)), subtitle: Text('${r.leaveDays} leave day${r.leaveDays == 1 ? '' : 's'}'), trailing: Text('${r.absentDays} absent')),
        const SizedBox(height: 12),
        Text('By weekday', style: Theme.of(context).textTheme.labelLarge),
        _muted('$_windowLabel — share of expected days missed.'),
        const SizedBox(height: 6),
        _weekdayPattern(),
      ]),
    );
  }

  Widget _workHours() {
    final w = _window;
    final s = summarizeWorkHours(_rangeDays);
    final daily = dailyHours(_days, w.from, w.to);
    final dev = s.deviationMinutes;
    return _card(
      'Work hours',
      Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Wrap(spacing: 8, runSpacing: 8, children: [
          _stat('Total worked', formatMinutes(s.totalMinutes), '${s.checkedInDays} checked-in day${s.checkedInDays == 1 ? '' : 's'}'),
          _stat('Average per day', formatMinutes(s.avgMinutes), 'Per checked-in day'),
          _stat('Expected', formatMinutes(s.expectedMinutes), 'Scheduled, days attended'),
          _stat('Deviation', '${dev > 0 ? '+' : ''}${formatMinutes(dev)}', dev < 0 ? 'Below schedule' : dev > 0 ? 'Above schedule' : 'On schedule'),
          _stat('Under-time', formatMinutes(s.underTimeMinutes), 'Complete days short of schedule'),
          _stat('Overtime', formatMinutes(s.otDetectedMinutes), '${formatMinutes(s.otApprovedMinutes)} approved'),
        ]),
        const SizedBox(height: 12),
        Text('Worked hours per day (red tick = scheduled)', style: Theme.of(context).textTheme.labelLarge),
        const SizedBox(height: 6),
        MiniColumnChart(
          bars: [for (final d in daily) ChartBar(d.label, d.workedMinutes.toDouble(), reference: d.scheduledMinutes.toDouble())],
          format: (v) => '${(v / 60).toStringAsFixed(1)}h',
        ),
      ]),
    );
  }

  Widget _overtimeCard() {
    if (_overtime.error != null) return _card('Overtime', _sectionError(_overtime.error!));
    final b = _bounds;
    final w = _window;
    // Totals cover the range; the per-day trend keeps the window's context, as on web.
    final s = summarizeOvertime(_rangeOvertime, b.from, b.to)..trend = summarizeOvertime(_overtime.data ?? const [], w.from, w.to).trend;
    final maxClass = s.byDayClass.fold<int>(1, (m, c) => c.minutes > m ? c.minutes : m);
    return _card(
      'Overtime',
      Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Wrap(spacing: 8, runSpacing: 8, children: [
          _stat('Total detected', formatMinutes(s.totalDetectedMinutes), '${formatMinutes(s.totalApprovedMinutes)} approved'),
          _stat('Employees with OT', '${s.employees}', s.avgDetectedPerEmployee != null ? '${formatMinutes(s.avgDetectedPerEmployee)} average each' : ''),
          _stat('Pending approval', '${s.pendingCount}', s.pendingCount > 0 ? '${formatMinutes(s.pendingMinutes)} waiting' : 'None waiting'),
          _stat('Approved', '${s.approvedCount}', 'Incl. auto-approved'),
          _stat('Rejected', '${s.rejectedCount}'),
        ]),
        if (s.byDayClass.isNotEmpty) ...[
          const SizedBox(height: 12),
          Text('By day class', style: Theme.of(context).textTheme.labelLarge),
          for (final c in s.byDayClass)
            Padding(
              padding: const EdgeInsets.symmetric(vertical: 3),
              child: Row(children: [
                SizedBox(width: 84, child: Text(overtimeDayClassLabels[c.dayClass] ?? 'Unclassified', style: const TextStyle(fontSize: 12))),
                Expanded(child: LinearProgressIndicator(value: c.minutes / maxClass, minHeight: 8, borderRadius: BorderRadius.circular(4))),
                SizedBox(width: 64, child: Text(formatMinutes(c.minutes), textAlign: TextAlign.end, style: const TextStyle(fontSize: 12))),
              ]),
            ),
        ],
        const SizedBox(height: 12),
        Text('Overtime per day', style: Theme.of(context).textTheme.labelLarge),
        const SizedBox(height: 6),
        MiniColumnChart(bars: [for (final t in s.trend) ChartBar(t.label, t.minutes.toDouble())], format: (v) => '${(v / 60).toStringAsFixed(1)}h'),
        Align(alignment: Alignment.centerLeft, child: TextButton(onPressed: () => context.push('/app/overtime'), child: const Text('Open overtime records →'))),
      ]),
    );
  }

  Widget _heatmap() {
    final w = _window;
    final dates = musterDates(w.from, w.to);
    final rows = buildMuster(_days, dates, _name);
    final scheme = Theme.of(context).colorScheme;
    Color colorFor(AttendanceDay d) => switch (attendanceBucketOf(d)) {
          'PRESENT' => Colors.green,
          'REMOTE' => Colors.teal,
          'ON_DUTY' => Colors.blue,
          'HALF_DAY' => Colors.amber,
          'ABSENT' => Colors.red,
          'LEAVE' => Colors.purple,
          'INCOMPLETE' => Colors.orange,
          'CONFIG_ERROR' => Colors.deepOrange,
          'HOLIDAY' || 'WEEKLY_OFF' => Colors.blueGrey,
          _ => Colors.grey,
        };
    return _card(
      'Attendance heatmap',
      subtitle: _musterGrid ? 'Employee × day (the last ${dates.length} days). Tap a cell for the day.' : 'Who was where on one day. Pick a day; tap a person for the day.',
      rows.isEmpty
          ? const Text('No attendance days to show.')
          : Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Align(
                alignment: Alignment.centerLeft,
                child: OutlinedButton.icon(
                  key: const ValueKey('muster_export'),
                  icon: const Icon(Icons.download_outlined),
                  label: const Text('Export register'),
                  onPressed: () => showAttendanceExport(
                    context,
                    ref,
                    title: 'Export attendance register',
                    filePrefix: 'muster',
                    from: _bounds.from,
                    to: _bounds.to,
                    today: _today,
                    path: musterExportPath,
                    pdfLimited: true,
                  ),
                ),
              ),
              const SizedBox(height: 8),
              SegmentedButton<bool>(
                key: const ValueKey('muster_switch'),
                showSelectedIcon: false,
                segments: const [ButtonSegment(value: false, label: Text('List')), ButtonSegment(value: true, label: Text('Grid'))],
                selected: {_musterGrid},
                onSelectionChanged: (v) => setState(() => _musterGrid = v.first),
              ),
              const SizedBox(height: 10),
              if (!_musterGrid) _musterList(dates, rows, colorFor),
              if (_musterGrid) ...[
              SingleChildScrollView(
                scrollDirection: Axis.horizontal,
                child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Row(children: [
                    const SizedBox(width: 110),
                    for (final d in dates) SizedBox(width: 22, child: Text(d.substring(8), textAlign: TextAlign.center, style: TextStyle(fontSize: 11, color: scheme.onSurfaceVariant))),
                  ]),
                  for (final r in rows)
                    Row(children: [
                      SizedBox(width: 110, child: Text(r.name, maxLines: 1, overflow: TextOverflow.ellipsis, style: const TextStyle(fontSize: 11))),
                      for (final d in dates)
                        Builder(builder: (context) {
                          final cell = r.cells[d];
                          return GestureDetector(
                            onTap: cell == null ? null : () => Navigator.of(context).push(MaterialPageRoute(builder: (_) => AttendanceDayDetailScreen(dayId: cell.id, initial: cell))),
                            child: Container(width: 20, height: 20, margin: const EdgeInsets.all(1), decoration: BoxDecoration(color: cell == null ? scheme.surfaceContainerHighest : colorFor(cell), borderRadius: BorderRadius.circular(3))),
                          );
                        }),
                    ]),
                ]),
              ),
              const SizedBox(height: 8),
              ],
              Wrap(spacing: 10, runSpacing: 4, children: [
                for (final e in const [('Present', Colors.green), ('Remote', Colors.teal), ('On duty', Colors.blue), ('Half day', Colors.amber), ('Absent', Colors.red), ('Leave', Colors.purple), ('Incomplete', Colors.orange), ('Off/holiday', Colors.blueGrey)])
                  Row(mainAxisSize: MainAxisSize.min, children: [Container(width: 10, height: 10, color: e.$2), const SizedBox(width: 4), Text(e.$1, style: const TextStyle(fontSize: 11))]),
              ]),
            ]),
    );
  }

  /// The muster for one day: a chip per day, then everyone with their status, worst first.
  Widget _musterList(List<String> dates, List<MusterRow> rows, Color Function(AttendanceDay) colorFor) {
    final scheme = Theme.of(context).colorScheme;
    final day = dates.contains(_musterDay) ? _musterDay! : dates.last;
    final withCell = [for (final r in rows) if (r.cells[day] != null) (r, r.cells[day]!)]..sort((a, b) => attentionRank(a.$2).compareTo(attentionRank(b.$2)));
    final none = rows.length - withCell.length;
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      SizedBox(
        height: 44,
        child: ListView(scrollDirection: Axis.horizontal, children: [
          for (final d in dates.reversed) // newest first, so the day shown is the first chip
            Padding(
              padding: const EdgeInsets.only(right: 6),
              child: ChoiceChip(key: ValueKey('muster_day:$d'), label: Text(shortDate(d)), selected: d == day, onSelected: (_) => setState(() => _musterDay = d)),
            ),
        ]),
      ),
      for (final (r, cell) in withCell)
        ListTile(
          dense: true,
          contentPadding: EdgeInsets.zero,
          leading: Container(width: 12, height: 12, decoration: BoxDecoration(color: colorFor(cell), shape: BoxShape.circle)),
          title: Text(r.name, maxLines: 1, overflow: TextOverflow.ellipsis),
          trailing: Text(attendanceBucketLabels[attendanceBucketOf(cell)] ?? cell.attendanceStatus, style: TextStyle(fontSize: 12, color: scheme.onSurfaceVariant)),
          onTap: () => Navigator.of(context).push(MaterialPageRoute(builder: (_) => AttendanceDayDetailScreen(dayId: cell.id, initial: cell))),
        ),
      if (withCell.isEmpty) const Padding(padding: EdgeInsets.symmetric(vertical: 8), child: Text('No attendance records for this day.')),
      if (none > 0 && withCell.isNotEmpty) _muted('$none other ${none == 1 ? 'employee' : 'employees'} with records in these days ${none == 1 ? 'has' : 'have'} none on this day. Anyone with no record at all in this period is not listed here.'),
    ]);
  }

  String get _rangeLabel {
    final b = _bounds;
    return b.from == b.to ? shortDate(b.to) : '${shortDate(b.from)} – ${shortDate(b.to)}';
  }

  String get _windowLabel => '${shortDate(_window.from)} – ${shortDate(_window.to)}';

  /// "+2 vs last Tue" — web's delta chip as text; null when there is nothing to compare.
  String? _delta(num? change, {String unit = '', int decimals = 0}) {
    if (change == null) return null;
    final sign = change > 0 ? '+' : (change < 0 ? '−' : '±');
    return '$sign${change.abs().toStringAsFixed(decimals)}$unit vs last ${weekdayShort(sameWeekdayLastWeek(_bounds.to))}';
  }

  Widget _muted(String text) => Text(text, style: TextStyle(fontSize: 12, color: Theme.of(context).colorScheme.onSurfaceVariant));

  Widget _badge(String label, Tone tone) => StatusChip(label: label, tone: tone, dot: false);

  /// Web's validation badges for an OPEN period, plus "Reopened".
  List<Widget> _periodBadges(_Rec p, {bool yet = false}) => [
        if (p['status'] == 'OPEN' && p['last_validation_status'] == 'BLOCKED') _badge('Validation blocked', Tone.danger),
        if (p['status'] == 'OPEN' && p['last_validation_status'] == 'READY') _badge('Ready to finalize', Tone.success),
        if (p['status'] == 'OPEN' && p['last_validation_status'] == null) _badge(yet ? 'Not validated yet' : 'Not validated', Tone.neutral),
        if (p['reopened_at'] != null) _badge('Reopened', Tone.warning),
      ];

  // ---- today ---------------------------------------------------------------------------------

  /// The attendance rate for the focus day, beside what it is compared with and the last two weeks.
  Widget _ratePulse() {
    final t = _t;
    if (t == null) return _totalsUnavailable('Attendance at a glance');
    final focus = t.focusDay;
    final spark = t.daily.where((p) => p.date.compareTo(t.focusDate) <= 0).toList();
    final recent = spark.sublist(spark.length > minContextDays ? spark.length - minContextDays : 0);
    final delta = _delta(t.rateDelta, unit: ' pts', decimals: 1);
    final theme = Theme.of(context);
    return _card(
      'Attendance at a glance',
      Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text('ATTENDANCE RATE TODAY', style: theme.textTheme.labelSmall?.copyWith(color: theme.colorScheme.onSurfaceVariant, letterSpacing: 0.6)),
        Wrap(crossAxisAlignment: WrapCrossAlignment.end, spacing: 10, children: [
          Text(formatPct(focus.rate), style: theme.textTheme.headlineMedium?.copyWith(fontWeight: FontWeight.w800)),
          if (delta != null) Padding(padding: const EdgeInsets.only(bottom: 6), child: _muted(delta)),
        ]),
        _muted(focus.rate == null ? 'Nobody was expected to work on this day.' : '${focus.present} of ${focus.expected} expected employees attended.'),
        const SizedBox(height: 10),
        MiniColumnChart(bars: [for (final p in recent) ChartBar(shortDate(p.date), p.rate)], format: (v) => '${v.round()}%', maxValue: 100, height: 70),
        _muted('Last ${recent.length} days'),
      ]),
    );
  }

  /// Opens Team attendance on the focus day, narrowed to a status bucket or a flag.
  void _openTeam({String? bucket, String? flag, int? missing}) {
    final t = _t;
    final query = {if (t != null) 'date': t.focusDate, if (bucket != null) 'bucket': bucket, if (flag != null) 'flag': flag, if (missing != null && missing > 0) 'missing': '$missing'};
    context.push(Uri(path: '/app/team-attendance', queryParameters: query.isEmpty ? null : query).toString());
  }

  /// One tappable figure: opens the list of the people behind it.
  Widget _tile(String label, String value, String hint, {String? bucket, String? flag, int? missing, double width = 150}) => Semantics(
        key: ValueKey('tile:$label'),
        button: true,
        label: '$label: $value. $hint. Show these employees.',
        child: InkWell(
          borderRadius: BorderRadius.circular(14),
          onTap: () => _openTeam(bucket: bucket, flag: flag, missing: missing),
          child: ExcludeSemantics(child: _stat(label, value, hint, width)),
        ),
      );

  static const _moreStatusesKey = 'more_statuses';
  bool _moreStatuses = false;

  /// The headcount as a line, five everyday figures, and the rarer ones behind "More statuses"
  /// (web `KpiGrid`). Each figure opens Team attendance narrowed to those employees.
  Widget _summaryBlock() {
    final t = _t;
    if (t == null) return _totalsUnavailable('Today');
    final k = t.focus;
    final before = t.compare;
    final total = k.totalEmployees;
    String ofWorkforce(int n) => total > 0 ? '${formatPct(pct(n, total))} of workforce' : 'No employees in scope';
    String hint(String base, int now, int? then) => [base, if (then != null) _delta(now - then)].whereType<String>().join(' · ');
    final present = k.presentTotal;
    final more = <(String, String, String, String?, String?)>[
      // Shown only when the engine produced work-from-home days (R-B05); today it never does.
      if (k.remote > 0) ('Remote (WFH)', '${k.remote}', present > 0 ? '${formatPct(pct(k.remote, present))} of those present' : 'Nobody present', 'REMOTE', null),
      (
        'Overtime',
        k.overtimeMinutesDetected > 0 ? formatMinutes(k.overtimeMinutesDetected) : 'None',
        k.overtimeEmployees > 0 ? '${k.overtimeEmployees} employee${k.overtimeEmployees == 1 ? '' : 's'} · ${formatMinutes(k.overtimeMinutesApproved)} approved' : 'No overtime detected',
        null,
        'overtime'
      ),
      ('On duty', '${k.onDuty}', ofWorkforce(k.onDuty), 'ON_DUTY', null),
      ('Half day', '${k.halfDay}', ofWorkforce(k.halfDay), 'HALF_DAY', null),
      ('Holiday', '${k.holiday}', ofWorkforce(k.holiday), 'HOLIDAY', null),
      ('Weekly off', '${k.weeklyOff}', ofWorkforce(k.weeklyOff), 'WEEKLY_OFF', null),
      ('Incomplete', '${k.incomplete}', 'Needs manual resolution', 'INCOMPLETE', null),
    ];
    final moreWithData = [k.remote, k.overtimeEmployees, k.onDuty, k.halfDay, k.holiday, k.weeklyOff, k.incomplete, k.exceptions].where((n) => n > 0).length;
    return _card(
      'Today',
      Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        _muted('$total ${total == 1 ? 'employee' : 'employees'} · ${k.noRecord > 0 ? '${k.noRecord} with no record yet for today' : 'employed today'}'),
        if (t.calculatedAt != null)
          _muted(t.focusDate == _today ? 'Last calculated at ${formatClockTime(t.calculatedAt, _zone)}.' : 'Last calculated ${formatDateTime(t.calculatedAt, _zone)}.'),
        const SizedBox(height: 10),
        LayoutBuilder(builder: (context, box) {
          final w = (box.maxWidth - 8) / 2;
          return Wrap(spacing: 8, runSpacing: 8, children: [
            _tile('Present', '$present', hint(ofWorkforce(present), present, before?.presentTotal), bucket: attendingBucketKey, width: w),
            _tile('Absent', '${k.absent}', hint(ofWorkforce(k.absent), k.absent, before?.absent), bucket: 'ABSENT', width: w),
            _tile('On leave', '${k.leave}', hint(ofWorkforce(k.leave), k.leave, before?.leave), bucket: 'LEAVE', width: w),
            _tile('Late', '${k.late}', hint(k.checkedIn > 0 ? '${formatPct(pct(k.late, k.checkedIn))} of checked-in employees' : 'Nobody checked in yet', k.late, before?.late), flag: 'late', width: w),
            _tile('Not checked in', '${k.notCheckedIn}', k.noRecord > 0 ? 'No IN punch, or no record yet' : 'Expected to work, no IN punch', flag: 'not_checked_in', missing: k.noRecord, width: w),
          ]);
        }),
        const SizedBox(height: 4),
        TextButton.icon(
          key: const ValueKey(_moreStatusesKey),
          onPressed: () => setState(() => _moreStatuses = !_moreStatuses),
          icon: Icon(_moreStatuses ? Icons.expand_less_rounded : Icons.expand_more_rounded, size: 18),
          label: Text(_moreStatuses ? 'Fewer statuses' : 'More statuses${moreWithData > 0 ? ' ($moreWithData with data)' : ''}'),
        ),
        if (_moreStatuses)
          LayoutBuilder(builder: (context, box) {
            final w = (box.maxWidth - 8) / 2;
            return Wrap(spacing: 8, runSpacing: 8, children: [
              for (final (label, value, context, bucket, flag) in more) _tile(label, value, context, bucket: bucket, flag: flag, width: w),
              // Exceptions have no list of their own: the breakdown is in Needs attention.
              _stat('Exceptions', '${k.exceptions}', 'See Needs attention for the breakdown', w),
            ]);
          }),
        Align(alignment: Alignment.centerLeft, child: TextButton(onPressed: () => _openTeam(), child: const Text("See who's in →"))),
      ]),
    );
  }

  // ---- month end -----------------------------------------------------------------------------

  /// Month-end at a glance, as one compact card. Web shows it only when the open period needs a
  /// look: something is in the way of closing it, validation is blocked, or it ends within three
  /// days (`payrollNeedsAttention`).
  Widget _readiness() {
    if (_periods.error != null) return const SizedBox.shrink();
    final open = [for (final p in _periods.data ?? const <_Rec>[]) if (p['status'] == 'OPEN') p];
    final period = pickDefaultPeriod(open, _today);
    if (period == null) return const SizedBox.shrink();
    final progress = periodProgress(period, _today);
    final blockers = _attentionItems.where((i) => i.severity == Severity.critical || i.severity == Severity.high).toList();
    final blocked = period['last_validation_status'] == 'BLOCKED';
    if (blockers.isEmpty && !blocked && progress.daysLeft > 3) return const SizedBox.shrink();
    final scheme = Theme.of(context).colorScheme;
    final tone = progress.daysLeft < 0 ? scheme.error : (progress.daysLeft <= 3 ? toneColors(context, Tone.warning).fg : scheme.primary);
    final total = blockers.fold<int>(0, (a, b) => a + b.count);
    return _card(
      'Payroll readiness',
      Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [
          Expanded(child: Text(periodTitle(period), style: const TextStyle(fontWeight: FontWeight.w600))),
          Text(periodCountdown(progress.daysLeft), style: TextStyle(fontSize: 12, fontWeight: FontWeight.w600, color: tone)),
        ]),
        const SizedBox(height: 8),
        Wrap(spacing: 6, runSpacing: 6, children: _periodBadges(period, yet: true)),
        const SizedBox(height: 8),
        _muted(blockers.isEmpty ? 'Nothing urgent in $_rangeLabel.' : '$total item${total == 1 ? '' : 's'} to clear before close: ${blockers.take(3).map((b) => b.label).join(', ')}${blockers.length > 3 ? ' and ${blockers.length - 3} more' : ''}. Counts cover $_rangeLabel.'),
        Align(alignment: Alignment.centerLeft, child: TextButton(onPressed: () => _openPeriod(period), child: const Text('Open period →'))),
      ]),
    );
  }

  // ---- departments & branches ----------------------------------------------------------------

  static const _breakdownShown = 8;
  bool _breakdownAll = false;

  /// Each department / branch on the focus day, by the assignment in force that day.
  Widget _breakdown() {
    const title = 'Departments & branches';
    final t = _t;
    if (t == null) return _totalsUnavailable(title);
    final one = _byBranch ? 'branch' : 'department';
    final many = _byBranch ? 'branches' : 'departments';
    final stats = _byBranch ? t.byBranch : t.byDepartment;
    final shown = _breakdownAll ? stats : stats.take(_breakdownShown).toList();
    return _card(
      title,
      subtitle: 'Who is in, and who is missing, in each part of the company.',
      Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Wrap(spacing: 6, children: [
          ChoiceChip(label: const Text('Department'), selected: !_byBranch, onSelected: (_) => setState(() => _byBranch = false)),
          ChoiceChip(label: const Text('Branch'), selected: _byBranch, onSelected: (_) => setState(() => _byBranch = true)),
        ]),
        const SizedBox(height: 4),
        _muted('Today · lowest attendance first'),
        const SizedBox(height: 6),
        if (stats.isEmpty)
          Text('No attendance records on this day to group by $one.')
        else if (stats.length == 1)
          Text('Everyone is in one $one (${stats.single.name}), so there is nothing to compare.')
        else ...[
          for (final g in shown)
            Padding(
              padding: const EdgeInsets.symmetric(vertical: 5),
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Row(children: [
                  Expanded(child: Text(g.name, style: const TextStyle(fontWeight: FontWeight.w600), maxLines: 1, overflow: TextOverflow.ellipsis)),
                  Text(g.rate == null ? 'Nobody expected' : '${g.present} of ${g.expected} · ${formatPct(g.rate)}', style: const TextStyle(fontSize: 12)),
                ]),
                const SizedBox(height: 4),
                LinearProgressIndicator(value: (g.rate ?? 0) / 100, minHeight: 6, borderRadius: BorderRadius.circular(3)),
                const SizedBox(height: 2),
                _muted('${g.absent} absent · ${g.leave} on leave · ${g.late} late'),
              ]),
            ),
          if (stats.length > _breakdownShown)
            TextButton(onPressed: () => setState(() => _breakdownAll = !_breakdownAll), child: Text(_breakdownAll ? 'Show fewer' : 'Show all ${stats.length} $many')),
        ],
      ]),
    );
  }

  // ---- patterns ------------------------------------------------------------------------------

  Widget _punctuality() {
    const title = 'Punctuality';
    final t = _t;
    if (t == null) return _totalsUnavailable(title);
    final s = t.punctuality;
    final frequent = t.frequentLate;
    final subtitle = '$_windowLabel — how punctual people are, and who is late again and again.';
    if (s.checkedIn == 0) return _card(title, subtitle: subtitle, const Text('Nobody has checked in during this range, so there is no punctuality to report.'));
    final maxBand = s.bands.fold<int>(1, (m, b) => b.count > m ? b.count : m);
    return _card(
      title,
      subtitle: subtitle,
      Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Wrap(spacing: 8, runSpacing: 8, children: [
          _stat('On time', formatPct(s.onTimeRate), '${s.onTime} of ${s.checkedIn} completed days'),
          _stat('Late arrivals', '${s.late}', '${formatPct(s.lateRate)} of completed days'),
          _stat('Average lateness', s.avgLateMinutes == null ? '—' : '${s.avgLateMinutes!.round()} min', 'On late days only'),
        ]),
        const SizedBox(height: 6),
        _muted('A completed day has both an IN and an OUT punch. A day still open is not judged yet, so these figures can differ from the Late tile, which counts every check-in.'),
        if (s.late > 0) ...[
          const SizedBox(height: 12),
          Text('How late', style: Theme.of(context).textTheme.labelLarge),
          for (final b in s.bands)
            Padding(
              padding: const EdgeInsets.symmetric(vertical: 3),
              child: Row(children: [
                SizedBox(width: 92, child: Text(b.label, style: const TextStyle(fontSize: 12))),
                Expanded(child: LinearProgressIndicator(value: b.count / maxBand, minHeight: 8, color: toneColors(context, Tone.warning).fg, borderRadius: BorderRadius.circular(4))),
                SizedBox(width: 32, child: Text('${b.count}', textAlign: TextAlign.end, style: const TextStyle(fontSize: 12))),
              ]),
            ),
        ],
        const SizedBox(height: 12),
        Text('Late more than once', style: Theme.of(context).textTheme.labelLarge),
        if (frequent.isEmpty)
          Padding(
            padding: const EdgeInsets.only(top: 4),
            child: Text(s.late == 0 ? 'Everyone who checked in was on time.' : 'Nobody has been late more than once in this range.'),
          ),
        for (final f in frequent)
          ListTile(dense: true, contentPadding: EdgeInsets.zero, onTap: () => _openEmployee(f.employeeId), title: Text(_name(f.employeeId)), trailing: Text('${f.lateDays} days · ${f.totalLateMinutes} min')),
      ]),
    );
  }

  Widget _weekdayPattern() {
    final t = _t;
    if (t == null) return _sectionError(_totals?.error ?? 'Attendance totals could not be loaded.');
    final stats = t.weekdayAbsence;
    if (stats.every((s) => s.expected == 0)) return const Text('No expected working days in this range.');
    final worst = worstWeekday(stats);
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      if (worst != null) Text('${worst.label}s have the highest absence — ${formatPct(worst.rate)} of expected days.'),
      const SizedBox(height: 8),
      MiniColumnChart(bars: [for (final s in stats) ChartBar(s.label, s.rate)], format: (v) => formatPct(v), color: toneColors(context, Tone.danger).fg),
    ]);
  }

 // ---- tabs ----------------------------------------------------------------------------------

  Widget _tab(List<Widget> children) => RefreshIndicator(onRefresh: _load, child: ListView(padding: const EdgeInsets.all(16), children: [if (_partialNote() case final note?) note, ...children]));

  /// Web's partial-data note (`attendance/page.tsx`): the totals are the server's and complete,
  /// the per-person panels only cover the days that were loaded.
  Widget? _partialNote() {
    final c = _coverage;
    if (c == null || !c.truncated) return null;
    return Padding(
      key: const ValueKey('days-truncated'),
      padding: const EdgeInsets.only(bottom: 12),
      child: _muted('Totals and charts count every attendance record, but the employee lists, heatmap and reports show the most recent ${_count(c.loaded)} of ${_count(c.total)} in this range. Choose a shorter range to list them all.'),
    );
  }

  static String _count(int n) => n.toString().replaceAllMapped(RegExp(r'(\d)(?=(\d{3})+$)'), (m) => '${m[1]},');

  @override
  Widget build(BuildContext context) {
    Widget body;
    if (_loading) {
      body = const ListSkeleton();
    } else if (_error != null) {
      body = StateMessage(icon: Icons.error_outline_rounded, tone: Tone.danger, title: "Couldn't load insights", message: _error!, actionLabel: 'Try again', onAction: _load);
    } else {
      // Swiping is off: the attendance grid and the charts scroll sideways, and a swipe there must not change tab.
      body = TabBarView(physics: const NeverScrollableScrollPhysics(), children: [
        _tab([_ratePulse(), _summaryBlock(), _needsAttention(), _patternAlerts(), _readiness(), _heatmap()]),
        _tab([_breakdown(), _trend(), _punctuality(), _absenceLeave(), _workHours(), _overtimeCard()]),
        AttendanceReportsPanel(partialNote: _partialNote(), showPayroll: _canViewAll, days: _rangeDays, overtime: _rangeOvertime, overtimeError: _overtime.error, periods: _periods.data, name: _name, zone: _zone, today: _today, rangeLabel: _rangeLabel, exportFrom: _bounds.from, exportTo: _bounds.to),
      ]);
    }
    return DefaultTabController(
      length: 3,
      child: Scaffold(
        appBar: AppBar(
          title: const Text('Attendance insights'),
          bottom: const TabBar(tabs: [Tab(text: 'Today'), Tab(text: 'Trends'), Tab(text: 'Reports')]),
        ),
        body: Column(children: [
          SingleChildScrollView(
            scrollDirection: Axis.horizontal,
            padding: const EdgeInsets.fromLTRB(16, 8, 16, 0),
            child: Row(children: [
              for (final r in InsightsRange.values)
                Padding(
                  padding: const EdgeInsets.only(right: 6),
                  child: ChoiceChip(
                    label: Text(insightsRangeLabels[r]!),
                    selected: _range == r,
                    onSelected: (_) {
                      setState(() => _range = r);
                      _load();
                    },
                  ),
                ),
            ]),
          ),
          Expanded(child: body),
        ]),
      ),
    );
  }
}
