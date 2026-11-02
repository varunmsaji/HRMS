import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart' show SystemUiOverlayStyle;
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../core/auth/permissions.dart';
import '../../../core/format.dart';
import '../../../core/theme/employee_theme_scope.dart';
import '../../../core/time.dart';
import '../../attendance/data/attendance_repository.dart';
import '../../attendance/domain/today_state.dart';
import '../../attendance/presentation/context_punch_ui.dart';
import '../../attendance/presentation/face_enrollment_screen.dart';
import '../../../core/api/api_error.dart';
import '../../attendance/state/punch_controller.dart';
import '../../attendance/state/today_provider.dart';
import '../../auth/state/auth_controller.dart';
import '../../leave/data/leave_repository.dart';
import '../../leave/presentation/leave_application_detail_screen.dart';
import '../../payroll/data/payroll_repository.dart' show PayslipSummary;
import '../../payroll/presentation/payslip_screen.dart';
import '../../payroll/presentation/pay_runs_screen.dart' show payrollRepositoryProvider;
import '../state/home_providers.dart';
import '../state/home_stats.dart';
import '../../notifications/presentation/notification_bell.dart';
import '../../notifications/state/unread_count.dart';
import 'dashboard_design.dart';

/// The employee's face-enrollment status, read once for Home so the punch control knows whether
/// to offer a plain or a face punch before it offers anything (spec S10: disabled until known).
final homeFaceStatusProvider = FutureProvider.autoDispose.family<FaceEnrollmentStatus, String>((ref, employeeId) async {
  final status = await ref.watch(attendanceRepositoryProvider).getMyFaceEnrollment();
  ref.read(punchControllerProvider.notifier).setFaceRequired(status.faceVerificationRequired);
  return status;
});

/// Employee dashboard. Every figure is read from the existing APIs (attendance days and punches,
/// leave balances and applications, corrections, payslips, work profile); nothing is hard-coded,
/// and a card whose data is missing shows "—" rather than a made-up value. Punching goes through
/// the same [PunchController] as the Attendance tab.
class EmployeeHomeScreen extends ConsumerStatefulWidget {
  const EmployeeHomeScreen({super.key});

  @override
  ConsumerState<EmployeeHomeScreen> createState() => _EmployeeHomeScreenState();
}

class _EmployeeHomeScreenState extends ConsumerState<EmployeeHomeScreen> {
  Timer? _ticker;

  @override
  void initState() {
    super.initState();
    // Drives the live "worked today" clock; cheap, only this screen rebuilds.
    _ticker = Timer.periodic(const Duration(seconds: 1), (_) {
      if (mounted) setState(() {});
    });
  }

  @override
  void dispose() {
    _ticker?.cancel();
    super.dispose();
  }

  void _refreshAll(String employeeId, TodayKey key) {
    ref.read(unreadCountProvider.notifier).refresh();
    ref.invalidate(todayDataProvider(key));
    ref.invalidate(homeEmployeeProvider(employeeId));
    ref.invalidate(homeBalancesProvider(employeeId));
    ref.invalidate(homeLeaveProvider(employeeId));
    ref.invalidate(homeSubmittedCorrectionsProvider(employeeId));
    ref.invalidate(homeFaceStatusProvider(employeeId));
    ref.invalidate(homeLatestPayslipProvider(employeeId));
    ref.invalidate(homeWorkProfileProvider(employeeId));
    ref.invalidate(homeMonthDaysProvider((employeeId: employeeId, zone: key.zone)));
  }

