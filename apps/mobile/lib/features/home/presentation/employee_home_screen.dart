import 'package:flutter/material.dart';
import 'package:flutter/services.dart' show SystemUiOverlayStyle;
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../core/api/api_error.dart';
import '../../../core/auth/permissions.dart';
import '../../../core/theme/employee_tokens.dart';
import '../../../core/theme/employee_theme_scope.dart';
import '../../../core/format.dart';
import '../../../core/time.dart';
import '../../../core/widgets/employee/check_in_action.dart';
import '../../../core/widgets/employee/layout.dart';
import '../../../core/widgets/employee/leave_balance_strip.dart';
import '../../../core/widgets/employee/request_row.dart';
import '../../../core/widgets/employee/status_map.dart';
import '../../../core/widgets/employee/today_status_panel.dart';
import '../../attendance/data/attendance_repository.dart';
import '../../attendance/presentation/context_punch_ui.dart';
import '../../attendance/state/punch_controller.dart';
import '../../attendance/state/today_provider.dart';
import '../../auth/state/auth_controller.dart';
import '../../leave/data/leave_repository.dart';
import '../../leave/presentation/leave_application_detail_screen.dart';
import '../../payroll/data/payroll_repository.dart' show PayslipSummary;
import '../../payroll/presentation/payslip_screen.dart';
import '../../payroll/presentation/pay_runs_screen.dart' show payrollRepositoryProvider;
import '../state/home_providers.dart';
import 'home_sections.dart';

/// Brand palette (Krewoxa brand concept): Deep Blue, a lighter blue for the gradient.
const _brandDeepBlue = Color(0xFF0B3D91);
const _brandBlue = Color(0xFF1668E3);

/// The employee's face-enrollment status, read once for Home so the punch control knows whether
/// to offer a plain or a face punch before it offers anything (spec S10: disabled until known).
final homeFaceStatusProvider = FutureProvider.autoDispose.family<FaceEnrollmentStatus, String>((ref, employeeId) async {
  final status = await ref.watch(attendanceRepositoryProvider).getMyFaceEnrollment();
  ref.read(punchControllerProvider.notifier).setFaceRequired(status.faceVerificationRequired);
  return status;
});

/// Employee Home (spec S10, T1-09): today's attendance, the punch control, leave balances,
/// requests that need attention, and recent days. Everything shown is read from the existing
/// APIs and decided by the existing today-state resolver; punching goes through the same
/// [PunchController] as the Attendance tab. Nothing here calculates attendance, and nothing is
/// described as done until the server has answered.
class EmployeeHomeScreen extends ConsumerStatefulWidget {
  const EmployeeHomeScreen({super.key});

  @override
  ConsumerState<EmployeeHomeScreen> createState() => _EmployeeHomeScreenState();
}

class _EmployeeHomeScreenState extends ConsumerState<EmployeeHomeScreen> {
  /// Decision banners the employee has closed this session.
  final _dismissedBanners = <String>{};

  void _refreshAll(String employeeId, TodayKey key) {
    ref.invalidate(todayDataProvider(key));
    ref.invalidate(homeEmployeeProvider(employeeId));
    ref.invalidate(homeBalancesProvider(employeeId));
    ref.invalidate(homeLeaveCreditsProvider(employeeId));
    ref.invalidate(homeLeaveProvider(employeeId));
    ref.invalidate(homeSubmittedCorrectionsProvider(employeeId));
    ref.invalidate(homeFaceStatusProvider(employeeId));
    ref.invalidate(homeLatestPayslipProvider(employeeId));
    ref.invalidate(homeWorkProfileProvider(employeeId));
  }

  void _punch(String direction, TodayKey key) {
    final ui = ContextPunchUi(context, ref, onPunchedCallback: () => ref.invalidate(todayDataProvider(key)), onFaceNotEnrolledCallback: () => ref.invalidate(homeFaceStatusProvider(key.employeeId)));
    final controller = ref.read(punchControllerProvider.notifier);
    if (ref.read(punchControllerProvider).faceRequired) {
      controller.punchFace(direction, ui);
    } else {
      controller.punchPlain(direction, ui);
    }
  }

