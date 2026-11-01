import 'package:flutter/material.dart' show IconData;
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/providers.dart';
import '../../attendance/domain/request_resources.dart' show regularizationTypeLabels;
import '../../leave/data/leave_repository.dart';
import '../../payroll/data/payroll_repository.dart';
import '../../payroll/presentation/pay_runs_screen.dart' show payrollRepositoryProvider;
import '../../profile/data/employee_repository.dart';
import '../../profile/presentation/profile_screen.dart' show employeeRepositoryProvider;

/// Each Home widget has its own provider so one failing read never hides another
/// (spec S10: "attendance failure never hides leave"). All are keyed by employee id.

/// H-01. Null when the read fails: Home then shows no name, never a placeholder.
final homeEmployeeProvider = FutureProvider.autoDispose.family<Employee, String>((ref, employeeId) {
  return ref.watch(employeeRepositoryProvider).getEmployee(employeeId);
});

/// H-05.
final homeBalancesProvider = FutureProvider.autoDispose.family<List<LeaveBalance>, String>((ref, employeeId) {
  return ref.watch(leaveRepositoryProvider).listLeaveBalances(employeeId);
});

/// H-06/H-07: the employee's own leave applications, newest first (the first page only).
final homeLeaveProvider = FutureProvider.autoDispose.family<List<LeaveApplication>, String>((ref, employeeId) async {
  final env = await ref.watch(leaveRepositoryProvider).listLeaveApplicationsPage(employeeId: employeeId);
  return env.data;
});

/// A correction request, reduced to what Home shows.
class HomeCorrection {
  const HomeCorrection({required this.id, required this.title, this.caption, this.submittedAt});
  final String id;
  final String? submittedAt;
  final String title;
  final String? caption;
}

/// H-06: own attendance corrections still awaiting a decision (`GET /regularizations`,
/// `ATTENDANCE.VIEW`).
final homeSubmittedCorrectionsProvider = FutureProvider.autoDispose.family<List<HomeCorrection>, String>((ref, employeeId) async {
  final env = await ref.watch(apiClientProvider).getList<HomeCorrection>(
        '/regularizations',
        filters: {'employee_id': employeeId, 'request_status': 'SUBMITTED'},
        parseItem: (d) {
          final m = d as Map<String, dynamic>;
          return HomeCorrection(
            id: m['id'] as String,
            title: regularizationTypeLabels[m['request_type']] ?? 'Attendance correction',
            caption: m['attendance_date'] as String?,
            submittedAt: m['submitted_at'] as String?,
          );
        },
      );
  return env.data;
});

/// The newest finalised payslip (`GET /me/payslips`, `PAYROLL.PAYSLIP_VIEW_OWN`), or null when
/// there is none yet. The endpoint is scoped to the signed-in user by the server.
final homeLatestPayslipProvider = FutureProvider.autoDispose.family<PayslipSummary?, String>((ref, employeeId) async {
  final all = await ref.watch(payrollRepositoryProvider).listMyPayslips();
  if (all.isEmpty) return null;
  // Months are "YYYY-MM", so a string sort is chronological.
  return ([...all]..sort((a, b) => b.month.compareTo(a.month))).first;
});

/// Days credited per leave type this year (ledger credits: opening balance, accrual, adjustments),
/// so Home can show "balance of total". Empty when the ledger cannot be read; Home then shows the
/// balance alone. Debits (applications, encashment) are excluded; the balance API already nets them.
final homeLeaveCreditsProvider = FutureProvider.autoDispose.family<Map<String, num>, String>((ref, employeeId) async {
  final env = await ref.watch(leaveRepositoryProvider).listLeaveLedger(employeeId);
  final credits = <String, num>{};
  for (final e in env.data) {
    if (e.amount > 0 && e.effectiveDate.startsWith(DateTime.now().year.toString())) {
      credits[e.leaveTypeId] = (credits[e.leaveTypeId] ?? 0) + e.amount;
    }
  }
  return credits;
});

/// One line of Home's "Recent activity".
class HomeActivity {
  const HomeActivity({required this.when, required this.icon, required this.title, required this.caption});
  final DateTime when;
  final IconData icon;
  final String title;
  final String caption;
}

/// The caller's current shift and work location (`GET /employee-work-profile/me`,
/// `ATTENDANCE.VIEW`). Either part is null when the placement carries none; Home then omits that card.
class HomeWorkProfile {
  const HomeWorkProfile({this.shiftName, this.shiftStart, this.shiftEnd, this.locationName, this.locationDetail, this.designation, this.department});

  final String? shiftName;

  /// "HH:mm" in the shift's own timezone.
  final String? shiftStart;
  final String? shiftEnd;
  final String? locationName;

  /// Address line and city, whichever the branch has.
  final String? locationDetail;
  final String? designation;
  final String? department;

  factory HomeWorkProfile.fromJson(Map<String, dynamic> json) {
    String? hhmm(Object? v) => v is String && v.length >= 5 ? v.substring(0, 5) : null;
    final shift = json['shift'] as Map<String, dynamic>?;
    final location = json['work_location'] as Map<String, dynamic>?;
    final detail = [location?['address_line1'], location?['city']].whereType<String>().where((e) => e.isNotEmpty).join(' · ');
    return HomeWorkProfile(
      shiftName: shift?['name'] as String?,
      shiftStart: hhmm(shift?['start_time']),
      shiftEnd: hhmm(shift?['end_time']),
      locationName: location?['name'] as String?,
      locationDetail: detail.isEmpty ? null : detail,
      designation: json['designation'] as String?,
      department: json['department'] as String?,
    );
  }
}

final homeWorkProfileProvider = FutureProvider.autoDispose.family<HomeWorkProfile, String>((ref, employeeId) {
  return ref.watch(apiClientProvider).get('/employee-work-profile/me', parse: (d) => HomeWorkProfile.fromJson(d as Map<String, dynamic>));
});