  void _punch(String direction, TodayKey key) {
    final ui = ContextPunchUi(context, ref, onPunchedCallback: () => ref.invalidate(todayDataProvider(key)), onFaceNotEnrolledCallback: () => ref.invalidate(homeFaceStatusProvider(key.employeeId)));
    final controller = ref.read(punchControllerProvider.notifier);
    // Face verification is for check-in only; check-out is a plain punch.
    if (ref.read(punchControllerProvider).faceRequired && direction == 'IN') {
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

    if (employeeId == null) {
      return Scaffold(
        backgroundColor: Dd.canvas,
        body: SafeArea(child: Column(children: [_Header(onBell: () {}, onProfile: () => context.push('/app/more')), const Expanded(child: Center(child: Text('No employee record is linked to your account.')))])),
      );
    }

    final key = (employeeId: employeeId, zone: zone);
    final canViewAttendance = permissions.contains(attendanceView);
    final canPunch = permissions.contains(attendancePunch);
    final canSeeLeave = permissions.contains(leaveBalanceView);
    final canSeeName = permissions.contains(employeeView);
    final canSeePayslip = permissions.contains(payrollPayslipViewOwn);

    final employee = canSeeName ? ref.watch(homeEmployeeProvider(employeeId)).valueOrNull : null;
    final profile = canViewAttendance ? ref.watch(homeWorkProfileProvider(employeeId)).valueOrNull : null;
    final todayAsync = canViewAttendance ? ref.watch(todayDataProvider(key)) : null;
    final today = todayAsync?.valueOrNull;
    final state = todayAsync == null ? null : todayStateOf(todayAsync, key);
    final todayDate = today?.today ?? businessToday(zone);
    final monthDays = canViewAttendance ? ref.watch(homeMonthDaysProvider(key)).valueOrNull : null;
    final balances = canSeeLeave ? ref.watch(homeBalancesProvider(employeeId)).valueOrNull : null;
    final leaveApps = canSeeLeave ? ref.watch(homeLeaveProvider(employeeId)).valueOrNull : null;
    final corrections = canViewAttendance ? ref.watch(homeSubmittedCorrectionsProvider(employeeId)).valueOrNull : null;
    final payslip = canSeePayslip ? ref.watch(homeLatestPayslipProvider(employeeId)).valueOrNull : null;
    final face = canPunch ? ref.watch(homeFaceStatusProvider(employeeId)) : null;
    final typeNames = {for (final b in balances ?? const <LeaveBalance>[]) b.leaveTypeId: b.leaveTypeName};

    final pendingLeave = [for (final a in leaveApps ?? const <LeaveApplication>[]) if (a.status == 'SUBMITTED') a];
    final pendingCorrections = corrections ?? const <HomeCorrection>[];
    final attentionCount = pendingLeave.length + pendingCorrections.length;

    return Scaffold(
      backgroundColor: Dd.canvas,
      body: AnnotatedRegion<SystemUiOverlayStyle>(
        // The dark header runs behind the status bar, so its icons are light.
        value: SystemUiOverlayStyle.light,
        child: SafeArea(
          top: false,
          bottom: false,
          child: Column(children: [
            _Header(onBell: () => context.push('/app/notifications'), onProfile: () => context.push('/app/more')),
            Expanded(
              child: RefreshIndicator(
                onRefresh: () async {
                  _refreshAll(employeeId, key);
                  await ref.read(todayDataProvider(key).future).catchError((_) => TodayData(punches: null, days: null, today: businessToday(zone)));
                },
                child: ListView(
                  physics: const AlwaysScrollableScrollPhysics(),
                  padding: const EdgeInsets.fromLTRB(16, 4, 16, 24),
                  children: [
                    Row(mainAxisAlignment: MainAxisAlignment.spaceBetween, children: [
                      Flexible(child: DdPill(label: _longDate(todayDate), background: const Color(0xFFE8EEF9), foreground: Dd.navy, icon: Icons.calendar_today_outlined)),
                      if (face?.valueOrNull?.isEnrolled ?? false) ...[
                        const SizedBox(width: 8),
                        const Flexible(child: DdPill(label: 'AI Sync Active', background: Color(0xFFE0F2FE), foreground: Color(0xFF0369A1), icon: Icons.auto_awesome)),
                      ],
                    ]),
                    const SizedBox(height: 12),
                    _Greeting(name: employee?.firstName, code: employee?.employeeCode, designation: profile?.designation, department: profile?.department),
                    const SizedBox(height: 16),
                    if (canViewAttendance && state != null)
                      _PunchCard(
                        state: state,
                        data: today,
                        zone: zone,
                        shift: profile == null || profile.shiftStart == null || profile.shiftEnd == null ? null : '${profile.shiftStart} - ${profile.shiftEnd}',
                        canPunch: canPunch,
                        faceKnown: face == null || !face.isLoading || face.hasValue,
                        onPunch: (d) => _punch(d, key),
                      ),
                    if (canPunch && face?.valueOrNull != null && !face!.valueOrNull!.isEnrolled) ...[
                      const SizedBox(height: 16),
                      FaceSetupCard(status: face.valueOrNull!, onChanged: () => ref.invalidate(homeFaceStatusProvider(employeeId))),
                    ],
                    const SizedBox(height: 16),
                    _tiles(
                      context,
                      balances: balances,
                      pendingLeave: pendingLeave.length,
                      pendingCorrections: pendingCorrections.length,
                      known: leaveApps != null || corrections != null,
                      monthDays: monthDays,
                      todayDate: todayDate,
                      payslip: payslip,
                      showLeave: canSeeLeave,
                      showHours: canViewAttendance,
                      showPay: canSeePayslip,
                    ),
                    if (canViewAttendance && monthDays != null) ...[const SizedBox(height: 16), _monthCard(context, monthDays, todayDate)],
                    if (attentionCount > 0) ...[const SizedBox(height: 20), _attention(context, pendingLeave, pendingCorrections, typeNames, attentionCount, zone)],
                    const SizedBox(height: 20),
                    const Text('Quick Actions', style: TextStyle(fontSize: 17, fontWeight: FontWeight.w700, color: Dd.ink)),
                    const SizedBox(height: 10),
                    _quickActions(context, permissions, payslip),
                  ],
                ),
              ),
            ),
          ]),
        ),
      ),
    );
  }

  // ---- tiles ----------------------------------------------------------------------------------

  Widget _tiles(
    BuildContext context, {
    required List<LeaveBalance>? balances,
    required int pendingLeave,
    required int pendingCorrections,
    required bool known,
    required List<AttendanceDay>? monthDays,
    required String todayDate,
    required PayslipSummary? payslip,
    required bool showLeave,
    required bool showHours,
    required bool showPay,
  }) {
    String days(num n) => n == n.roundToDouble() ? '${n.toInt()}' : n.toStringAsFixed(1);
    final left = balances?.fold<num>(0, (s, b) => s + b.balance);
    final breakdown = balances == null || balances.isEmpty ? '—' : [for (final b in balances) '${_abbr(b.leaveTypeName)} ${days(b.balance)}'].join(' · ');

    final pending = pendingLeave + pendingCorrections;
    final pendingParts = [if (pendingLeave > 0) '$pendingLeave leave', if (pendingCorrections > 0) '$pendingCorrections correction'];

    // Hours this week: worked vs what the week's day rows scheduled.
    ({double worked, double target, double workedBefore, double targetBefore})? week;
    if (monthDays != null) {
      final t = DateTime.parse(todayDate);
      final monday = DateTime.utc(t.year, t.month, t.day - (t.weekday - 1));
      String iso(DateTime d) => '${d.year.toString().padLeft(4, '0')}-${d.month.toString().padLeft(2, '0')}-${d.day.toString().padLeft(2, '0')}';
      final from = iso(monday), to = iso(monday.add(const Duration(days: 6)));
      var worked = 0, target = 0, workedBefore = 0, targetBefore = 0;
      for (final d in monthDays) {
        if (d.attendanceDate.compareTo(from) < 0 || d.attendanceDate.compareTo(to) > 0) continue;
        final w = d.workedMinutes ?? 0;
        final s = (d.raw['scheduled_minutes'] as num?)?.toInt() ?? 0;
        worked += w;
        target += s;
        if (d.attendanceDate.compareTo(todayDate) < 0) {
          workedBefore += w;
          targetBefore += s;
        }
      }
      week = (worked: worked / 60, target: target / 60, workedBefore: workedBefore / 60, targetBefore: targetBefore / 60);
    }
    final pct = week == null || week.target == 0 ? null : (week.worked / week.target * 100).round();
    final onTrack = week != null && week.workedBefore >= week.targetBefore;

    final tiles = <Widget>[
      if (showLeave)
        DdStatTile(
          icon: Icons.beach_access_outlined,
          iconColor: Dd.navy,
          iconBackground: const Color(0xFFE8EEF9),
          badge: 'Paid',
          badgeColor: Dd.ink,
          badgeBackground: Colors.transparent,
          value: left == null ? '—' : days(left),
          unit: left == null ? null : 'days left',
          caption: breakdown,
          onTap: () => context.push('/app/leave-balances'),
        ),
      if (showLeave || showHours)
        DdStatTile(
          icon: Icons.assignment_late_outlined,
          iconColor: Dd.amberFg,
          iconBackground: Dd.amberBg,
          badge: 'Pending',
          badgeColor: Dd.amberFg,
          badgeBackground: Dd.amberBg,
          value: known ? '$pending' : '—',
          unit: known ? 'with HR' : null,
          caption: !known ? '—' : (pendingParts.isEmpty ? 'Nothing waiting' : pendingParts.join(' · ')),
          captionColor: pendingParts.isEmpty ? Dd.muted : Dd.red,
          onTap: () => context.go('/app/leave-applications'),
        ),
      if (showHours)
        DdStatTile(
          icon: Icons.schedule,
          iconColor: Dd.navy,
          iconBackground: const Color(0xFFE8EEF9),
          badge: week == null ? 'This week' : (onTrack ? 'On track' : 'Behind'),
          badgeColor: week == null ? Dd.muted : (onTrack ? Dd.green : Dd.red),
          badgeBackground: Colors.transparent,
          value: week == null ? '—' : week.worked.toStringAsFixed(1),
          unit: week == null ? null : 'hrs',
          caption: week == null || week.target == 0 ? 'No scheduled hours' : 'Target ${days(double.parse(week.target.toStringAsFixed(1)))}h · $pct% logged',
          onTap: () => context.go('/app/attendance'),
        ),
      if (showPay)
        DdStatTile(
          icon: Icons.payments_outlined,
          iconColor: Dd.green,
          iconBackground: const Color(0xFFDCFCE7),
          badge: payslip == null ? 'Payslip' : (payslip.status == 'PAID' ? 'Disbursed' : _title(payslip.status)),
          badgeColor: Dd.green,
          badgeBackground: Colors.transparent,
          value: payslip == null ? '—' : formatInr(payslip.netMinor),
          caption: payslip == null ? 'No payslip yet' : _payMonth(payslip.month),
          action: payslip == null ? null : 'View',
          onTap: payslip == null ? () => context.push('/app/me/payslips') : () => _openPayslip(payslip),
        ),
    ];
    return _TwoColumnGrid(children: tiles);
  }

  // ---- attendance this month ------------------------------------------------------------------

  Widget _monthCard(BuildContext context, List<AttendanceDay> days, String todayDate) {
    final monthPrefix = todayDate.substring(0, 7);
    final month = summariseMonth(days.where((d) => d.attendanceDate.startsWith(monthPrefix) && d.attendanceDate.compareTo(todayDate) <= 0));
    final total = month.total;
    String pct(int n) => total == 0 ? '0%' : '${(n / total * 100).toStringAsFixed(n * 1000 % total == 0 ? 0 : 1)}%';
    final presentPct = total == 0 ? 0 : (month.present / total * 100).round();
    final segments = [
      DdSegment('Present', month.present, Dd.navy),
      DdSegment('On leave', month.onLeave, Dd.cyan),
      DdSegment('Absent', month.absent, const Color(0xFFB91C1C)),
      DdSegment('Other', month.other, const Color(0xFFE3E8F2)),
    ];
    final d = DateTime.parse(todayDate);
    return DdCard(
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Expanded(
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              const Text('Attendance this month', style: TextStyle(fontSize: 16, fontWeight: FontWeight.w700, color: Dd.ink)),
              const SizedBox(height: 3),
              Text('${_monthName(d.month)} ${d.year} · $total Working Days', style: const TextStyle(fontSize: 11.5, color: Dd.muted, fontWeight: FontWeight.w500)),
            ]),
          ),
          DdPill(label: '$presentPct% Present', background: const Color(0xFFDCFCE7), foreground: Dd.green),
        ]),
        const SizedBox(height: 16),
        Row(children: [
          DdDonut(segments: segments, total: total),
          const SizedBox(width: 16),
          Expanded(
            child: Wrap(runSpacing: 12, spacing: 8, children: [
              for (final s in segments) SizedBox(width: 118, child: _Legend(segment: s, percent: pct(s.count), singular: s.label == 'Present' || s.label == 'Absent' || s.label == 'Other')),
            ]),
          ),
        ]),
        const SizedBox(height: 14),
        Container(
          padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 11),
          decoration: BoxDecoration(color: const Color(0xFFEFF3FA), borderRadius: BorderRadius.circular(12)),
          child: Row(children: [
            const Icon(Icons.info_outline, size: 16, color: Dd.navy),
            const SizedBox(width: 8),
            Expanded(child: Text('${month.weeklyOffs} weekly offs · ${month.holidays} public ${month.holidays == 1 ? 'holiday' : 'holidays'}', style: const TextStyle(fontSize: 12, color: Dd.ink, fontWeight: FontWeight.w500))),
            GestureDetector(onTap: () => context.go('/app/attendance'), child: const Text('View logs', style: TextStyle(fontSize: 12, fontWeight: FontWeight.w700, color: Dd.navy))),
          ]),
        ),
      ]),
    );
  }

  // ---- needs attention ------------------------------------------------------------------------

  Widget _attention(BuildContext context, List<LeaveApplication> leave, List<HomeCorrection> corrections, Map<String, String> typeNames, int count, String zone) {
    final rows = <Widget>[
      for (final a in leave)
        DdAttentionRow(
          icon: Icons.event_note_outlined,
          iconColor: Dd.navy,
          iconBackground: const Color(0xFFE8EEF9),
          title: typeNames[a.leaveTypeId] ?? 'Leave',
          badge: 'Submitted',
          badgeColor: Dd.amberFg,
          badgeBackground: Dd.amberBg,
          caption: [_range(a.startDate, a.endDate), if (a.totalDays != null) '${a.totalDays} ${a.totalDays == 1 ? 'day' : 'days'}', if (_ago(a.raw['submitted_at'] as String?) case final ago?) ago].join(' · '),
          onTap: () => Navigator.of(context).push(MaterialPageRoute(builder: (_) => EmployeeThemeScope(child: LeaveApplicationDetailScreen(applicationId: a.id, initial: a)))),
        ),
      for (final c in corrections)
        DdAttentionRow(
          icon: Icons.edit_note,
          iconColor: Dd.amberFg,
          iconBackground: const Color(0xFFFFF4E0),
          title: 'Punch Correction',
          badge: 'Submitted',
          badgeColor: Dd.amberFg,
          badgeBackground: Dd.amberBg,
          caption: [c.title, if (c.caption != null) _shortDate(c.caption!), if (_ago(c.submittedAt) case final ago?) ago].join(' · '),
          onTap: () => context.push('/app/regularizations'),
        ),
    ].take(3).toList();
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Row(children: [
        const Flexible(child: Text('Needs attention', maxLines: 1, overflow: TextOverflow.ellipsis, style: TextStyle(fontSize: 17, fontWeight: FontWeight.w700, color: Dd.ink))),
        const SizedBox(width: 8),
        Container(padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2), decoration: BoxDecoration(color: Dd.amberBg, borderRadius: BorderRadius.circular(10)), child: Text('$count', style: const TextStyle(fontSize: 12, fontWeight: FontWeight.w700, color: Dd.amberFg))),
        const Spacer(),
        Flexible(child: GestureDetector(onTap: () => context.go('/app/leave-applications'), child: Text('View all ($count)', maxLines: 1, overflow: TextOverflow.ellipsis, style: const TextStyle(fontSize: 12.5, fontWeight: FontWeight.w700, color: Dd.navy)))),
      ]),
      const SizedBox(height: 10),
      for (final r in rows) Padding(padding: const EdgeInsets.only(bottom: 10), child: r),
    ]);
  }

  // ---- quick actions --------------------------------------------------------------------------

  Widget _quickActions(BuildContext context, List<String> permissions, PayslipSummary? payslip) {
    final items = <Widget>[
      if (permissions.contains(leaveApplicationSubmit)) DdQuickAction(icon: Icons.flight_takeoff, iconColor: const Color(0xFF0369A1), iconBackground: const Color(0xFFE0F2FE), title: 'Apply Leave', subtitle: 'Quick balance slip', onTap: () => context.go('/app/leave-applications')),
      if (permissions.contains(attendanceRegularizationRequest)) DdQuickAction(icon: Icons.history_toggle_off, iconColor: Dd.navy, iconBackground: const Color(0xFFE3E8FB), title: 'Correction', subtitle: 'Fix missed punch', onTap: () => context.push('/app/regularizations')),
      if (permissions.contains(payrollPayslipViewOwn)) DdQuickAction(icon: Icons.receipt_long_outlined, iconColor: Dd.green, iconBackground: const Color(0xFFDCFCE7), title: 'Payslips', subtitle: payslip == null ? 'Download payslip' : 'Download ${_payMonth(payslip.month, withYear: false)} slip', onTap: () => context.push('/app/me/payslips')),
      if (permissions.contains(attendanceView)) DdQuickAction(icon: Icons.calendar_month_outlined, iconColor: Dd.navy, iconBackground: const Color(0xFFE8EEF9), title: 'My Shifts', subtitle: 'Upcoming roster', onTap: () => context.go('/app/attendance')),
    ];
    return _TwoColumnGrid(children: items);
  }

  void _openPayslip(PayslipSummary p) => Navigator.of(context).push(MaterialPageRoute(
        builder: (_) => EmployeeThemeScope(
          child: PayslipScreen(
            title: 'Payslip · ${formatPayMonth(p.month)}',
            load: () => ref.read(payrollRepositoryProvider).getMyPayslip(p.payRunId),
          ),
        ),
      ));

  // ---- formatting helpers ---------------------------------------------------------------------

  static const _mo = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  static const _moFull = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'];
  static String _monthName(int m) => _moFull[m - 1];

  static String _abbr(String name) => name.trim().length <= 3 ? name.trim() : name.trim().substring(0, 3);
  static String _title(String s) => s.isEmpty ? s : s[0] + s.substring(1).toLowerCase();

  /// "2026-09" -> "Sept 2026" (or "Sept" without the year).
  static String _payMonth(String month, {bool withYear = true}) {
    final parts = month.split('-');
    final m = int.tryParse(parts.length > 1 ? parts[1] : '');
    if (m == null || m < 1 || m > 12) return month;
    final full = _moFull[m - 1];
    final name = m == 9 ? 'Sept' : (full.length <= 4 ? full : full.substring(0, 3));
    return withYear ? '$name ${parts[0]}' : name;
  }

  static String _longDate(String iso) {
    const wd = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'];
    final d = DateTime.parse(iso);
    return '${wd[d.weekday - 1]}, ${d.day} ${_mo[d.month - 1]} ${d.year}';
  }

  static String _shortDate(String iso) {
    final d = DateTime.tryParse(iso);
    return d == null ? iso : '${d.day} ${_mo[d.month - 1]}';
  }

  /// "12–13 Nov", "12 Nov", or "30 Oct – 2 Nov".
  static String _range(String a, String b) {
    final s = DateTime.tryParse(a), e = DateTime.tryParse(b);
    if (s == null || e == null) return a == b ? a : '$a – $b';
    if (a == b) return '${s.day} ${_mo[s.month - 1]}';
    if (s.month == e.month) return '${s.day}–${e.day} ${_mo[e.month - 1]}';
    return '${s.day} ${_mo[s.month - 1]} – ${e.day} ${_mo[e.month - 1]}';
  }

  static String? _ago(String? iso) {
    final t = DateTime.tryParse(iso ?? '');
    if (t == null) return null;
    final d = DateTime.now().toUtc().difference(t.toUtc());
    if (d.isNegative || d.inMinutes < 1) return 'just now';
    if (d.inHours < 1) return '${d.inMinutes}m ago';
    if (d.inDays < 1) return '${d.inHours}h ago';
    return '${d.inDays}d ago';
  }
}