  @override
  Widget build(BuildContext context) {
    final user = ref.watch(authControllerProvider).user;
    final employeeId = user?.employeeId;
    final permissions = user?.permissions ?? const <String>[];
    final zone = user?.companyTimezone ?? 'Asia/Kolkata';

    final theme = Theme.of(context);
    const onBrand = Colors.white;
    final textScale = MediaQuery.textScalerOf(context).scale(16) / 16;
    final appBar = AppBar(
      toolbarHeight: 64 * textScale.clamp(1.0, 1.6),
      centerTitle: false,
      automaticallyImplyLeading: false,
      backgroundColor: Colors.transparent,
      foregroundColor: onBrand,
      systemOverlayStyle: SystemUiOverlayStyle.light,
      // `SizedBox.expand`: a bare DecoratedBox collapses to zero size here and the gradient never paints.
      flexibleSpace: const SizedBox.expand(
        child: DecoratedBox(
          decoration: BoxDecoration(
            gradient: LinearGradient(begin: Alignment.topLeft, end: Alignment.bottomRight, colors: [_brandDeepBlue, _brandBlue]),
            borderRadius: BorderRadius.vertical(bottom: Radius.circular(24)),
          ),
        ),
      ),
      // The KX monogram on a white tile, as in the brand concept's app icon.
      title: Align(
        alignment: Alignment.centerLeft,
        child: Container(
          width: 44,
          height: 44,
          padding: const EdgeInsets.all(9),
          decoration: BoxDecoration(color: Colors.white, borderRadius: BorderRadius.circular(12)),
          child: const Image(image: AssetImage('assets/brand/krewoxa-mark.png'), semanticLabel: 'Krewoxa'),
        ),
      ),
      actions: [
        IconButton(
          tooltip: 'More',
          onPressed: () => context.push('/app/more'),
          icon: CircleAvatar(radius: 16, backgroundColor: onBrand.withValues(alpha: 0.18), child: const Icon(Icons.person_outline, size: 18, color: onBrand)),
        ),
        const SizedBox(width: 4),
      ],
      bottom: PreferredSize(
        preferredSize: Size.fromHeight(60 * textScale.clamp(1.0, 2.4)),
        child: Align(
          alignment: Alignment.centerLeft,
          child: Padding(
            padding: const EdgeInsets.fromLTRB(16, 0, 16, 14),
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, mainAxisSize: MainAxisSize.min, children: [
              Text('Home', style: theme.textTheme.headlineSmall?.copyWith(color: onBrand, fontWeight: FontWeight.w700)),
              Text(_longDate(zone), style: theme.textTheme.bodySmall?.copyWith(color: onBrand.withValues(alpha: 0.85))),
            ]),
          ),
        ),
      ),
    );

    if (employeeId == null) {
      return Scaffold(
        appBar: appBar,
        body: const Center(child: EmployeeEmptyState(icon: Icons.person_off_outlined, title: 'No employee record', message: 'No employee record is linked to your account.')),
      );
    }

    final key = (employeeId: employeeId, zone: zone);
    final t = EmployeeTokens.of(context);
    final canViewAttendance = permissions.contains(attendanceView);
    final canPunch = permissions.contains(attendancePunch);
    final canSeeLeave = permissions.contains(leaveBalanceView);
    final canSeeName = permissions.contains(employeeView);
    final canSeePayslip = permissions.contains(payrollPayslipViewOwn);

    final children = <Widget>[];

    // H-01 identity: the date always; the name only when it actually loaded.
    final name = canSeeName ? ref.watch(homeEmployeeProvider(employeeId)).valueOrNull?.firstName : null;
    final code = canSeeName ? ref.watch(homeEmployeeProvider(employeeId)).valueOrNull?.employeeCode : null;
    if (name != null) children.add(_Identity(name: name, code: code));

    // A leave decision made in the last 48 hours, until dismissed.
    final decided = canSeeLeave ? _recentDecision(ref.watch(homeLeaveProvider(employeeId)).valueOrNull ?? const []) : null;
    if (decided != null && !_dismissedBanners.contains(decided.id)) {
      children.add(DecisionBanner(application: decided, onView: () => _openLeave(decided), onDismiss: () => setState(() => _dismissedBanners.add(decided.id))));
    }

