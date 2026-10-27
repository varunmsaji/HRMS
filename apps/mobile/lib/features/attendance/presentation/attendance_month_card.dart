import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api/api_error.dart';
import '../../../core/time.dart';
import '../data/attendance_repository.dart';
import 'attendance_day_detail_screen.dart';
import 'attendance_summary.dart';
import '../../../core/widgets/ui.dart';

Color _bucketColor(String bucket) => switch (bucket) {
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

String _iso(DateTime d) => '${d.year.toString().padLeft(4, '0')}-${d.month.toString().padLeft(2, '0')}-${d.day.toString().padLeft(2, '0')}';

/// "This month" for the signed-in employee — mirrors the web self-view's `EmployeeMonthView`:
/// a month grid coloured by each day's attendance bucket, with previous/next month navigation.
/// Tapping a day opens its detail.
class AttendanceMonthCard extends ConsumerStatefulWidget {
  const AttendanceMonthCard({super.key, required this.employeeId, required this.zone});
  final String employeeId;
  final String zone;

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
    final today = DateTime.parse(businessToday(widget.zone));
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

  static const _monthNames = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'];

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final daysInMonth = DateTime(_month.year, _month.month + 1, 0).day;
    final leading = DateTime(_month.year, _month.month, 1).weekday - 1; // Monday-first
    final cells = <Widget>[
      for (final w in const ['M', 'T', 'W', 'T', 'F', 'S', 'S']) Center(child: Text(w, style: TextStyle(fontSize: 11, color: scheme.onSurfaceVariant))),
      for (var i = 0; i < leading; i++) const SizedBox.shrink(),
      for (var day = 1; day <= daysInMonth; day++) _cell(context, day),
    ];
    final present = _byDate.values.where((d) => const {'PRESENT', 'REMOTE', 'ON_DUTY'}.contains(attendanceBucketOf(d))).length;
    final absent = _byDate.values.where((d) => attendanceBucketOf(d) == 'ABSENT').length;
    final leave = _byDate.values.where((d) => attendanceBucketOf(d) == 'LEAVE').length;
    return AppCard(
      padding: const EdgeInsets.all(12),
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
            GridView.count(crossAxisCount: 7, shrinkWrap: true, physics: const NeverScrollableScrollPhysics(), childAspectRatio: 1.1, children: cells),
            const SizedBox(height: 8),
            Text('Present $present · Absent $absent · Leave $leave', style: TextStyle(fontSize: 12, color: scheme.onSurfaceVariant)),
          ],
        ]),
      ),
    );
  }

  Widget _cell(BuildContext context, int day) {
    final date = _iso(DateTime(_month.year, _month.month, day));
    final record = _byDate[date];
    final color = record == null ? null : _bucketColor(attendanceBucketOf(record));
    return InkWell(
      onTap: record == null ? null : () => Navigator.of(context).push(MaterialPageRoute(builder: (_) => AttendanceDayDetailScreen(dayId: record.id, initial: record))),
      child: Container(
        margin: const EdgeInsets.all(2),
        decoration: BoxDecoration(
          color: color?.withValues(alpha: 0.22),
          borderRadius: BorderRadius.circular(10),
          border: record == null ? null : Border.all(color: color!.withValues(alpha: 0.5)),
        ),
        child: Center(child: Text('$day', style: TextStyle(fontSize: 12, fontWeight: record == null ? FontWeight.w400 : FontWeight.w700))),
      ),
    );
  }
}
