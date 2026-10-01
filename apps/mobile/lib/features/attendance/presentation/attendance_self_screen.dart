import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api/api_error.dart';
import '../../auth/state/auth_controller.dart';
import '../../shell/more_action.dart';
import '../data/attendance_repository.dart';
import 'attendance_day_detail_screen.dart';
import 'face_punch_card.dart';
import 'holiday_calendars_screen.dart' show attendanceRepositoryProvider;

/// Mirrors the "My Attendance" portion of the Stitch Mobile Dashboard —
/// today's punch status plus the last 14 days, for the signed-in employee.
class AttendanceSelfScreen extends ConsumerStatefulWidget {
  const AttendanceSelfScreen({super.key});

  @override
  ConsumerState<AttendanceSelfScreen> createState() => _AttendanceSelfScreenState();
}

class _AttendanceSelfScreenState extends ConsumerState<AttendanceSelfScreen> {
  bool _loading = true;
  bool _punching = false;
  List<AttendanceDay> _days = const [];
  ApiError? _error;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    final employeeId = ref.read(authControllerProvider).user?.employeeId;
    if (employeeId == null) {
      setState(() => _loading = false);
      return;
    }
    setState(() {
      _loading = true;
      _error = null;
    });
    final to = DateTime.now();
    final from = to.subtract(const Duration(days: 13));
    try {
      final days = await ref.read(attendanceRepositoryProvider).listAttendanceDays(
            employeeId: employeeId,
            dateFrom: from.toIso8601String().split('T').first,
            dateTo: to.toIso8601String().split('T').first,
          );
      days.sort((a, b) => b.attendanceDate.compareTo(a.attendanceDate));
      if (mounted) setState(() => _days = days);
    } catch (error) {
      if (mounted) setState(() => _error = error is ApiError ? error : ApiError(status: 0, code: 'UNKNOWN_ERROR', message: 'Something went wrong.'));
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _punch(String direction) async {
    setState(() => _punching = true);
    try {
      await ref.read(attendanceRepositoryProvider).punchMe(direction: direction);
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(direction == 'IN' ? 'Punched in.' : 'Punched out.')));
      _load();
    } catch (error) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(error is ApiError ? error.message : 'Something went wrong.')));
      }
    } finally {
      if (mounted) setState(() => _punching = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final employeeId = ref.watch(authControllerProvider).user?.employeeId;
    final scheme = Theme.of(context).colorScheme;

    Widget body;
    if (employeeId == null) {
      body = const Center(
        child: Padding(padding: EdgeInsets.all(24), child: Text('No employee record is linked to your account.', textAlign: TextAlign.center)),
      );
    } else if (_loading) {
      body = const Center(child: CircularProgressIndicator());
    } else if (_error != null) {
      body = Center(
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: Column(mainAxisSize: MainAxisSize.min, children: [
            Text(_error!.message, textAlign: TextAlign.center),
            const SizedBox(height: 16),
            FilledButton(onPressed: _load, child: const Text('Retry')),
          ]),
        ),
      );
    } else {
      body = RefreshIndicator(
        onRefresh: _load,
        child: ListView(
          padding: const EdgeInsets.all(16),
          children: [
            FacePunchCard(onPunched: _load),
            const SizedBox(height: 16),
            Row(children: [
              Expanded(
                child: FilledButton.icon(
                  onPressed: _punching ? null : () => _punch('IN'),
                  icon: const Icon(Icons.login),
                  label: const Text('Punch in'),
                ),
              ),
              const SizedBox(width: 12),
              Expanded(
                child: OutlinedButton.icon(
                  onPressed: _punching ? null : () => _punch('OUT'),
                  icon: const Icon(Icons.logout),
                  label: const Text('Punch out'),
                ),
              ),
            ]),
            const SizedBox(height: 24),
            Text('Last 14 days', style: Theme.of(context).textTheme.labelMedium),
            const SizedBox(height: 8),
            if (_days.isEmpty)
              const Padding(padding: EdgeInsets.symmetric(vertical: 24), child: Text('No attendance records yet.'))
            else
              for (final day in _days)
                InkWell(
                  onTap: () => Navigator.of(context).push(MaterialPageRoute(builder: (_) => AttendanceDayDetailScreen(day: day))),
                  child: Container(
                    margin: const EdgeInsets.only(bottom: 8),
                    padding: const EdgeInsets.all(12),
                    decoration: BoxDecoration(color: scheme.surfaceContainerLowest, borderRadius: BorderRadius.circular(10), border: Border.all(color: scheme.outlineVariant)),
                    child: Row(
                      mainAxisAlignment: MainAxisAlignment.spaceBetween,
                      children: [
                        Text(day.attendanceDate),
                        _StatusBadge(status: day.attendanceStatus),
                      ],
                    ),
                  ),
                ),
          ],
        ),
      );
    }

    return Scaffold(
      appBar: AppBar(title: const Text('Attendance'), automaticallyImplyLeading: false, actions: const [MoreAction()]),
      body: body,
    );
  }
}

/// Defensive enum-mapping (the backend's `attendance_status` set isn't
/// frozen client-side) — mirrors the web app's `AttendanceStatusBadge`.
class _StatusBadge extends StatelessWidget {
  const _StatusBadge({required this.status});
  final String status;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    Color color;
    switch (status) {
      case 'PRESENT':
        color = Colors.green;
      case 'HALF_DAY':
      case 'INCOMPLETE':
        color = Colors.amber;
      case 'ABSENT':
      case 'CONFIG_ERROR':
        color = Colors.red;
      case 'ON_DUTY':
      case 'WFH':
        color = Colors.blue;
      case 'LEAVE':
        color = Colors.purple;
      default:
        color = scheme.onSurfaceVariant;
    }
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
      decoration: BoxDecoration(color: color.withValues(alpha: 0.15), borderRadius: BorderRadius.circular(4)),
      child: Text(status.replaceAll('_', ' '), style: TextStyle(color: color, fontSize: 11, fontWeight: FontWeight.w600)),
    );
  }
}