    // H-02 today panel and H-03/H-04 punch control.
    if (canViewAttendance) {
      final today = ref.watch(todayDataProvider(key));
      final state = todayStateOf(today, key);
      children
        ..add(const SizedBox(height: 16))
        ..add(Padding(
          padding: const EdgeInsets.symmetric(horizontal: 16),
          child: TodayStatusPanel(
            state: state,
            zone: zone,
            scheduleText: scheduleCaption(today.valueOrNull?.todayRow, zone, compact: true),
            hero: true,
            onRetry: () => ref.invalidate(todayDataProvider(key)),
          ),
        ));
      if (canPunch) {
        final face = ref.watch(homeFaceStatusProvider(employeeId));
        final punch = ref.watch(punchControllerProvider);
        // "Known" also covers a failed status read: the plain punch is then offered and the
        // server, which enforces face-only punching, answers 403 FACE_VERIFICATION_REQUIRED if
        // it must (the controller then switches to the face flow). Only "still loading" waits.
        final known = !face.isLoading || face.hasValue;
        children
          ..add(const SizedBox(height: 12))
          ..add(Padding(
            padding: const EdgeInsets.symmetric(horizontal: 16),
            child: CheckInAction(
              likely: state.likely,
              faceRequired: punch.faceRequired,
              busy: punch.plainBusy || punch.faceBusy,
              ready: known,
              showIcons: false,
              busyLabel: punch.faceBusy ? 'Verifying…' : 'Recording punch…',
              onPunch: (d) => _punch(d, key),
            ),
          ));
      }
    }

    // Current shift and work location: omitted until known (a failed read just leaves them out).
    if (canViewAttendance) {
      final profile = ref.watch(homeWorkProfileProvider(employeeId)).valueOrNull;
      if (profile != null) children.add(WorkProfileCards(profile: profile));
    }

    // Shortcuts, only to what this user may do.
    final actions = <QuickAction>[
      if (permissions.contains(leaveApplicationSubmit)) QuickAction(label: 'Apply Leave', icon: Icons.edit_calendar_outlined, onTap: () => context.go('/app/leave-applications')),
      if (canViewAttendance) QuickAction(label: 'Attendance Log', icon: Icons.history, onTap: () => context.go('/app/attendance')),
      if (permissions.contains(attendanceRegularizationRequest)) QuickAction(label: 'Regularise Punch', icon: Icons.fact_check_outlined, onTap: () => context.push('/app/regularizations')),
      if (canViewAttendance) QuickAction(label: 'Overtime', icon: Icons.hourglass_bottom_outlined, onTap: () => context.push('/app/overtime')),
    ];
    if (actions.isNotEmpty) {
      children
        ..add(const EmployeeSectionHeader('Quick actions', prominent: true, caption: 'Frequently used'))
        ..add(QuickActionsGrid(actions: actions));
    }

    // H-05 balances.
    if (canSeeLeave) {
      final balances = ref.watch(homeBalancesProvider(employeeId));
      children.add(EmployeeSectionHeader('Leave', prominent: true, actionLabel: 'View detailed ledger', onAction: () => context.push('/app/leave-balances')));
      children.add(balances.when(
        loading: () => const _SectionSkeleton(),
        error: (e, _) => _SectionError(message: 'Leave balances are unavailable.', detail: describeApiError(e), onRetry: () => ref.invalidate(homeBalancesProvider(employeeId))),
        data: (rows) => rows.isEmpty
            ? const Padding(padding: EdgeInsets.symmetric(horizontal: 16), child: Text('No leave balances yet.'))
            : LeaveBalanceBars(items: _balanceItems(rows, ref.watch(homeLeaveCreditsProvider(employeeId)).valueOrNull ?? const {})),
      ));
    }