/// Two equal columns whose rows are exactly as tall as their content. Unlike a [GridView] with a
/// fixed `childAspectRatio`, the cell height follows the text (system font size, long captions), so
/// nothing is clipped or overflows; the two cells in a row are stretched to the same height.
class _TwoColumnGrid extends StatelessWidget {
  const _TwoColumnGrid({required this.children});
  final List<Widget> children;

  @override
  Widget build(BuildContext context) {
    final rows = <Widget>[];
    for (var i = 0; i < children.length; i += 2) {
      if (rows.isNotEmpty) rows.add(const SizedBox(height: 12));
      rows.add(IntrinsicHeight(
        child: Row(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          Expanded(child: children[i]),
          const SizedBox(width: 12),
          Expanded(child: i + 1 < children.length ? children[i + 1] : const SizedBox.shrink()),
        ]),
      ));
    }
    return Column(children: rows);
  }
}

class _Header extends StatelessWidget {
  const _Header({required this.onBell, required this.onProfile});
  final VoidCallback onBell;
  final VoidCallback onProfile;

  @override
  Widget build(BuildContext context) => DecoratedBox(
        decoration: const BoxDecoration(
          gradient: LinearGradient(begin: Alignment.topLeft, end: Alignment.bottomRight, colors: [Dd.navy, Color(0xFF123A8F)]),
          borderRadius: BorderRadius.vertical(bottom: Radius.circular(20)),
          boxShadow: [BoxShadow(color: Color(0x330A1F5C), blurRadius: 12, offset: Offset(0, 4))],
        ),
        // Own SafeArea so the dark bar paints behind the status bar instead of leaving a light strip.
        child: SafeArea(
          bottom: false,
          child: Padding(
            padding: const EdgeInsets.fromLTRB(16, 10, 16, 14),
            child: Row(children: [
              Container(
                width: 40,
                height: 40,
                padding: const EdgeInsets.all(8),
                decoration: BoxDecoration(color: Colors.white, borderRadius: BorderRadius.circular(12)),
                child: const Image(image: AssetImage('assets/brand/krewoxa-mark.png'), semanticLabel: 'Krewoxa'),
              ),
              const SizedBox(width: 10),
              const Expanded(
                child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Text('Krewoxa', maxLines: 1, overflow: TextOverflow.ellipsis, style: TextStyle(fontSize: 17, fontWeight: FontWeight.w800, color: Colors.white, height: 1.1)),
                  Text('ENTERPRISE', maxLines: 1, overflow: TextOverflow.ellipsis, style: TextStyle(fontSize: 10, fontWeight: FontWeight.w700, color: Color(0xFF9CC2FF), letterSpacing: 1.1)),
                ]),
              ),
              NotificationBell(onPressed: onBell, color: Colors.white),
              GestureDetector(
                onTap: onProfile,
                child: const CircleAvatar(radius: 19, backgroundColor: Colors.white, child: Icon(Icons.person, size: 20, color: Dd.navy)),
              ),
            ]),
          ),
        ),
      );
}

