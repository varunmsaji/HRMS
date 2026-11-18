import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api/api_error.dart';
import '../../../core/forms/choice_sources.dart';
import '../../../core/forms/form_spec.dart' show Choice;
import '../../../core/providers.dart';
import '../../../core/widgets/ui.dart';
import '../data/attendance_repository.dart';
import '../domain/attendance_insights.dart' show shortDate;
import '../domain/attendance_mismatch.dart';
import 'attendance_day_detail_screen.dart';
import 'attendance_widgets.dart';
import 'mismatch_fixes.dart';
import 'team_attendance_screen.dart' show openPunchOnBehalf;

/// Every day in [from]..[to] that does not add up (missing punch, nothing punched, work on
/// approved leave, config error, waiting on approval), each with its one-line reason and the fix
/// to use. Opened from Insights → Needs attention; the web list's "View all" drill-down.
class AttendanceMismatchesScreen extends ConsumerStatefulWidget {
  const AttendanceMismatchesScreen({super.key, required this.from, required this.to});
  final String from;
  final String to;

  @override
  ConsumerState<AttendanceMismatchesScreen> createState() => _AttendanceMismatchesScreenState();
}

class _AttendanceMismatchesScreenState extends ConsumerState<AttendanceMismatchesScreen> {
  bool _loading = true;
  String? _error;
  List<AttendanceDay> _days = const [];
  Map<String, String> _names = const {};
  Map<String, String> _pending = const {};

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final daysFuture = ref.read(attendanceRepositoryProvider).listAttendanceDays(dateFrom: widget.from, dateTo: widget.to);
      final namesFuture = loadChoices(ref.read(apiClientProvider), const [
        'employees',
      ]).then((c) => {for (final e in c['employees'] ?? const <Choice>[]) e.value: e.label}).catchError((_) => <String, String>{});
      final pendingFuture = loadPendingCorrections(ref);
      final days = await daysFuture;
      final names = await namesFuture;
      final pending = await pendingFuture;
      if (!mounted) return;
      setState(() {
        _days = days;
        _names = names;
        _pending = pending;
      });
    } catch (e) {
      if (mounted) setState(() => _error = e is ApiError ? e.message : 'Something went wrong.');
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  String _name(String employeeId) => _names[employeeId] ?? 'Employee';

  @override
  Widget build(BuildContext context) {
    final fixer = MismatchFixer(
      context: context,
      ref: ref,
      nameOf: _name,
      pending: _pending,
      openPunch: ({required employeeId, required direction, required time}) => openPunchOnBehalf(context, ref, employeeId: employeeId, direction: direction, punchTime: time),
      openDay: (d) => Navigator.of(context).push(MaterialPageRoute(builder: (_) => AttendanceDayDetailScreen(dayId: d.id, initial: d))),
      onChanged: _load,
    );
    // Newest day first, then by name, so today's problems are on top.
    final rows = [
      for (final d in _days)
        if (mismatchOf(d) != null) d,
    ]..sort((a, b) {
      final byDate = b.attendanceDate.compareTo(a.attendanceDate);
      return byDate != 0 ? byDate : _name(a.employeeId).compareTo(_name(b.employeeId));
    });
    final range = widget.from == widget.to ? shortDate(widget.to) : '${shortDate(widget.from)} – ${shortDate(widget.to)}';
    return Scaffold(
      appBar: AppBar(title: const Text('Days that need fixing')),
      body:
          _loading
              ? const ListSkeleton()
              : _error != null
              ? StateMessage(icon: Icons.error_outline_rounded, tone: Tone.danger, title: "Couldn't load attendance", message: _error!, actionLabel: 'Try again', onAction: _load)
              : RefreshIndicator(
                onRefresh: _load,
                child: ListView(
                  padding: const EdgeInsets.all(16),
                  children: [
                    Padding(
                      padding: const EdgeInsets.only(bottom: 10),
                      child: Text(rows.isEmpty ? range : '$range · ${rows.length} ${rows.length == 1 ? 'day' : 'days'}', style: Theme.of(context).textTheme.bodySmall),
                    ),
                    if (rows.isEmpty)
                      const SizedBox(height: 300, child: StateMessage(icon: Icons.check_circle_outline_rounded, title: 'Nothing needs fixing', message: 'Every day in this range adds up.'))
                    else
                      for (final d in rows)
                        AttendanceDayTile(
                          day: d,
                          employeeLabel: _name(d.employeeId),
                          mismatch: fixer.forDay(d),
                          onTap: () => Navigator.of(context).push(MaterialPageRoute(builder: (_) => AttendanceDayDetailScreen(dayId: d.id, initial: d))),
                        ),
                  ],
                ),
              ),
    );
  }
}