    // H-06/H-07 requests: what still awaits a decision first, then the latest decided leave.
    final leaveApps = canSeeLeave ? ref.watch(homeLeaveProvider(employeeId)) : null;
    final pendingCorrections = canViewAttendance ? ref.watch(homeSubmittedCorrectionsProvider(employeeId)) : null;
    final typeNames = canSeeLeave ? {for (final b in ref.watch(homeBalancesProvider(employeeId)).valueOrNull ?? const <LeaveBalance>[]) b.leaveTypeId: b.leaveTypeName} : const <String, String>{};
    final apps = leaveApps?.valueOrNull ?? const <LeaveApplication>[];
    final requests = <Widget>[
      for (final a in apps.where((a) => a.status == 'SUBMITTED')) _leaveRow(a, typeNames),
      for (final c in pendingCorrections?.valueOrNull ?? const <HomeCorrection>[])
        RequestRow(title: c.title, caption: c.caption, status: statusForRequest('SUBMITTED'), onTap: () => context.push('/app/regularizations')),
      for (final a in apps.where((a) => a.status != 'SUBMITTED')) _leaveRow(a, typeNames),
    ].take(3).toList();
    final pendingCount = apps.where((a) => a.status == 'SUBMITTED').length + (pendingCorrections?.valueOrNull?.length ?? 0);
    if (requests.isNotEmpty) {
      children
        ..add(EmployeeSectionHeader('Requests', prominent: true, count: pendingCount == 0 ? null : pendingCount, actionLabel: 'See all', onAction: () => context.go('/app/leave-applications')))
        ..add(EmployeeListGroup(children: requests));
    } else if (leaveApps != null && leaveApps.hasError && leaveApps.valueOrNull == null) {
      children
        ..add(const EmployeeSectionHeader('Requests', prominent: true))
        ..add(_SectionError(message: 'Leave applications are unavailable.', detail: describeApiError(leaveApps.error!), onRetry: () => ref.invalidate(homeLeaveProvider(employeeId))));
    }

    // Recent activity: the last attendance days and the latest leave decisions.
    final activity = _activity(
      zone: zone,
      days: canViewAttendance ? ref.watch(todayDataProvider(key)).valueOrNull?.recentDays(3) ?? const [] : const [],
      apps: apps,
      typeNames: typeNames,
    );
    if (activity.isNotEmpty) {
      children
        ..add(const EmployeeSectionHeader('Recent activity', prominent: true, caption: 'Latest'))
        ..add(RecentActivityList(items: activity));
    }

    // Latest payslip: omitted when there is none or the read fails (it is a convenience link here).
    if (canSeePayslip) {
      final payslip = ref.watch(homeLatestPayslipProvider(employeeId)).valueOrNull;
      if (payslip != null) {
        children
          ..add(const EmployeeSectionHeader('Payslip', prominent: true))
          ..add(EmployeeListGroup(children: [
            EmployeeListRow(
              title: formatPayMonth(payslip.month),
              trailing: Text(formatInr(payslip.netMinor), style: Theme.of(context).textTheme.titleMedium?.copyWith(fontWeight: FontWeight.w700)),
              onTap: () => _openPayslip(payslip),
            ),
          ]));
      }
    }