class _Greeting extends StatelessWidget {
  const _Greeting({this.name, this.code, this.designation, this.department});
  final String? name;
  final String? code;
  final String? designation;
  final String? department;

  @override
  Widget build(BuildContext context) {
    final sub = [code, designation, department].whereType<String>().where((e) => e.isNotEmpty).join(' · ');
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Text.rich(TextSpan(children: [
        const TextSpan(text: "Here's your workday, "),
        if (name != null) TextSpan(text: name, style: const TextStyle(color: Dd.blue)),
        const TextSpan(text: '.'),
      ]), style: const TextStyle(fontSize: 25, fontWeight: FontWeight.w800, color: Dd.navy, height: 1.2)),
      if (sub.isNotEmpty) ...[const SizedBox(height: 4), Text(sub, style: const TextStyle(fontSize: 12.5, color: Dd.muted, fontWeight: FontWeight.w500))],
    ]);
  }
}

class _Legend extends StatelessWidget {
  const _Legend({required this.segment, required this.percent, required this.singular});
  final DdSegment segment;
  final String percent;
  final bool singular;

  @override
  Widget build(BuildContext context) {
    final n = segment.count;
    final label = segment.label == 'On leave' ? 'On leave' : segment.label;
    return Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Padding(padding: const EdgeInsets.only(top: 4), child: Container(width: 8, height: 8, decoration: BoxDecoration(color: segment.color, shape: BoxShape.circle))),
      const SizedBox(width: 6),
      Expanded(
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text('$n ${n == 1 ? 'Day' : 'Days'}', style: const TextStyle(fontSize: 12, fontWeight: FontWeight.w700, color: Dd.ink)),
          Text('$label ($percent)', style: const TextStyle(fontSize: 11, color: Dd.muted, fontWeight: FontWeight.w500)),
        ]),
      ),
    ]);
  }
}

