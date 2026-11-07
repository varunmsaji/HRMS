import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api/api_error.dart';
import '../../../core/auth/permissions.dart';
import '../../../core/nav/nav_entries.dart' show attendanceCalendarReads;
import '../../../core/theme/employee_tokens.dart';
import '../../../core/time.dart';
import '../../../core/widgets/employee/status_map.dart';
import '../../../core/widgets/ui.dart';
import '../../auth/state/auth_controller.dart';
import '../../profile/data/employee_repository.dart';
import '../data/attendance_repository.dart';
import '../data/roster_repository.dart';
import '../domain/employee_calendar.dart' show formatMonthKey, shiftMonthKey;
import '../domain/hr_calendar.dart';
import 'attendance_day_detail_screen.dart';
import 'attendance_summary.dart';
import 'employee_attendance_panel.dart';

/// HR view: every employee's attendance for a month as one calendar — mirrors
/// `apps/web/src/app/app/attendance/calendar/page.tsx`. Names stay put while the days scroll sideways.
/// Tap a box for that day, or a name for that person's month.
class AttendanceCalendarScreen extends ConsumerStatefulWidget {
  const AttendanceCalendarScreen({super.key, this.now});

  /// Overrides the clock (tests). Null = now.
  final DateTime? now;

  @override
  ConsumerState<AttendanceCalendarScreen> createState() => _AttendanceCalendarScreenState();
}

/// A month for a whole company is a lot of cells for a phone, so people are shown in batches.
const _batch = 50;
const _nameWidth = 116.0;
const _dayWidth = 34.0;
const _totalWidth = 38.0;
const _rowHeight = 38.0;

/// The same letters as the web: colour is never the only signal, and several statuses share an icon.
const _bucketGlyphs = {
  'PRESENT': 'P',
  'REMOTE': 'R',
  'ON_DUTY': 'OD',
  'HALF_DAY': '½',
  'ABSENT': 'A',
  'LEAVE': 'L',
  'INCOMPLETE': '!',
  'CONFIG_ERROR': 'E',
  'HOLIDAY': 'H',
  'WEEKLY_OFF': 'W',
  'NON_WORKING': '–',
  'NOT_EMPLOYED': '·',
};

const _weekdayLetters = ['M', 'T', 'W', 'T', 'F', 'S', 'S'];

class _AttendanceCalendarScreenState extends ConsumerState<AttendanceCalendarScreen> {
  late final String _today;
  late String _month;
  String _query = '';
  int _shown = _batch;

  ({List<AttendanceDay> items, int total})? _days;
  ({List<Employee> rows, bool more})? _employees;
  ApiError? _error;
  bool _loading = true;
  int _request = 0;

  bool get _allowed {
    final permissions = ref.read(authControllerProvider).user?.permissions ?? const <String>[];
    return permissions.contains(attendanceViewAll) && attendanceCalendarReads.every(permissions.contains);
  }
  String get _zone => ref.read(authControllerProvider).user?.companyTimezone ?? 'Asia/Kolkata';

  @override
  void initState() {
    super.initState();
    _today = businessToday(_zone, now: widget.now);
    _month = _today.substring(0, 7);
    if (_allowed) _load();
  }

  /// A slower answer for a month the user has left never overwrites the current one.
  Future<void> _load() async {
    final mine = ++_request;
    setState(() {
      _loading = true;
      _error = null;
    });
    final dates = hrMonthDates(_month);
    try {
      final people = _employees ?? await ref.read(rosterRepositoryProvider).listBoardEmployees();
      final days = await ref.read(attendanceRepositoryProvider).listMonthDays(dateFrom: dates.first, dateTo: dates.last);
      if (!mounted || mine != _request) return;
      setState(() {
        _employees = people;
        _days = days;
      });
    } catch (e) {
      if (mounted && mine == _request) setState(() => _error = e is ApiError ? e : ApiError(status: 0, code: 'UNKNOWN_ERROR', message: 'Something went wrong.'));
    } finally {
      if (mounted && mine == _request) setState(() => _loading = false);
    }
  }

  void _goTo(String month) {
    setState(() {
      _month = month;
      _days = null;
      _shown = _batch;
    });
    _load();
  }

  void _openDay(AttendanceDay day) => Navigator.of(context).push(MaterialPageRoute(builder: (_) => AttendanceDayDetailScreen(dayId: day.id, initial: day)));

  void _openEmployee(HrCalendarRow row) => Navigator.of(context).push(MaterialPageRoute(
        builder: (_) => Scaffold(appBar: AppBar(title: Text(row.name)), body: EmployeeAttendancePanel(employeeId: row.employeeId, employeeLabel: row.name)),
      ));

