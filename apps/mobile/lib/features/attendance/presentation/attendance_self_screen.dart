import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/widgets/ui.dart';

import '../../../core/api/api_client.dart';
import '../../../core/api/api_error.dart';
import '../../../core/time.dart';
import '../../auth/state/auth_controller.dart';
import '../../shell/more_action.dart';
import '../data/attendance_repository.dart';
import 'attendance_day_detail_screen.dart';
import 'attendance_month_card.dart';
import 'attendance_widgets.dart';
import 'face_punch_card.dart';

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

  /// True once the server says this employee must punch with their face (enrolled). The plain
  /// buttons are then not offered at all; the server refuses them regardless (403).
  bool _faceRequired = false;
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

  /// The idempotency key of a punch whose outcome is unknown (no response). A retry of the
  /// *same* direction reuses it, so a punch that did reach the server is not recorded twice.
  ({String direction, String key})? _unconfirmedPunch;

  Future<void> _punch(String direction) async {
    setState(() => _punching = true);
    final pending = _unconfirmedPunch;
    final key =
        pending != null && pending.direction == direction
            ? pending.key
            : ApiClient.newIdempotencyKey();
    try {
      await ref.read(attendanceRepositoryProvider).punchMe(direction: direction, idempotencyKey: key);
      _unconfirmedPunch = null;
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(direction == 'IN' ? 'Punched in.' : 'Punched out.')));
      _load();
    } catch (error) {
      if (error is ApiError && error.code == 'FACE_VERIFICATION_REQUIRED' && mounted) {
        setState(() => _faceRequired = true);
      }
      // No response: keep the key for a retry. Any real answer settles this attempt.
      _unconfirmedPunch =
          error is ApiError && error.status == 0
              ? (direction: direction, key: key)
              : null;
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(describeApiError(error))));
      }
    } finally {
      if (mounted) setState(() => _punching = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final employeeId = ref.watch(authControllerProvider).user?.employeeId;

    // The punch controls and the month card load on their own and never wait for the 14-day
    // list: punching is the reason to open this tab, the history is secondary.
    Widget history;
    if (_loading && _days.isEmpty) {
      history = const Padding(padding: EdgeInsets.symmetric(vertical: 32), child: Center(child: CircularProgressIndicator()));
    } else if (_error != null && _days.isEmpty) {
      history = StateMessage(icon: Icons.cloud_off_rounded, tone: Tone.danger, title: 'Couldn\'t load attendance', message: _error!.message, actionLabel: 'Try again', onAction: _load);
    } else if (_days.isEmpty) {
      history = const Padding(padding: EdgeInsets.symmetric(vertical: 24), child: StateMessage(icon: Icons.event_busy_outlined, title: 'No attendance yet', message: 'Your punches will show up here.'));
    } else {
      history = Column(children: [
        for (final day in _days)
          AttendanceDayTile(
            day: day,
            onTap: () => Navigator.of(context).push(MaterialPageRoute(builder: (_) => AttendanceDayDetailScreen(dayId: day.id, initial: day))),
          ),
      ]);
    }

    final Widget body;
    if (employeeId == null) {
      body = const StateMessage(
        icon: Icons.person_off_outlined,
        tone: Tone.warning,
        title: 'No employee record',
        message: 'No employee record is linked to your account.',
      );
    } else {
      body = RefreshIndicator(
        onRefresh: _load,
        child: ListView(
          padding: const EdgeInsets.all(16),
          children: [
            FacePunchCard(
              onPunched: _load,
              onStatus: (status) {
                if (status.faceVerificationRequired != _faceRequired) {
                  setState(() => _faceRequired = status.faceVerificationRequired);
                }
              },
            ),
            if (!_faceRequired) ...[
            const SizedBox(height: 16),
            Row(children: [
              Expanded(
                child: FilledButton.icon(
                  onPressed: _punching ? null : () => _punch('IN'),
                  icon: const Icon(Icons.login_rounded),
                  label: const Text('Punch in'),
                ),
              ),
              const SizedBox(width: 12),
              Expanded(
                child: OutlinedButton.icon(
                  onPressed: _punching ? null : () => _punch('OUT'),
                  icon: const Icon(Icons.logout_rounded),
                  label: const Text('Punch out'),
                ),
              ),
            ]),
            ],
            const SizedBox(height: 24),
            const SectionHeader('This month'),
            AttendanceMonthCard(employeeId: employeeId, zone: ref.read(authControllerProvider).user?.companyTimezone ?? 'Asia/Kolkata'),
            const SizedBox(height: 24),
            const SectionHeader('Last 14 days'),
            history,
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
