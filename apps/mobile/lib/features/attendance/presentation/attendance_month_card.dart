import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api/api_error.dart';
import '../../../core/time.dart';
import '../data/attendance_repository.dart';
import 'attendance_day_detail_screen.dart';
import 'attendance_summary.dart';
import '../../../core/theme/employee_theme_scope.dart';
import '../../../core/theme/employee_tokens.dart';
import '../../../core/widgets/employee/status_map.dart';
import '../../../core/widgets/ui.dart';

String _iso(DateTime d) => '${d.year.toString().padLeft(4, '0')}-${d.month.toString().padLeft(2, '0')}-${d.day.toString().padLeft(2, '0')}';

/// "This month" for the signed-in employee — mirrors the web self-view's `EmployeeMonthView`:
/// a month grid coloured by each day's attendance bucket, with previous/next month navigation.
/// Tapping a day opens its detail.
class AttendanceMonthCard extends ConsumerStatefulWidget {
  const AttendanceMonthCard({super.key, required this.employeeId, required this.zone, this.now});
  final String employeeId;
  final String zone;

  /// Overrides the clock (tests, so "today" and the opening month are fixed). Null = now.
  final DateTime? now;

  @override
  ConsumerState<AttendanceMonthCard> createState() => _AttendanceMonthCardState();
}

class _AttendanceMonthCardState extends ConsumerState<AttendanceMonthCard> {
  late DateTime _month;
  bool _loading = true;
  String? _error;
  Map<String, AttendanceDay> _byDate = const {};

  @override
  void initState() {
    super.initState();
    final today = DateTime.parse(businessToday(widget.zone, now: widget.now));
    _month = DateTime(today.year, today.month);
    _load();
  }