/// The "worked today" card: status line, live clock, progress, and the punch button.
class _PunchCard extends StatelessWidget {
  const _PunchCard({required this.state, required this.data, required this.zone, required this.shift, required this.canPunch, required this.faceKnown, required this.onPunch});
  final TodayState state;
  final TodayData? data;
  final String zone;
  final String? shift;
  final bool canPunch;
  final bool faceKnown;
  final void Function(String direction) onPunch;

  /// Seconds worked today. While punched in it follows the punches (closed IN→OUT pairs plus the
  /// open one up to now) so the clock ticks; otherwise it is the server's `worked_minutes`.
  int _workedSeconds() {
    if (state.kind == TodayStateKind.punchedIn) {
      final today = data?.today ?? businessToday(zone);
      final punches = [for (final p in data?.punches ?? const <Punch>[]) if (dateInZone(p.punchTime, zone) == today) p]..sort((a, b) => a.punchTime.compareTo(b.punchTime));
      DateTime? open;
      var total = 0;
      for (final p in punches) {
        final t = DateTime.parse(p.punchTime);
        if (p.direction == 'IN') {
          open ??= t;
        } else if (open != null) {
          total += t.difference(open).inSeconds;
          open = null;
        }
      }
      if (open != null) total += DateTime.now().toUtc().difference(open.toUtc()).inSeconds.clamp(0, 86400 * 2);
      return total;
    }
    return state.showWorked ? (state.day?.workedMinutes ?? 0) * 60 : 0;
  }

