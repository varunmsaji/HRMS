import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../core/api/api_client.dart';
import '../../../core/api/api_error.dart';
import '../../../core/forms/choice_sources.dart';
import '../../../core/forms/form_spec.dart' show Choice;
import '../../../core/providers.dart';
import '../../../core/time.dart';
import '../../auth/state/auth_controller.dart';
import '../data/attendance_repository.dart';
import '../domain/attendance_insights.dart';
import 'attendance_day_detail_screen.dart';
import 'attendance_summary.dart';
import 'insight_charts.dart';

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

/// Mirrors the range panels of `apps/web/src/app/app/attendance/page.tsx`: needs-attention, trend,
/// leave & absence, work hours, overtime and the muster heatmap, over a selectable range. The
/// department/location/work-mode breakdowns are "not available" on the web too (attendance days
/// carry no department, branch or work-mode), so the same note is shown instead.
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
  List<AttendanceDay> _days = const [];
  Map<String, String> _names = const {};
  _Loaded<List<_Rec>> _overtime = _Loaded.ok(const []);
  _Loaded<List<_Rec>> _regularizations = _Loaded.ok(const []);
  _Loaded<List<_Rec>> _periods = _Loaded.ok(const []);

  String get _zone => ref.read(authControllerProvider).user?.companyTimezone ?? 'Asia/Kolkata';
  ({String from, String to}) get _bounds => resolveInsightsRange(_range, businessToday(_zone));

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
    final b = _bounds;
    try {
      final daysFuture = ref.read(attendanceRepositoryProvider).listAttendanceDays(dateFrom: b.from, dateTo: b.to);
      final namesFuture = loadChoices(ref.read(apiClientProvider), const ['employees']).then((c) => {for (final e in c['employees'] ?? const <Choice>[]) e.value: e.label}).catchError((_) => <String, String>{});
      final otFuture = _section(() => _all('/overtime', filters: {'date_from': b.from, 'date_to': b.to}));
      final regFuture = _section(() => _all('/regularizations', filters: {'request_status': 'SUBMITTED'}));
      final periodFuture = _section(() => _all('/attendance-periods'));
      final days = await daysFuture;
      final names = await namesFuture;
      final ot = await otFuture;
      final regs = await regFuture;
      final periods = await periodFuture;
      if (!mounted) return;
      setState(() {
        _days = days;
        _names = names;
        _overtime = ot;
        _regularizations = regs;
        _periods = periods;
      });
    } catch (e) {
      if (mounted) setState(() => _error = _msg(e));
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  String _name(String id) => _names[id] ?? 'Employee ${id.substring(0, id.length < 8 ? id.length : 8)}';

  Widget _card(String title, Widget child, {String? subtitle}) => Card(
        margin: const EdgeInsets.only(bottom: 12),
        child: Padding(
          padding: const EdgeInsets.all(12),
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text(title, style: Theme.of(context).textTheme.titleSmall?.copyWith(fontWeight: FontWeight.w700)),
            if (subtitle != null) Text(subtitle, style: TextStyle(fontSize: 12, color: Theme.of(context).colorScheme.onSurfaceVariant)),
            const SizedBox(height: 8),
            child,
          ]),
        ),
      );

  Widget _stat(String label, String value, [String? hint]) => Container(
        width: 150,
        padding: const EdgeInsets.all(8),
        decoration: BoxDecoration(border: Border.all(color: Theme.of(context).colorScheme.outlineVariant), borderRadius: BorderRadius.circular(8)),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(label, style: TextStyle(fontSize: 11, color: Theme.of(context).colorScheme.onSurfaceVariant)),
          Text(value, style: const TextStyle(fontSize: 16, fontWeight: FontWeight.w700)),
          if (hint != null && hint.isNotEmpty) Text(hint, style: TextStyle(fontSize: 11, color: Theme.of(context).colorScheme.onSurfaceVariant)),
        ]),
      );

  Widget _sectionError(String message) => Text(message, style: TextStyle(color: Theme.of(context).colorScheme.error));

  // ---- sections -----------------------------------------------------------------------------

  Widget _needsAttention() {
    final blocked = (_periods.data ?? const []).where((p) => p['status'] == 'OPEN' && p['last_validation_status'] == 'BLOCKED').length;
    final items = buildAttentionItems(
      rows: _days,
      pendingRegularizations: _regularizations.data?.length ?? 0,
      pendingOvertime: (_overtime.data ?? const []).where((r) => r['status'] == 'PENDING').length,
      blockedPeriods: blocked,
    );
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
    final b = _bounds;
    final points = buildTrend(_days, b.from, b.to, _metric, weekly: _weekly);
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
    final absent = _days.where((d) => attendanceBucketOf(d) == 'ABSENT').length;
    final leave = _days.where((d) => attendanceBucketOf(d) == 'LEAVE').length;
    final repeat = repeatAbsences(_days);
    return _card(
      'Leave & absence',
      Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Wrap(spacing: 8, runSpacing: 8, children: [_stat('Absent days', '$absent'), _stat('Leave days', '$leave')]),
        const SizedBox(height: 8),
        Text('Repeat absences ($repeatAbsenceThreshold+ absent days)', style: Theme.of(context).textTheme.labelLarge),
        if (repeat.isEmpty) const Padding(padding: EdgeInsets.only(top: 4), child: Text('None in this range.')),
        for (final r in repeat.take(10))
          ListTile(dense: true, contentPadding: EdgeInsets.zero, title: Text(_name(r.employeeId)), subtitle: Text('${r.leaveDays} leave day${r.leaveDays == 1 ? '' : 's'}'), trailing: Text('${r.absentDays} absent')),
      ]),
    );
  }

  Widget _workHours() {
    final b = _bounds;
    final s = summarizeWorkHours(_days);
    final daily = dailyHours(_days, b.from, b.to);
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
    final s = summarizeOvertime(_overtime.data ?? const [], b.from, b.to);
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
    final b = _bounds;
    final dates = musterDates(b.from, b.to);
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
      subtitle: 'Employee × day (last ${dates.length} days of the range). Tap a cell for the day.',
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

  Widget _breakdowns() => _card(
        'Department, location & work-mode breakdowns',
        Text(
          "Not available yet: attendance days carry no department, branch, designation or work-mode, so these breakdowns can't be built without one request per employee. The web dashboard shows the same limitation.",
          style: TextStyle(fontSize: 12, color: Theme.of(context).colorScheme.onSurfaceVariant),
        ),
      );

  @override
  Widget build(BuildContext context) {
    Widget body;
    if (_loading) {
      body = const Center(child: CircularProgressIndicator());
    } else if (_error != null) {
      body = Center(
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: Column(mainAxisSize: MainAxisSize.min, children: [
            Text(_error!, textAlign: TextAlign.center),
            const SizedBox(height: 16),
            FilledButton(onPressed: _load, child: const Text('Retry')),
          ]),
        ),
      );
    } else {
      body = RefreshIndicator(
        onRefresh: _load,
        child: ListView(padding: const EdgeInsets.all(16), children: [
          _needsAttention(),
          _trend(),
          _leaveAbsence(),
          _workHours(),
          _overtimeCard(),
          _heatmap(),
          _breakdowns(),
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
