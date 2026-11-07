import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../core/api/api_client.dart';
import '../../../core/api/api_error.dart';
import '../../../core/auth/permissions.dart';
import '../../../core/forms/choice_sources.dart';
import '../../../core/forms/form_spec.dart' show Choice;
import '../../../core/providers.dart';
import '../../../core/time.dart';
import '../../auth/state/auth_controller.dart';
import '../../employees/domain/employee_directory.dart';
import '../../profile/presentation/profile_screen.dart' show employeeRepositoryProvider;
import '../data/attendance_repository.dart';
import '../domain/attendance_insights.dart';
import '../domain/attendance_pulse.dart';
import 'attendance_period_detail_screen.dart';
import 'attendance_reports_screen.dart';
import '../domain/attendance_reports.dart' show reportLabels;
import 'attendance_day_detail_screen.dart';
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

String _msg(Object e) => e is ApiError ? (e.status == 403 ? "You don't have permission to view this." : e.message) : 'Something went wrong.';

/// Mirrors `apps/web/src/app/app/attendance/page.tsx` (the organisation view) in its order: today's
/// rate and KPIs, needs attention, payroll readiness, the department / branch breakdown, trend,
/// punctuality, weekday pattern, work hours, overtime, leave & absence, the muster heatmap, period
/// status and the monthly summary. As on web, the days are fetched over the range widened to at
/// least 14 days ([windowRangeIso]); range panels read only the range, trends read the window.
/// Web's "who's in" list is the Team attendance screen here, so the pulse links to it.
class AttendanceInsightsScreen extends ConsumerStatefulWidget {
  const AttendanceInsightsScreen({super.key});

  @override
  ConsumerState<AttendanceInsightsScreen> createState() => _AttendanceInsightsScreenState();
}

class _AttendanceInsightsScreenState extends ConsumerState<AttendanceInsightsScreen> {
  InsightsRange _range = InsightsRange.month;
  TrendMetric _metric = TrendMetric.presentPct;
  bool _weekly = false;

  bool _loading = true;
  String? _error;
  /// Every day in the fetched window (the range widened to at least 14 days).
  List<AttendanceDay> _days = const [];
  Map<String, String> _names = const {};
  _Loaded<List<_Rec>> _overtime = _Loaded.ok(const []);
  _Loaded<List<_Rec>> _regularizations = _Loaded.ok(const []);
  _Loaded<List<_Rec>> _periods = _Loaded.ok(const []);

  /// Department and branch per employee; null when the caller cannot read the directory.
  _Loaded<Map<String, DirectoryRow>>? _directory;
  bool _byBranch = false;

  /// The period the monthly summary shows (null = the default one) and its summary rows.
  String? _periodId;
  _Loaded<List<_Rec>>? _summary;
  int _summaryRequest = 0;

  String get _zone => ref.read(authControllerProvider).user?.companyTimezone ?? 'Asia/Kolkata';
  String get _today => businessToday(_zone);
  ({String from, String to}) get _bounds => resolveInsightsRange(_range, _today);
  ({String from, String to}) get _window => windowRangeIso(_bounds.from, _bounds.to);
  List<AttendanceDay> get _rangeDays => rowsBetween(_days, _bounds.from, _bounds.to);
  bool _can(String code) => ref.read(authControllerProvider).user?.permissions.contains(code) ?? false;

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

  Future<_Loaded<List<_Rec>>> _section(Future<List<_Rec>> Function() load) async {
    try {
      return _Loaded.ok(await load());
    } catch (e) {
      return _Loaded.fail(_msg(e));
    }
  }

