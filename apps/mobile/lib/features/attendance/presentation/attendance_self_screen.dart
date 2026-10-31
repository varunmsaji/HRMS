import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/theme/employee_theme_scope.dart';
import '../../../core/widgets/employee/attendance_history.dart';
import '../../../core/widgets/employee/check_in_action.dart';
import '../../../core/widgets/employee/interaction.dart';
import '../../../core/widgets/employee/today_status_panel.dart';
import '../../../core/widgets/ui.dart';

import '../../../core/api/api_error.dart';
import '../../../core/time.dart';
import '../../../core/auth/surface.dart';
import '../../auth/state/auth_controller.dart';
import '../../shell/more_action.dart';
import '../data/attendance_repository.dart';
import 'attendance_day_detail_screen.dart';
import 'attendance_month_card.dart';
import 'face_punch_card.dart';
import '../state/punch_controller.dart';
import 'context_punch_ui.dart';
import '../state/today_provider.dart';

/// Mirrors the "My Attendance" portion of the Stitch Mobile Dashboard —
/// today's punch status plus the last 14 days, for the signed-in employee.
class AttendanceSelfScreen extends ConsumerStatefulWidget {
  const AttendanceSelfScreen({super.key});

  @override
  ConsumerState<AttendanceSelfScreen> createState() => _AttendanceSelfScreenState();
}

class _AttendanceSelfScreenState extends ConsumerState<AttendanceSelfScreen> {
  bool _loading = true;
  List<AttendanceDay> _days = const [];
  ApiError? _error;

  /// False until the face status read has finished (worked or not): the sticky control must not
  /// offer a plain punch and then have it refused for an enrolled employee.
  bool _faceKnown = false;

  /// Bumped to make the face card re-read its status (after a `FACE_NOT_ENROLLED` answer).
  int _faceReload = 0;

  final _barKey = GlobalKey();

  /// The bar plus its 16 px padding above and below.
  double _barHeight() => (_barKey.currentContext?.size?.height ?? 0) + 32;

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

  /// Punching (plain) lives in [PunchController], shared with Home; this only supplies the dialogs.
  void _punch(String direction) {
    final employeeId = ref.read(authControllerProvider).user?.employeeId;
    final zone = ref.read(authControllerProvider).user?.companyTimezone ?? 'Asia/Kolkata';
    void refresh() {
      _load();
      if (employeeId != null) ref.invalidate(todayDataProvider((employeeId: employeeId, zone: zone)));
    }

    final controller = ref.read(punchControllerProvider.notifier);
    if (ref.read(punchControllerProvider).faceRequired) {
      controller.punchFace(direction, ContextPunchUi(context, ref, onPunchedCallback: refresh, onFaceNotEnrolledCallback: () => setState(() => _faceReload++), snackBarClearance: _barHeight));
    } else {
      controller.punchPlain(direction, ContextPunchUi(context, ref, onPunchedCallback: refresh, snackBarClearance: _barHeight));
    }
  }

  @override
  Widget build(BuildContext context) {
    final employeeId = ref.watch(authControllerProvider).user?.employeeId;
    final punch = ref.watch(punchControllerProvider);
    // True once the server says this employee must punch with their face (enrolled): the plain
    // buttons are then not offered at all; the server refuses them regardless (403).
    final faceRequired = punch.faceRequired;

    // The punch controls and the month card load on their own and never wait for the 14-day
    // list: punching is the reason to open this tab, the history is secondary.
    Widget history;
    if (_loading && _days.isEmpty) {
      history = const AttendanceHistorySkeleton();
    } else if (_error != null && _days.isEmpty) {
      history = StateMessage(icon: Icons.cloud_off_rounded, tone: Tone.danger, title: 'Couldn\'t load attendance', message: _error!.message, actionLabel: 'Try again', onAction: _load);
    } else if (_days.isEmpty) {
      history = const Padding(padding: EdgeInsets.symmetric(vertical: 24), child: StateMessage(icon: Icons.event_busy_outlined, title: 'No attendance yet', message: 'Your punches will show up here.'));
    } else {
      history = AttendanceHistoryGroup(
        days: _days,
        today: businessToday(ref.read(authControllerProvider).user?.companyTimezone ?? 'Asia/Kolkata'),
        onTap: (day) => Navigator.of(context).push(MaterialPageRoute(builder: (_) => EmployeeThemeScope(child: AttendanceDayDetailScreen(dayId: day.id, initial: day)))),
      );
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
      final zone = ref.read(authControllerProvider).user?.companyTimezone ?? 'Asia/Kolkata';
      final key = (employeeId: employeeId, zone: zone);
      final today = ref.watch(todayDataProvider(key));
      final state = todayStateOf(today, key);
      body = WithStickyBar(
        body: RefreshIndicator(
          onRefresh: () async {
            ref.invalidate(todayDataProvider(key));
            await _load();
          },
          child: ListView(
            padding: const EdgeInsets.all(16),
            children: [
              TodayStatusPanel(
                state: state,
                zone: zone,
                scheduleText: scheduleCaption(today.valueOrNull?.todayRow, zone),
                onRetry: () => ref.invalidate(todayDataProvider(key)),
              ),
              const SizedBox(height: 16),
              FacePunchCard(
                key: ValueKey(_faceReload),
                onPunched: _load,
                showButtons: false,
                onResolved: () {
                  if (mounted && !_faceKnown) setState(() => _faceKnown = true);
                },
              ),
              const SizedBox(height: 24),
              const SectionHeader('This month'),
              AttendanceMonthCard(employeeId: employeeId, zone: zone),
              const SizedBox(height: 24),
              const SectionHeader('Last 14 days'),
              history,
            ],
          ),
        ),
        bar: KeyedSubtree(key: _barKey, child: CheckInAction(
          likely: state.likely,
          faceRequired: faceRequired,
          busy: punch.plainBusy || punch.faceBusy,
          ready: _faceKnown,
          busyLabel: punch.faceBusy ? 'Verifying…' : 'Recording punch…',
          onPunch: _punch,
        )),
      );
    }

    return Scaffold(
      appBar: AppBar(title: const Text('Attendance'), automaticallyImplyLeading: false, actions: usesEmployeeSurface(ref.watch(authControllerProvider).user) ? null : const [MoreAction()]),
      body: body,
    );
  }
}