  String? _since() {
    final today = data?.today ?? businessToday(zone);
    final ins = [for (final p in data?.punches ?? const <Punch>[]) if (p.direction == 'IN' && dateInZone(p.punchTime, zone) == today) p.punchTime]..sort();
    return ins.isEmpty ? null : formatClock24(ins.first, zone);
  }

  @override
  Widget build(BuildContext context) {
    final kind = state.kind;
    final loading = kind == TodayStateKind.loading;
    final secs = _workedSeconds();
    final scheduled = (state.day?.raw['scheduled_minutes'] as num?)?.toInt();
    final remainingMin = scheduled == null ? null : (scheduled - secs ~/ 60).clamp(0, scheduled);
    final progress = scheduled == null || scheduled == 0 ? 0.0 : (secs / 60 / scheduled).clamp(0.0, 1.0);
    String two(int n) => n.toString().padLeft(2, '0');
    final clock = '${two(secs ~/ 3600)}:${two(secs % 3600 ~/ 60)}:${two(secs % 60)}';

    final (Color dot, String status) = switch (kind) {
      TodayStateKind.punchedIn => (Dd.green, 'Punched in${_since() == null ? '' : ' · Since ${_since()}'}'),
      TodayStateKind.punchedOut => (Dd.muted, 'Punched out${state.lastPunch == null ? '' : ' · ${formatClock24(state.lastPunch!.punchTime, zone)}'}'),
      TodayStateKind.notPunchedIn || TodayStateKind.noData => (Dd.amberFg, 'Not punched in'),
      TodayStateKind.onLeave => (Dd.cyan, 'On leave today'),
      TodayStateKind.notWorkingDay => (Dd.muted, 'Not a working day'),
      TodayStateKind.loading => (Dd.muted, 'Checking today…'),
      TodayStateKind.calculating => (Dd.amberFg, 'Updating your day…'),
      _ => (Dd.muted, 'Status unavailable'),
    };

    final dir = state.likely == LikelyPunch.punchOut ? 'OUT' : 'IN';
    final caption = state.likely == LikelyPunch.punchOut ? 'Punch out when you finish your shift' : 'Punch in to start your shift';

    return DdCard(
      padding: const EdgeInsets.all(18),
      gradient: const LinearGradient(begin: Alignment.topLeft, end: Alignment.bottomRight, colors: [Color(0xFFEAF2FF), Colors.white], stops: [0, 0.6]),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [
          Container(width: 9, height: 9, decoration: BoxDecoration(color: dot, shape: BoxShape.circle)),
          const SizedBox(width: 8),
          Expanded(flex: 3, child: Text(status, overflow: TextOverflow.ellipsis, style: const TextStyle(fontSize: 13.5, fontWeight: FontWeight.w700, color: Dd.green).copyWith(color: dot == Dd.green ? Dd.green : Dd.ink))),
          if (shift != null) Flexible(flex: 2, child: DdPill(label: 'Shift $shift', background: const Color(0xFFDCE8FB), foreground: Dd.navy)),
        ]),
        const SizedBox(height: 18),
        Row(crossAxisAlignment: CrossAxisAlignment.end, children: [
          Expanded(
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              const Text('WORKED TODAY', style: TextStyle(fontSize: 11, fontWeight: FontWeight.w700, color: Dd.muted, letterSpacing: 0.6)),
              const SizedBox(height: 4),
              FittedBox(
                fit: BoxFit.scaleDown,
                alignment: Alignment.centerLeft,
                child: Row(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.baseline, textBaseline: TextBaseline.alphabetic, children: [
                  Text(loading ? '--:--:--' : clock, style: const TextStyle(fontSize: 32, fontWeight: FontWeight.w800, color: Dd.navy, fontFeatures: [FontFeature.tabularFigures()])),
                  const SizedBox(width: 6),
                  const Text('hrs', style: TextStyle(fontSize: 13, color: Dd.blue, fontWeight: FontWeight.w600)),
                ]),
              ),
            ]),
          ),
          Column(crossAxisAlignment: CrossAxisAlignment.end, children: [
            const Text('Remaining', style: TextStyle(fontSize: 11.5, color: Dd.muted, fontWeight: FontWeight.w500)),
            Text(remainingMin == null ? '—' : '${remainingMin ~/ 60}h ${remainingMin % 60}m', style: const TextStyle(fontSize: 16, fontWeight: FontWeight.w800, color: Dd.blue)),
          ]),
        ]),
        const SizedBox(height: 14),
        ClipRRect(
          borderRadius: BorderRadius.circular(6),
          child: LinearProgressIndicator(value: progress, minHeight: 6, backgroundColor: const Color(0xFFE3E8F2), valueColor: const AlwaysStoppedAnimation(Dd.navy)),
        ),
        if (canPunch) ...[
          const SizedBox(height: 16),
          Consumer(builder: (context, ref, _) {
            final punch = ref.watch(punchControllerProvider);
            final busy = punch.plainBusy || punch.faceBusy;
            final enabled = faceKnown && !busy && !loading;
            final label = '${punch.faceRequired && dir == 'IN' ? 'Face punch' : 'Punch'} ${dir == 'IN' ? 'in' : 'out'}';
            return Column(children: [
              SizedBox(
                width: double.infinity,
                height: 50,
                child: FilledButton.icon(
                  style: FilledButton.styleFrom(backgroundColor: Dd.navy, foregroundColor: Colors.white, shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(14)), textStyle: const TextStyle(fontSize: 16, fontWeight: FontWeight.w700)),
                  onPressed: enabled ? () => onPunch(dir) : null,
                  icon: busy ? const SizedBox(width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white)) : Icon(dir == 'IN' ? Icons.login_rounded : Icons.logout_rounded, size: 20),
                  label: Text(busy ? (punch.faceBusy ? 'Verifying…' : 'Recording punch…') : label),
                ),
              ),
              const SizedBox(height: 10),
              Text(faceKnown ? caption : 'Checking your punch options…', style: const TextStyle(fontSize: 12, color: Dd.ink, fontWeight: FontWeight.w500)),
            ]);
          }),
        ],
      ]),
    );
  }
}