  @override
  Widget build(BuildContext context) {
    if (!_allowed) {
      return Scaffold(
        appBar: AppBar(title: const Text('Attendance calendar')),
        body: const StateMessage(icon: Icons.lock_outline_rounded, title: 'No access', message: "The attendance calendar is available to HR and people who can view everyone's attendance."),
      );
    }
    final scheme = Theme.of(context).colorScheme;
    final muted = TextStyle(fontSize: 12, color: scheme.onSurfaceVariant);
    final thisMonth = _today.substring(0, 7);
    final days = _days;
    final people = _employees;
    final dates = hrMonthDates(_month);
    final rows = days == null || people == null ? null : filterHrRows(buildHrCalendar(days.items, people.rows, dates), _query);
    final used = <String>{for (final d in days?.items ?? const <AttendanceDay>[]) attendanceBucketOf(d)};
    return Scaffold(
      appBar: AppBar(title: const Text('Attendance calendar')),
      body: RefreshIndicator(
        onRefresh: _load,
        child: ListView(padding: const EdgeInsets.fromLTRB(16, 12, 16, 32), children: [
          Row(children: [
            IconButton(tooltip: 'Previous month', onPressed: () => _goTo(shiftMonthKey(_month, -1)), icon: const Icon(Icons.chevron_left)),
            Expanded(child: Text(formatMonthKey(_month), textAlign: TextAlign.center, style: const TextStyle(fontWeight: FontWeight.w700))),
            IconButton(tooltip: 'Next month', onPressed: _month.compareTo(thisMonth) >= 0 ? null : () => _goTo(shiftMonthKey(_month, 1)), icon: const Icon(Icons.chevron_right)),
          ]),
          if (_month != thisMonth) Center(child: TextButton(onPressed: () => _goTo(thisMonth), child: const Text('This month'))),
          const SizedBox(height: 4),
          AppSearchField(
            hint: 'Search name or code',
            onChanged: (v) => setState(() {
              _query = v;
              _shown = _batch;
            }),
          ),
          const SizedBox(height: 10),
          if (people != null && people.more) Padding(padding: const EdgeInsets.only(bottom: 8), child: Text('Showing the first ${people.rows.length} employees.', style: muted)),
          if (days != null && days.total > days.items.length)
            Padding(
              padding: const EdgeInsets.only(bottom: 8),
              child: Text('This month has more attendance records than could be loaded (${days.items.length} of ${days.total}), so some boxes may be missing.', style: TextStyle(color: scheme.error)),
            ),
          if (_error != null)
            StateMessage(icon: Icons.error_outline_rounded, tone: Tone.danger, title: "Couldn't load the calendar", message: _error!.status == 403 ? 'You do not have permission to view attendance for everyone.' : _error!.message, actionLabel: 'Retry', onAction: _load)
          else if (rows == null)
            const Padding(padding: EdgeInsets.all(32), child: Center(child: CircularProgressIndicator(strokeWidth: 2.5)))
          else if (rows.isEmpty)
            const StateMessage(icon: Icons.people_outline, title: 'No employees match.')
          else ...[
            if (_loading) const LinearProgressIndicator(),
            Wrap(spacing: 12, runSpacing: 4, children: [
              for (final bucket in attendanceBucketLabels.keys)
                if (used.contains(bucket)) _LegendItem(bucket: bucket),
            ]),
            const SizedBox(height: 10),
            _grid(context, rows.take(_shown).toList(), dates),
            if (rows.length > _shown) Center(child: TextButton(onPressed: () => setState(() => _shown += _batch), child: Text('Show more (${rows.length - _shown} left)'))),
            const SizedBox(height: 8),
            Text('P = days present, A = absent, L = on leave, Late = late arrivals. A dot means no attendance record for that day.', style: muted),
          ],
        ]),
      ),
    );
  }