  Future<void> _load() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    final last = DateTime(_month.year, _month.month + 1, 0);
    try {
      final days = await ref.read(attendanceRepositoryProvider).listAttendanceDays(employeeId: widget.employeeId, dateFrom: _iso(_month), dateTo: _iso(last));
      if (mounted) setState(() => _byDate = {for (final d in days) d.attendanceDate: d});
    } catch (e) {
      if (mounted) setState(() => _error = e is ApiError ? e.message : 'Something went wrong.');
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  void _shift(int delta) {
    setState(() => _month = DateTime(_month.year, _month.month + delta));
    _load();
  }

  bool _provisional(AttendanceDay d) => d.attendanceDate == businessToday(widget.zone, now: widget.now) && isNotCheckedIn(d) && !d.isLocked;

  EmployeeStatus _statusOf(AttendanceDay d) =>
      _provisional(d) ? (kind: StatusKind.warning, label: 'Not punched in yet', glyph: glyphFor(StatusKind.warning)) : statusForAttendanceBucket(attendanceBucketOf(d));

  static const _monthNames = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'];

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final daysInMonth = DateTime(_month.year, _month.month + 1, 0).day;
    final leading = DateTime(_month.year, _month.month, 1).weekday - 1; // Monday-first
    final t = EmployeeTokens.of(context);
    final cells = <Widget>[
      for (final w in const ['Mo', 'Tu', 'We', 'Th', 'Fr', 'Sa', 'Su']) Center(child: Text(w, style: TextStyle(fontSize: 11, color: t.inkSecondary))),
      for (var i = 0; i < leading; i++) const SizedBox.shrink(),
      for (var day = 1; day <= daysInMonth; day++) _cell(context, day),
    ];
    final present = _byDate.values.where((d) => const {'PRESENT', 'REMOTE', 'ON_DUTY'}.contains(attendanceBucketOf(d))).length;
    // Today's ABSENT/INCOMPLETE row before any punch is the 09:30 sweep's placeholder, not an absence.
    final absent = _byDate.values.where((d) => attendanceBucketOf(d) == 'ABSENT' && !_provisional(d)).length;
    final leave = _byDate.values.where((d) => attendanceBucketOf(d) == 'LEAVE').length;
    return AppCard(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 12),
      child: Padding(
        padding: EdgeInsets.zero,
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Row(children: [
            IconButton(onPressed: () => _shift(-1), icon: const Icon(Icons.chevron_left)),
            Expanded(child: Text('${_monthNames[_month.month - 1]} ${_month.year}', textAlign: TextAlign.center, style: const TextStyle(fontWeight: FontWeight.w700, fontSize: 16))),
            IconButton(onPressed: () => _shift(1), icon: const Icon(Icons.chevron_right)),
          ]),
          if (_loading)
            const Padding(padding: EdgeInsets.all(24), child: Center(child: CircularProgressIndicator(strokeWidth: 2.5)))
          else if (_error != null)
            Padding(
              padding: const EdgeInsets.all(12),
              child: Column(children: [Text(_error!), TextButton(onPressed: _load, child: const Text('Retry'))]),
            )
          else ...[
            GridView(
              shrinkWrap: true,
              physics: const NeverScrollableScrollPhysics(),
              // Cells grow with the text size so the numeral and glyph never clip.
              gridDelegate: SliverGridDelegateWithFixedCrossAxisCount(crossAxisCount: 7, mainAxisExtent: 48 * MediaQuery.textScalerOf(context).scale(1).clamp(1.0, 2.0)),
              children: cells,
            ),
            const SizedBox(height: 8),
            _Legend(statuses: [for (final d in _byDate.values) _statusOf(d)]),
            const SizedBox(height: 8),
            Text('Present $present · Absent $absent · Leave $leave', style: TextStyle(fontSize: 12, color: scheme.onSurfaceVariant)),
          ],
        ]),
      ),
    );
  }

  Widget _cell(BuildContext context, int day) {
    final t = EmployeeTokens.of(context);
    final date = _iso(DateTime(_month.year, _month.month, day));
    final record = _byDate[date];
    final isToday = date == businessToday(widget.zone, now: widget.now);
    final status = record == null ? null : _statusOf(record);
    final colors = status == null ? null : statusColors(context, status.kind);
    final label = '$day ${_monthNames[_month.month - 1]}, ${status?.label ?? 'No record'}${isToday ? ', today' : ''}';
    return Semantics(
      label: label,
      button: record != null,
      excludeSemantics: true,
      // The InkWell is the whole grid cell (the 2 px gap is drawn inside it), so the touch target is
      // the full cell: 48 high, and as wide as the grid allows (about 39 px on a 320 px phone,
      // where seven columns cannot be wider without changing the layout).
      child: InkWell(
        borderRadius: BorderRadius.circular(10),
        onTap: record == null ? null : () => Navigator.of(context).push(MaterialPageRoute(builder: (_) => EmployeeThemeScope(child: AttendanceDayDetailScreen(dayId: record.id, initial: record)))),
        child: Container(
          margin: const EdgeInsets.all(2),
          decoration: BoxDecoration(
            color: colors?.fill,
            borderRadius: BorderRadius.circular(8),
            border: isToday ? Border.all(color: t.action, width: 1.5) : null,
          ),
          // Glyph + numeral: colour is never the only signal.
          child: Column(mainAxisAlignment: MainAxisAlignment.center, children: [
            Text('$day', style: TextStyle(fontSize: 12, fontWeight: record == null ? FontWeight.w400 : FontWeight.w700, color: record == null ? t.inkTertiary : colors!.text)),
            if (status != null) Icon(status.glyph, size: 10, color: colors!.glyph),
          ]),
        ),
      ),
    );
  }
}

/// Which status each glyph/colour means, for the buckets present this month only.
class _Legend extends StatelessWidget {
  const _Legend({required this.statuses});
  final List<EmployeeStatus> statuses;

  @override
  Widget build(BuildContext context) {
    final t = EmployeeTokens.of(context);
    if (statuses.isEmpty) return const SizedBox.shrink();
    final seen = <String>{};
    final items = statuses.where((s) => seen.add(s.label)).toList();
    return Wrap(spacing: 12, runSpacing: 4, children: [
      for (final s in items)
        Row(mainAxisSize: MainAxisSize.min, children: [
          Icon(s.glyph, size: 10, color: statusColors(context, s.kind).glyph),
          const SizedBox(width: 4),
          Text(s.label, style: TextStyle(fontSize: 11, color: t.inkSecondary)),
        ]),
    ]);
  }
}