/// "Face Attendance Setup": shown until the employee's face is enrolled. Everything shown comes
/// from the server's own enrollment state; starting only opens the employee's own window (the
/// same one HR can open), and the capture still goes through server-side liveness, consent and
/// HR approval. Nothing here marks the employee enrolled.
class FaceSetupCard extends ConsumerStatefulWidget {
  const FaceSetupCard({required this.status, required this.onChanged});
  final FaceEnrollmentStatus status;
  final VoidCallback onChanged;

  @override
  ConsumerState<FaceSetupCard> createState() => FaceSetupCardState();
}

class FaceSetupCardState extends ConsumerState<FaceSetupCard> {
  bool _busy = false;

  Future<void> _start() async {
    final messenger = ScaffoldMessenger.of(context);
    setState(() => _busy = true);
    try {
      if (!widget.status.canEnroll) {
        await ref.read(attendanceRepositoryProvider).startMyFaceEnrollment();
      }
      if (!mounted) return;
      final submitted = await pushKeepingTheme<bool>(context, (_) => const FaceEnrollmentScreen());
      if (submitted == true) messenger.showSnackBar(const SnackBar(content: Text('Face submitted. HR will review it before face attendance is switched on.')));
    } catch (error) {
      messenger.showSnackBar(SnackBar(content: Text(describeApiError(error))));
    } finally {
      if (mounted) setState(() => _busy = false);
      widget.onChanged();
    }
  }