  Widget _grid(BuildContext context, List<HrCalendarRow> rows, List<String> dates) {
    final scheme = Theme.of(context).colorScheme;
    final t = EmployeeTokens.of(context);
    final scale = MediaQuery.textScalerOf(context).scale(1);
    final height = _rowHeight * scale;
    final line = Border(bottom: BorderSide(color: scheme.outlineVariant));

    Widget total(String value, Color? color) => Container(
          width: _totalWidth * scale,
          height: height,
          alignment: Alignment.center,
          decoration: BoxDecoration(border: line),
          child: Text(value, style: TextStyle(fontSize: 12, fontWeight: FontWeight.w600, color: color)),
        );

    Widget header(String top, {String? bottom, double width = _dayWidth, Color? color}) => Container(
          width: width * scale,
          height: height,
          alignment: Alignment.center,
          decoration: BoxDecoration(border: line),
          child: Column(mainAxisAlignment: MainAxisAlignment.center, children: [
            Text(top, style: TextStyle(fontSize: 11, fontWeight: FontWeight.w600, color: color ?? scheme.onSurfaceVariant)),
            if (bottom != null) Text(bottom, style: TextStyle(fontSize: 10, color: color ?? scheme.onSurfaceVariant)),
          ]),
        );

    Widget dayCell(HrCalendarRow row, String date) {
      final day = row.cells[date];
      final isToday = date == _today;
      if (day == null) {
        return Container(width: _dayWidth * scale, height: height, alignment: Alignment.center, decoration: BoxDecoration(border: line), child: Text('·', style: TextStyle(color: scheme.onSurfaceVariant)));
      }
      final bucket = attendanceBucketOf(day);
      final status = statusForAttendanceBucket(bucket);
      final colors = statusColors(context, status.kind);
      final times = day.actualFirstIn == null ? '' : ', in ${formatClockTime(day.actualFirstIn, _zone)}${day.actualLastOut == null ? '' : ', out ${formatClockTime(day.actualLastOut, _zone)}'}';
      return Container(
        width: _dayWidth * scale,
        height: height,
        decoration: BoxDecoration(border: line),
        child: Semantics(
          label: '${row.name}, $date: ${attendanceBucketLabels[bucket] ?? bucket}$times',
          button: true,
          excludeSemantics: true,
          child: InkWell(
            onTap: () => _openDay(day),
            child: Container(
              margin: const EdgeInsets.all(2),
              alignment: Alignment.center,
              decoration: BoxDecoration(color: colors.fill, borderRadius: BorderRadius.circular(5), border: isToday ? Border.all(color: t.action, width: 1.5) : null),
              child: Text(_bucketGlyphs[bucket] ?? '–', style: TextStyle(fontSize: 10, fontWeight: FontWeight.w700, color: colors.text)),
            ),
          ),
        ),
      );
    }

    return Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Column(children: [
        Container(width: _nameWidth, height: height, alignment: Alignment.centerLeft, decoration: BoxDecoration(border: line), child: Text('Employee', style: TextStyle(fontSize: 12, fontWeight: FontWeight.w600, color: scheme.onSurfaceVariant))),
        for (final row in rows)
          Container(
            width: _nameWidth,
            height: height,
            alignment: Alignment.centerLeft,
            padding: const EdgeInsets.only(right: 6),
            decoration: BoxDecoration(border: line),
            child: InkWell(onTap: () => _openEmployee(row), child: Text(row.name, maxLines: 2, overflow: TextOverflow.ellipsis, style: TextStyle(fontSize: 12, fontWeight: FontWeight.w500, color: scheme.primary))),
          ),
      ]),
      Expanded(
        child: SingleChildScrollView(
          scrollDirection: Axis.horizontal,
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Row(children: [
              for (final d in dates)
                header(d.substring(8), bottom: _weekdayLetters[DateTime.parse('${d}T00:00:00Z').weekday - 1], color: d == _today ? scheme.primary : null),
              for (final h in const ['P', 'A', 'L', 'Late']) header(h, width: _totalWidth),
            ]),
            for (final row in rows)
              Row(children: [
                for (final d in dates) dayCell(row, d),
                total(formatHrCount(row.present), t.successText),
                total('${row.absent}', t.dangerText),
                total('${row.leave}', t.onLeaveText),
                total('${row.late}', t.warningText),
              ]),
          ]),
        ),
      ),
    ]);
  }
}

class _LegendItem extends StatelessWidget {
  const _LegendItem({required this.bucket});
  final String bucket;

  @override
  Widget build(BuildContext context) {
    final status = statusForAttendanceBucket(bucket);
    final colors = statusColors(context, status.kind);
    return Row(mainAxisSize: MainAxisSize.min, children: [
      Text(_bucketGlyphs[bucket] ?? '–', style: TextStyle(fontSize: 11, fontWeight: FontWeight.w700, color: colors.text)),
      const SizedBox(width: 4),
      Flexible(child: Text(attendanceBucketLabels[bucket] ?? bucket, style: TextStyle(fontSize: 11, color: Theme.of(context).colorScheme.onSurfaceVariant))),
    ]);
  }
}
