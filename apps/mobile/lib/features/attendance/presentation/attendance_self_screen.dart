import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api/api_error.dart';
import '../../../core/time.dart';
import '../../auth/state/auth_controller.dart';
import '../../shell/more_action.dart';
import '../data/attendance_repository.dart';
import 'attendance_day_detail_screen.dart';
import 'attendance_widgets.dart';
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
    // The window is the last 14 *business* days in the company's zone (TZ-06), not the device's.
    final zone = ref.read(authControllerProvider).user?.companyTimezone ?? 'Asia/Kolkata';
    try {
      final days = await ref.read(attendanceRepositoryProvider).listAttendanceDays(
            employeeId: employeeId,
            dateFrom: businessDayOffset(zone, -13),
            dateTo: businessToday(zone),
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
                AttendanceDayTile(
                  day: day,
                  onTap: () => Navigator.of(context).push(MaterialPageRoute(builder: (_) => AttendanceDayDetailScreen(dayId: day.id, initial: day))),
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