  Future<void> _load() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    final w = _window;
    try {
      final daysFuture = ref.read(attendanceRepositoryProvider).listAttendanceDays(dateFrom: w.from, dateTo: w.to);
      final namesFuture = loadChoices(ref.read(apiClientProvider), const ['employees']).then((c) => {for (final e in c['employees'] ?? const <Choice>[]) e.value: e.label}).catchError((_) => <String, String>{});
      final otFuture = _section(() => _all('/overtime', filters: {'date_from': w.from, 'date_to': w.to}));
      final regFuture = _section(() => _all('/regularizations', filters: {'request_status': 'SUBMITTED'}));
      final periodFuture = _section(() => _all('/attendance-periods'));
      final days = await daysFuture;
      // Attendance days carry no department or branch: look up only the people in them, batched.
      final ids = {for (final d in days) d.employeeId}.toList();
      final directoryFuture = !_can(employeeViewAll) || ids.isEmpty
          ? Future.value(null)
          : ref.read(employeeRepositoryProvider).directoryRows(ids).then<_Loaded<Map<String, DirectoryRow>>>(_Loaded.ok, onError: (Object e) => _Loaded.fail(_msg(e)));
      final names = await namesFuture;
      final ot = await otFuture;
      final regs = await regFuture;
      final periods = await periodFuture;
      final directory = await directoryFuture;
      if (!mounted) return;
      setState(() {
        _days = days;
        _names = names;
        _overtime = ot;
        _regularizations = regs;
        _periods = periods;
        _directory = directory;
      });
      _loadSummary();
    } catch (e) {
      if (mounted) setState(() => _error = _msg(e));
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Map<String, dynamic>? get _summaryPeriod {
    final list = _periods.data ?? const <_Rec>[];
    if (_periodId != null) {
      for (final p in list) {
        if (p['id'] == _periodId) return p;
      }
    }
    return pickDefaultPeriod(list, _today);
  }

  /// The chosen period's per-employee summary (live while OPEN, frozen once CLOSED).
  Future<void> _loadSummary() async {
    final period = _summaryPeriod;
    final mine = ++_summaryRequest;
    if (period == null) {
      setState(() => _summary = null);
      return;
    }
    setState(() => _summary = null);
    final loaded = await _section(() => _all('/attendance-periods/${period['id']}/summary'));
    if (mounted && mine == _summaryRequest) setState(() => _summary = loaded);
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

  Widget _stat(String label, String value, [String? hint]) => Container(
        width: 150,
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
                  onTap: i.route == null ? null : () => context.push(i.route!),
                ),
            ]),
    );
  }

  Widget _trend() {
    final w = _window;
    final points = buildTrend(_days, w.from, w.to, _metric, weekly: _weekly);
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

  Widget _leaveAbsence() {
    final rows = _rangeDays;
    final absent = rows.where((d) => attendanceBucketOf(d) == 'ABSENT').length;
    final leave = rows.where((d) => attendanceBucketOf(d) == 'LEAVE').length;
    final repeat = repeatAbsences(rows);
    return _card(
      'Leave & absence',
      Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Wrap(spacing: 8, runSpacing: 8, children: [_stat('Absent days', '$absent'), _stat('Leave days', '$leave')]),
        const SizedBox(height: 8),
        Text('Repeat absences ($repeatAbsenceThreshold+ absent days)', style: Theme.of(context).textTheme.labelLarge),
        if (repeat.isEmpty) const Padding(padding: EdgeInsets.only(top: 4), child: Text('None in this range.')),
        for (final r in repeat.take(10))
          ListTile(dense: true, contentPadding: EdgeInsets.zero, onTap: () => _openEmployee(r.employeeId), title: Text(_name(r.employeeId)), subtitle: Text('${r.leaveDays} leave day${r.leaveDays == 1 ? '' : 's'}'), trailing: Text('${r.absentDays} absent')),
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
      subtitle: 'Employee × day (the last ${dates.length} days). Tap a cell for the day.',
      rows.isEmpty
          ? const Text('No attendance days to show.')
          : Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              SingleChildScrollView(
                scrollDirection: Axis.horizontal,
                child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Row(children: [
                    const SizedBox(width: 110),
                    for (final d in dates) SizedBox(width: 22, child: Text(d.substring(8), textAlign: TextAlign.center, style: TextStyle(fontSize: 9, color: scheme.onSurfaceVariant))),
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
              Wrap(spacing: 10, runSpacing: 4, children: [
                for (final e in const [('Present', Colors.green), ('Remote', Colors.teal), ('On duty', Colors.blue), ('Half day', Colors.amber), ('Absent', Colors.red), ('Leave', Colors.purple), ('Incomplete', Colors.orange), ('Off/holiday', Colors.blueGrey)])
                  Row(mainAxisSize: MainAxisSize.min, children: [Container(width: 10, height: 10, color: e.$2), const SizedBox(width: 4), Text(e.$1, style: const TextStyle(fontSize: 10))]),
              ]),
            ]),
    );
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

  Widget _pulse() {
    final today = _bounds.to;
    final w = _window;
    final points = dailyAttendanceRate(_days, w.from, w.to);
    final focus = points.lastWhere((p) => p.date == today, orElse: () => RatePoint(today, null, 0, 0));
    final spark = points.where((p) => p.date.compareTo(today) <= 0).toList();
    final recent = spark.sublist(spark.length > minContextDays ? spark.length - minContextDays : 0);
    final distribution = statusDistribution(rowsOn(_days, today));
    final total = distribution.fold<int>(0, (a, e) => a + e.count);
    final delta = _delta(rateDelta(points, today, sameWeekdayLastWeek(today)), unit: ' pts', decimals: 1);
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
        const SizedBox(height: 14),
        Row(children: [
          Expanded(child: Text("WHO'S WHO", style: theme.textTheme.labelSmall?.copyWith(color: theme.colorScheme.onSurfaceVariant, letterSpacing: 0.6))),
          _muted('$total records'),
        ]),
        const SizedBox(height: 6),
        if (distribution.isEmpty)
          const Text('No attendance records for this date.')
        else
          Wrap(spacing: 8, runSpacing: 8, children: [
            for (final e in distribution)
              Chip(
                visualDensity: VisualDensity.compact,
                label: Text('${e.label}  ${e.count} · ${formatPct(pct(e.count, total))}'),
              ),
          ]),
        Align(
          alignment: Alignment.centerLeft,
          child: TextButton(onPressed: () => context.push('/app/team-attendance'), child: const Text("See who's in →")),
        ),
      ]),
    );
  }

  Widget _kpis() {
    final today = _bounds.to;
    final k = computeKpis(rowsOn(_days, today));
    final compareRows = rowsOn(_days, sameWeekdayLastWeek(today));
    final before = compareRows.isEmpty ? null : computeKpis(compareRows);
    final total = k.employed;
    String ofWorkforce(int n) => total > 0 ? '${formatPct(pct(n, total))} of workforce' : 'No employees in scope';
    String hint(String base, int now, int? then) => [base, if (then != null) _delta(now - then)].whereType<String>().join(' · ');
    final present = k.presentTotal;
    return _card(
      'Today',
      Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Wrap(spacing: 8, runSpacing: 8, children: [
          _stat('Total employees', '$total', 'Employed on today'),
          _stat('Present', '$present', hint(ofWorkforce(present), present, before?.presentTotal)),
          _stat('Absent', '${k.absent}', hint(ofWorkforce(k.absent), k.absent, before?.absent)),
          _stat('On leave', '${k.leave}', hint(ofWorkforce(k.leave), k.leave, before?.leave)),
          _stat('Late', '${k.late}', hint(k.checkedIn > 0 ? '${formatPct(pct(k.late, k.checkedIn))} of checked-in employees' : 'Nobody checked in yet', k.late, before?.late)),
          _stat('Not checked in', '${k.notCheckedIn}', 'Expected to work, no IN punch'),
          _stat('Remote (WFH)', '${k.remote}', present > 0 ? '${formatPct(pct(k.remote, present))} of those present' : 'Nobody present'),
          _stat(
            'Overtime',
            k.overtimeMinutesDetected > 0 ? formatMinutes(k.overtimeMinutesDetected) : 'None',
            k.overtimeEmployees > 0 ? '${k.overtimeEmployees} employee${k.overtimeEmployees == 1 ? '' : 's'} · ${formatMinutes(k.overtimeMinutesApproved)} approved' : 'No overtime detected',
          ),
        ]),
        Theme(
          data: Theme.of(context).copyWith(dividerColor: Colors.transparent),
          child: ExpansionTile(
            tilePadding: EdgeInsets.zero,
            childrenPadding: EdgeInsets.zero,
            title: const Text('More statuses', style: TextStyle(fontSize: 13)),
            children: [
              Align(
                alignment: Alignment.centerLeft,
                child: Wrap(spacing: 8, runSpacing: 8, children: [
                  _stat('On duty', '${k.onDuty}', ofWorkforce(k.onDuty)),
                  _stat('Half day', '${k.halfDay}', ofWorkforce(k.halfDay)),
                  _stat('Holiday', '${k.holiday}', ofWorkforce(k.holiday)),
                  _stat('Weekly off', '${k.weeklyOff}', ofWorkforce(k.weeklyOff)),
                  _stat('Incomplete', '${k.incomplete}', 'Needs manual resolution'),
                  _stat('Exceptions', '${k.exceptions}', 'See Needs attention for the breakdown'),
                ]),
              ),
            ],
          ),
        ),
      ]),
    );
  }

  // ---- month end -----------------------------------------------------------------------------

  /// Web shows this card only when there is an open period.
  Widget _readiness() {
    if (_periods.error != null) return const SizedBox.shrink();
    final open = [for (final p in _periods.data ?? const <_Rec>[]) if (p['status'] == 'OPEN') p];
    final period = pickDefaultPeriod(open, _today);
    if (period == null) return const SizedBox.shrink();
    final progress = periodProgress(period, _today);
    final scheme = Theme.of(context).colorScheme;
    final tone = progress.daysLeft < 0 ? scheme.error : (progress.daysLeft <= 3 ? toneColors(context, Tone.warning).fg : scheme.primary);
    final blockers = _attentionItems.where((i) => i.severity == Severity.critical || i.severity == Severity.high).toList();
    final total = blockers.fold<int>(0, (a, b) => a + b.count);
    return _card(
      'Payroll readiness',
      Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [
          Expanded(child: Text(periodTitle(period), style: const TextStyle(fontWeight: FontWeight.w600))),
          StatusChip.status('${period['status']}'),
        ]),
        const SizedBox(height: 10),
        Row(children: [
          Expanded(child: Text(periodCountdown(progress.daysLeft), style: TextStyle(fontSize: 12, fontWeight: FontWeight.w600, color: progress.daysLeft <= 3 ? tone : null))),
          _muted('Day ${progress.elapsedDays} of ${progress.totalDays}'),
        ]),
        const SizedBox(height: 6),
        Semantics(
          label: 'Period progress',
          child: LinearProgressIndicator(value: progress.fraction, minHeight: 8, color: tone, borderRadius: BorderRadius.circular(4)),
        ),
        const SizedBox(height: 10),
        Wrap(spacing: 6, runSpacing: 6, children: _periodBadges(period, yet: true)),
        const SizedBox(height: 10),
        Text('Still to clear before close', style: Theme.of(context).textTheme.labelLarge),
        if (blockers.isEmpty) Padding(padding: const EdgeInsets.only(top: 4), child: Text('Nothing urgent in $_rangeLabel.')),
        for (final b in blockers.take(4))
          Padding(
            padding: const EdgeInsets.only(top: 4),
            child: Row(children: [Expanded(child: Text(b.label)), Text('${b.count}', style: const TextStyle(fontWeight: FontWeight.w600))]),
          ),
        if (blockers.length > 4) _muted('+${blockers.length - 4} more · $total items in total'),
        const SizedBox(height: 6),
        _muted('Counts cover $_rangeLabel, not the whole period.'),
        Align(alignment: Alignment.centerLeft, child: TextButton(onPressed: () => _openPeriod(period), child: const Text('Open period →'))),
      ]),
    );
  }

  // ---- departments & branches ----------------------------------------------------------------

  static const _breakdownShown = 8;
  bool _breakdownAll = false;

  /// Shown only to callers who may read the employee directory, as on web.
  Widget _breakdown() {
    final directory = _directory;
    if (directory == null) return const SizedBox.shrink();
    const title = 'Departments & branches';
    if (directory.error != null) return _card(title, _sectionError(directory.error!));
    final rows = directory.data ?? const <String, DirectoryRow>{};
    final one = _byBranch ? 'branch' : 'department';
    final many = _byBranch ? 'branches' : 'departments';
    final stats = breakdownBy(rowsOn(_days, _bounds.to), (id) => _byBranch ? rows[id]?.branch : rows[id]?.department);
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
    final rows = rowsBetween(_days, _window.from, _window.to);
    final s = punctualitySummary(rows);
    final frequent = frequentLateArrivals(rows);
    const title = 'Punctuality';
    final subtitle = '$_windowLabel — how punctual people are, and who is late again and again.';
    if (s.checkedIn == 0) return _card(title, subtitle: subtitle, const Text('Nobody has checked in during this range, so there is no punctuality to report.'));
    final maxBand = s.bands.fold<int>(1, (m, b) => b.count > m ? b.count : m);
    return _card(
      title,
      subtitle: subtitle,
      Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Wrap(spacing: 8, runSpacing: 8, children: [
          _stat('On time', formatPct(s.onTimeRate), '${s.onTime} of ${s.checkedIn} check-ins'),
          _stat('Late arrivals', '${s.late}', '${formatPct(s.lateRate)} of check-ins'),
          _stat('Average lateness', s.avgLateMinutes == null ? '—' : '${s.avgLateMinutes!.round()} min', 'On late days only'),
        ]),
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

  Widget _weekdays() {
    final stats = weekdayAbsence(rowsBetween(_days, _window.from, _window.to));
    const title = 'Absence by weekday';
    final subtitle = '$_windowLabel — share of expected days missed, per weekday.';
    if (stats.every((s) => s.expected == 0)) return _card(title, subtitle: subtitle, const Text('No expected working days in this range.'));
    final worst = worstWeekday(stats);
    return _card(
      title,
      subtitle: subtitle,
      Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        if (worst != null) Text('${worst.label}s have the highest absence — ${formatPct(worst.rate)} of expected days.'),
        const SizedBox(height: 8),
        MiniColumnChart(bars: [for (final s in stats) ChartBar(s.label, s.rate)], format: (v) => formatPct(v), color: toneColors(context, Tone.danger).fg),
      ]),
    );
  }

  // ---- periods -------------------------------------------------------------------------------

  Widget _periodStatus() {
    const title = 'Attendance periods';
    const subtitle = 'Payroll-facing cycles, one per company.';
    if (_periods.error != null) return _card(title, subtitle: subtitle, _sectionError(_periods.error!));
    final list = [...?_periods.data]..sort((a, b) => '${b['period_start']}'.compareTo('${a['period_start']}'));
    return _card(
      title,
      subtitle: subtitle,
      Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        if (list.isEmpty) const Text('No attendance periods yet. Periods are opened per company.'),
        for (final p in list.take(6))
          ListTile(
            contentPadding: EdgeInsets.zero,
            title: Text(periodTitle(p)),
            subtitle: Padding(
              padding: const EdgeInsets.only(top: 4),
              child: Wrap(spacing: 6, runSpacing: 6, children: [StatusChip.status('${p['status']}'), ..._periodBadges(p)]),
            ),
            trailing: const Icon(Icons.chevron_right_rounded),
            onTap: () => _openPeriod(p),
          ),
        _muted('As of ${shortDate(_today)}.'),
        Align(alignment: Alignment.centerLeft, child: TextButton(onPressed: () => context.push('/app/attendance-periods'), child: const Text('All periods →'))),
      ]),
    );
  }

  Widget _monthlySummary() {
    const title = 'Monthly attendance summary';
    const subtitle = 'Employee-days across the period, as Payroll will read them.';
    if (_periods.error != null) return _card(title, subtitle: subtitle, _sectionError(_periods.error!));
    final period = _summaryPeriod;
    if (period == null) return _card(title, subtitle: subtitle, const Text('No attendance period to summarise. Open a period for a company first.'));
    final list = [...?_periods.data]..sort((a, b) => '${b['period_start']}'.compareTo('${a['period_start']}'));
    final summary = _summary;
    Widget body;
    if (summary == null) {
      body = const Padding(padding: EdgeInsets.all(12), child: Center(child: CircularProgressIndicator()));
    } else if (summary.error != null) {
      body = Column(crossAxisAlignment: CrossAxisAlignment.start, children: [_sectionError(summary.error!), TextButton(onPressed: _loadSummary, child: const Text('Try again'))]);
    } else {
      final t = sumPeriodSummary(summary.data ?? const []);
      body = Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Wrap(spacing: 8, crossAxisAlignment: WrapCrossAlignment.center, children: [
          _badge(t.frozen ? 'Frozen snapshot' : 'Live preview', t.frozen ? Tone.neutral : Tone.info),
          _muted('${t.employees} employee${t.employees == 1 ? '' : 's'}'),
        ]),
        const SizedBox(height: 10),
        Wrap(spacing: 8, runSpacing: 8, children: [
          for (final (label, field) in periodDayFields) _stat(label, formatDays(t.values[field])),
          _stat('Overtime', formatMinutes(t.otMinutes)),
          _stat('Late count', '${t.lateCount}'),
        ]),
      ]);
    }
    return _card(
      title,
      subtitle: subtitle,
      Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        if (list.length > 1)
          DropdownButton<String>(
            isExpanded: true,
            value: period['id'] as String,
            items: [for (final p in list) DropdownMenuItem(value: p['id'] as String, child: Text(periodTitle(p), overflow: TextOverflow.ellipsis))],
            onChanged: (id) {
              setState(() => _periodId = id);
              _loadSummary();
            },
          ),
        body,
      ]),
    );
  }

  /// Web's Reports panel lives on its own screen here; it reuses what this screen loaded.
  Widget _reportsCard() => _card(
        'Reports',
        subtitle: '$_rangeLabel. Read-only views of existing attendance data.',
        Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          _muted(reportLabels.values.join(' · ')),
          Align(
            alignment: Alignment.centerLeft,
            child: TextButton(
              onPressed: () => Navigator.of(context).push(MaterialPageRoute(
                builder: (_) => AttendanceReportsScreen(
                  days: _rangeDays,
                  overtime: _rangeOvertime,
                  overtimeError: _overtime.error,
                  periods: _periods.data,
                  name: _name,
                  zone: _zone,
                  today: _today,
                  rangeLabel: _rangeLabel,
                ),
              )),
              child: const Text('Open reports →'),
            ),
          ),
        ]),
      );

  @override
  Widget build(BuildContext context) {
    Widget body;
    if (_loading) {
      body = const ListSkeleton();
    } else if (_error != null) {
      body = StateMessage(icon: Icons.error_outline_rounded, tone: Tone.danger, title: 'Something went wrong', message: _error!, actionLabel: 'Retry', onAction: _load);
    } else {
      body = RefreshIndicator(
        onRefresh: _load,
        child: ListView(padding: const EdgeInsets.all(16), children: [
          _pulse(),
          _kpis(),
          _needsAttention(),
          _readiness(),
          _breakdown(),
          _trend(),
          _punctuality(),
          _weekdays(),
          _workHours(),
          _overtimeCard(),
          _leaveAbsence(),
          _heatmap(),
          _periodStatus(),
          _monthlySummary(),
          _reportsCard(),
        ]),
      );
    }
    return Scaffold(
      appBar: AppBar(title: const Text('Attendance insights')),
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
    );
  }
}