    children.add(const SizedBox(height: 32));
    return Scaffold(
      appBar: appBar,
      backgroundColor: t.canvas,
      body: RefreshIndicator(
        onRefresh: () async {
          _refreshAll(employeeId, key);
          await ref.read(todayDataProvider(key).future).catchError((_) => TodayData(punches: null, days: null, today: businessToday(zone)));
        },
        child: ListView(padding: const EdgeInsets.only(top: 8), children: children),
      ),
    );
  }

  /// Biggest balances first, at most three, each with what was credited this year when known.
  static List<({String name, num balance, num? total})> _balanceItems(List<LeaveBalance> rows, Map<String, num> credits) {
    final sorted = [...rows]..sort((a, b) => b.balance.compareTo(a.balance));
    return [for (final b in sorted.take(3)) (name: b.leaveTypeName, balance: b.balance, total: credits[b.leaveTypeId])];
  }

  /// The newest approved/rejected application decided within the last 48 hours.
  static LeaveApplication? _recentDecision(List<LeaveApplication> apps) {
    final cutoff = DateTime.now().toUtc().subtract(const Duration(hours: 48));
    LeaveApplication? best;
    DateTime? bestAt;
    for (final a in apps) {
      if (a.status != 'APPROVED' && a.status != 'REJECTED') continue;
      final at = DateTime.tryParse(a.raw['reviewed_at'] as String? ?? '');
      if (at == null || at.isBefore(cutoff)) continue;
      if (bestAt == null || at.isAfter(bestAt)) {
        best = a;
        bestAt = at;
      }
    }
    return best;
  }

  List<HomeActivity> _activity({required String zone, required List<AttendanceDay> days, required List<LeaveApplication> apps, required Map<String, String> typeNames}) {
    final out = <HomeActivity>[
      for (final d in days)
        if (d.actualFirstIn != null)
          HomeActivity(
            when: DateTime.parse(d.actualFirstIn!),
            icon: Icons.check_circle_outline,
            title: d.actualLastOut == null ? 'Checked in at ${formatClock24(d.actualFirstIn, zone)}' : 'Worked ${formatClock24(d.actualFirstIn, zone)} – ${formatClock24(d.actualLastOut, zone)}',
            caption: d.attendanceDate,
          ),
      for (final a in apps)
        if (DateTime.tryParse(a.raw['submitted_at'] as String? ?? '') case final at?)
          HomeActivity(
            when: DateTime.tryParse(a.raw['reviewed_at'] as String? ?? '') ?? at,
            icon: a.status == 'SUBMITTED' ? Icons.send_outlined : Icons.event_available_outlined,
            title: a.status == 'SUBMITTED' ? 'Leave request submitted' : 'Leave request ${a.status.toLowerCase()}',
            caption: '${typeNames[a.leaveTypeId] ?? 'Leave'} · ${shortDateRange(a.startDate, a.endDate)}',
          ),
    ]..sort((x, y) => y.when.compareTo(x.when));
    return out.take(3).toList();
  }

  Widget _leaveRow(LeaveApplication a, Map<String, String> typeNames) {
    final days = a.totalDays == null ? '' : ' · ${a.totalDays} ${a.totalDays == 1 ? 'day' : 'days'}';
    return RequestRow(title: _range(a), caption: '${typeNames[a.leaveTypeId] ?? 'Leave'}$days', status: statusForRequest(a.status), onTap: () => _openLeave(a));
  }

  void _openPayslip(PayslipSummary p) => Navigator.of(context).push(MaterialPageRoute(
        builder: (_) => EmployeeThemeScope(
          child: PayslipScreen(
            title: 'Payslip · ${formatPayMonth(p.month)}',
            load: () => ref.read(payrollRepositoryProvider).getMyPayslip(p.payRunId),
          ),
        ),
      ));

  void _openLeave(LeaveApplication a) => Navigator.of(context).push(MaterialPageRoute(builder: (_) => EmployeeThemeScope(child: LeaveApplicationDetailScreen(applicationId: a.id, initial: a))));

  /// "31 Oct – 2 Nov", or "31 Oct" for a single day.
  static String _range(LeaveApplication a) {
    String short(String iso) {
      const mo = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
      final d = DateTime.tryParse(iso);
      return d == null ? iso : '${d.day} ${mo[d.month - 1]}';
    }

    return a.startDate == a.endDate ? short(a.startDate) : '${short(a.startDate)} – ${short(a.endDate)}';
  }

  static String _longDate(String zone) {
    const wd = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'];
    const mo = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
    final d = DateTime.parse(businessToday(zone)); // a calendar date in the company zone, no clock involved
    return '${wd[d.weekday - 1]}, ${d.day} ${mo[d.month - 1]}';
  }
}

class _Identity extends StatelessWidget {
  const _Identity({required this.name, this.code});
  final String name;
  final String? code;

  @override
  Widget build(BuildContext context) {
    final t = EmployeeTokens.of(context);
    final theme = Theme.of(context);
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 16),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text(name, style: theme.textTheme.headlineMedium?.copyWith(fontWeight: FontWeight.w700)),
        if (code != null) Text(code!, style: theme.textTheme.bodySmall?.copyWith(color: t.inkSecondary)),
      ]),
    );
  }
}

class _SectionSkeleton extends StatelessWidget {
  const _SectionSkeleton();

  @override
  Widget build(BuildContext context) => const Padding(
        padding: EdgeInsets.symmetric(horizontal: 16),
        child: Row(children: [
          Expanded(child: SkeletonBlock(height: 40)),
          SizedBox(width: 12),
          Expanded(child: SkeletonBlock(height: 40)),
          SizedBox(width: 12),
          Expanded(child: SkeletonBlock(height: 40)),
        ]),
      );
}

class _SectionError extends StatelessWidget {
  const _SectionError({required this.message, required this.detail, required this.onRetry});
  final String message;
  final String detail;
  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context) {
    final t = EmployeeTokens.of(context);
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 16),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text(message, style: Theme.of(context).textTheme.bodyMedium),
        Text(detail, style: Theme.of(context).textTheme.bodySmall?.copyWith(color: t.inkSecondary)),
        TextButton(onPressed: onRetry, child: const Text('Try again')),
      ]),
    );
  }
}
