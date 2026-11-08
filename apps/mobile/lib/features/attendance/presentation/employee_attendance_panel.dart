import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api/api_error.dart';
import '../../../core/auth/permissions.dart';
import '../../../core/time.dart';
import '../../auth/state/auth_controller.dart';
import '../data/attendance_repository.dart';
import '../domain/employee_attendance_summary.dart';
import 'attendance_day_detail_screen.dart';
import 'attendance_widgets.dart';
import 'face_enrollment_admin_card.dart';
import 'team_attendance_screen.dart' show openPunchOnBehalf;

/// The Attendance tab of an employee record — mirrors
/// `apps/web/src/components/attendance/employee-attendance-panel.tsx`: one employee's attendance
/// days over a date range (quick ranges, a range summary, then the days), with "Calculate today"
/// and "Record punch" for HR.
class EmployeeAttendancePanel extends ConsumerStatefulWidget {
  const EmployeeAttendancePanel({super.key, required this.employeeId, this.employeeLabel = 'this employee'});
  final String employeeId;
  final String employeeLabel;

  @override
  ConsumerState<EmployeeAttendancePanel> createState() => _EmployeeAttendancePanelState();
}

class _EmployeeAttendancePanelState extends ConsumerState<EmployeeAttendancePanel> {
  late String _from;
  late String _to;
  bool _loading = true;
  bool _busy = false;
  ApiError? _error;
  List<AttendanceDay> _days = const [];

  String get _zone => ref.read(authControllerProvider).user?.companyTimezone ?? 'Asia/Kolkata';

  @override
  void initState() {
    super.initState();
    final first = attendanceRangePresets(businessToday(_zone)).first;
    _from = first.from;
    _to = first.to;
    _load();
  }

  Future<void> _load() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final days = await ref.read(attendanceRepositoryProvider).listAttendanceDays(employeeId: widget.employeeId, dateFrom: _from, dateTo: _to);
      days.sort((a, b) => b.attendanceDate.compareTo(a.attendanceDate));
      if (mounted) setState(() => _days = days);
    } catch (e) {
      if (mounted) setState(() => _error = e is ApiError ? e : ApiError(status: 0, code: 'UNKNOWN_ERROR', message: 'Something went wrong.'));
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _pick(bool from) async {
    final current = DateTime.tryParse(from ? _from : _to) ?? DateTime.now();
    final picked = await showDatePicker(context: context, initialDate: current, firstDate: DateTime(2020), lastDate: DateTime(2100));
    if (picked == null) return;
    final iso = '${picked.year.toString().padLeft(4, '0')}-${picked.month.toString().padLeft(2, '0')}-${picked.day.toString().padLeft(2, '0')}';
    setState(() => from ? _from = iso : _to = iso);
    _load();
  }

  void _applyPreset(RangePreset p) {
    setState(() {
      _from = p.from;
      _to = p.to;
    });
    _load();
  }

  Future<void> _calculateToday() async {
    setState(() => _busy = true);
    try {
      await ref.read(attendanceRepositoryProvider).calculateToday(widget.employeeId);
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text("Today's attendance calculated.")));
      await _load();
    } catch (e) {
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(e is ApiError ? e.message : 'Something went wrong.')));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final permissions = ref.watch(authControllerProvider).user?.permissions ?? const <String>[];
    final scheme = Theme.of(context).colorScheme;
    return RefreshIndicator(
      onRefresh: _load,
      child: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          if (permissions.contains(attendanceFaceEnrollmentManage)) FaceEnrollmentAdminCard(employeeId: widget.employeeId, employeeLabel: widget.employeeLabel),
          Wrap(spacing: 8, runSpacing: 8, children: [
            for (final p in attendanceRangePresets(businessToday(_zone)))
              ChoiceChip(label: Text(p.label), selected: _from == p.from && _to == p.to, onSelected: (_) => _applyPreset(p)),
          ]),
          const SizedBox(height: 8),
          Row(children: [
            Expanded(child: OutlinedButton(onPressed: () => _pick(true), child: Text('From $_from'))),
            const SizedBox(width: 8),
            Expanded(child: OutlinedButton(onPressed: () => _pick(false), child: Text('To $_to'))),
          ]),
          const SizedBox(height: 8),
          Wrap(spacing: 8, runSpacing: 8, children: [
            if (permissions.contains(attendanceViewAll)) OutlinedButton(onPressed: _busy ? null : _calculateToday, child: const Text('Calculate today')),
            if (permissions.contains(attendancePunchOnBehalf))
              OutlinedButton(
                onPressed: () async {
                  if (await openPunchOnBehalf(context, ref, employeeId: widget.employeeId) && mounted) _load();
                },
                child: const Text('Record punch'),
              ),
          ]),
          const SizedBox(height: 12),
          if (_loading)
            const Padding(padding: EdgeInsets.all(32), child: Center(child: CircularProgressIndicator()))
          else if (_error != null)
            Column(children: [
              Text(_error!.status == 403 ? "You do not have permission to view this employee's attendance." : _error!.message, textAlign: TextAlign.center),
              const SizedBox(height: 12),
              FilledButton(onPressed: _load, child: const Text('Retry')),
            ])
          else if (_days.isEmpty)
            Padding(padding: const EdgeInsets.all(32), child: Text('No attendance days in this range.', textAlign: TextAlign.center, style: TextStyle(color: scheme.onSurfaceVariant)))
          else ...[
            _RangeSummary(days: _days),
            const SizedBox(height: 12),
            for (final d in _days)
              AttendanceDayTile(day: d, onTap: () => Navigator.of(context).push(MaterialPageRoute(builder: (_) => AttendanceDayDetailScreen(dayId: d.id, initial: d)))),
          ],
        ],
      ),
    );
  }
}

/// Web `RangeSummary` in `employee-attendance-panel.tsx`.
class _RangeSummary extends StatelessWidget {
  const _RangeSummary({required this.days});
  final List<AttendanceDay> days;

  @override
  Widget build(BuildContext context) {
    final m = AttendanceRangeSummary.compute(days);
    return Semantics(
      label: 'Range summary',
      container: true,
      child: StatTiles(stats: [
        ('Present', '${m.present}'),
        ('Absent', '${m.count('ABSENT')}'),
        ('On leave', '${m.count('LEAVE')}'),
        ('Late', '${m.late}'),
        ('Missing punch', '${m.missingPunch}'),
        ('Worked', formatMinutes(m.workedMinutes)),
      ]),
    );
  }
}

/// Label-over-figure tiles that wrap to the screen width (the web `<dl>` stat grids).
class StatTiles extends StatelessWidget {
  const StatTiles({super.key, required this.stats});
  final List<(String, String)> stats;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    return LayoutBuilder(builder: (context, c) {
      final width = (c.maxWidth - 16) / 3;
      return Wrap(spacing: 8, runSpacing: 8, children: [
        for (final (label, value) in stats)
          Container(
            width: width < 96 ? (c.maxWidth - 8) / 2 : width,
            padding: const EdgeInsets.all(10),
            decoration: BoxDecoration(color: scheme.surfaceContainerLow, borderRadius: BorderRadius.circular(12)),
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text(label, style: TextStyle(fontSize: 11, color: scheme.onSurfaceVariant)),
              const SizedBox(height: 2),
              Text(value, style: const TextStyle(fontSize: 17, fontWeight: FontWeight.w700)),
            ]),
          ),
      ]);
    });
  }
}