  @override
  Widget build(BuildContext context) {
    final st = widget.status;
    final pending = st.isPendingApproval;
    final available = st.canEnroll;
    final rejected = st.profileStatus == 'REJECTED';
    final title = pending ? 'Face enrollment submitted' : 'Face Attendance Setup';
    final body = pending
        ? 'HR is reviewing your enrollment. Face attendance turns on once it is approved.'
        : rejected
            ? (st.reviewNote == null || st.reviewNote!.isEmpty ? 'Your last enrollment was not approved. Please enroll again.' : 'Your last enrollment was not approved: ${st.reviewNote}')
            : st.companyRequiresEnrollment
                ? 'Your company requires face enrollment. Complete it to use face-based attendance.'
                : 'Complete face enrollment to use face-based attendance.';
    return DdCard(
      child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Container(
          width: 40,
          height: 40,
          decoration: BoxDecoration(color: const Color(0xFFE8EEF9), borderRadius: BorderRadius.circular(12)),
          child: Icon(pending ? Icons.hourglass_top_rounded : Icons.face_retouching_natural, size: 21, color: Dd.navy),
        ),
        const SizedBox(width: 12),
        Expanded(
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text(title, style: const TextStyle(fontSize: 14.5, fontWeight: FontWeight.w700, color: Dd.ink)),
            const SizedBox(height: 4),
            Text(body, style: const TextStyle(fontSize: 12, color: Dd.muted, height: 1.35)),
            if (!pending) ...[
              const SizedBox(height: 10),
              // No fixed height: the label must fit whatever font size the phone uses.
              SizedBox(
                width: double.infinity,
                child: FilledButton(
                  style: FilledButton.styleFrom(
                    backgroundColor: Dd.navy,
                    minimumSize: const Size(0, 40),
                    padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
                    shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
                  ),
                  onPressed: _busy ? null : _start,
                  child: _busy ? const SizedBox(width: 16, height: 16, child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white)) : Text(available ? 'Continue Enrollment' : 'Start Enrollment'),
                ),
              ),
            ],
          ]),
        ),
      ]),
    );
  }
}
