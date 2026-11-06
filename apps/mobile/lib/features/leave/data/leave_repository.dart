import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api/api_client.dart';
import '../../../core/providers.dart';
import '../../../core/api/envelope.dart';
import '../../../core/json.dart';
import '../domain/leave_decision_center.dart';

class LeaveType {
  LeaveType({
    required this.id,
    required this.code,
    required this.name,
    required this.isPaidDefault,
    required this.requiresBalance,
    required this.isCompOff,
    this.statutoryCategory,
    required this.isActive,
    required this.version,
  });
  final String id;
  final String code;
  final String name;
  final bool isPaidDefault;
  final bool requiresBalance;
  final bool isCompOff;
  final String? statutoryCategory;
  final bool isActive;
  final int version;

  factory LeaveType.fromJson(Map<String, dynamic> json) => LeaveType(
        id: json['id'] as String,
        code: json['code'] as String,
        name: json['name'] as String,
        isPaidDefault: json['is_paid_default'] as bool,
        requiresBalance: json['requires_balance'] as bool,
        isCompOff: json['is_comp_off'] as bool,
        statutoryCategory: json['statutory_category'] as String?,
        isActive: json['is_active'] as bool,
        version: json['version'] as int,
      );
}

class LeaveCombinationRule {
  LeaveCombinationRule({required this.id, required this.leaveTypeIdA, required this.leaveTypeIdB, required this.allowed, this.reason});
  final String id;
  final String leaveTypeIdA;
  final String leaveTypeIdB;
  final bool allowed;
  final String? reason;

  factory LeaveCombinationRule.fromJson(Map<String, dynamic> json) => LeaveCombinationRule(
        id: json['id'] as String,
        leaveTypeIdA: json['leave_type_id_a'] as String,
        leaveTypeIdB: json['leave_type_id_b'] as String,
        allowed: json['allowed'] as bool,
        reason: json['reason'] as String?,
      );
}

class StatutoryLeaveMinimum {
  StatutoryLeaveMinimum({required this.id, this.stateCode, this.establishmentType, required this.leaveCategory, required this.minDaysPerYear, this.note});
  final String id;
  final String? stateCode;
  final String? establishmentType;
  final String leaveCategory;
  final num minDaysPerYear;
  final String? note;

  factory StatutoryLeaveMinimum.fromJson(Map<String, dynamic> json) => StatutoryLeaveMinimum(
        id: json['id'] as String,
        stateCode: json['state_code'] as String?,
        establishmentType: json['establishment_type'] as String?,
        leaveCategory: json['leave_category'] as String,
        minDaysPerYear: parseNum(json['min_days_per_year']),
        note: json['note'] as String?,
      );
}

class LeaveYearSetting {
  LeaveYearSetting({required this.leaveYearType, this.startMonth, this.startDay, required this.version});
  final String leaveYearType;
  final int? startMonth;
  final int? startDay;
  final int version;

  factory LeaveYearSetting.fromJson(Map<String, dynamic> json) => LeaveYearSetting(
        leaveYearType: json['leave_year_type'] as String,
        startMonth: json['start_month'] as int?,
        startDay: json['start_day'] as int?,
        version: json['version'] as int,
      );
}

class LeaveBalance {
  LeaveBalance({required this.employeeId, required this.leaveTypeId, required this.leaveTypeCode, required this.leaveTypeName, required this.balance, required this.reservedBalance});
  final String employeeId;
  final String leaveTypeId;
  final String leaveTypeCode;
  final String leaveTypeName;
  final num balance;
  final num reservedBalance;

  factory LeaveBalance.fromJson(Map<String, dynamic> json) => LeaveBalance(
        employeeId: json['employee_id'] as String,
        leaveTypeId: json['leave_type_id'] as String,
        leaveTypeCode: json['leave_type_code'] as String,
        leaveTypeName: json['leave_type_name'] as String,
        balance: parseNum(json['balance']),
        reservedBalance: parseNum(json['reserved_balance']),
      );
}

/// `GET /leave-ledger` — one append-only ledger row (`LeaveLedgerEntryRead`).
class LeaveLedgerEntry {
  LeaveLedgerEntry({
    required this.id,
    required this.leaveTypeId,
    required this.entryType,
    required this.amount,
    required this.effectiveDate,
    this.reason,
    required this.createdAt,
  });
  final String id;
  final String leaveTypeId;
  final String entryType;
  final num amount;
  final String effectiveDate;
  final String? reason;
  final String createdAt;

  factory LeaveLedgerEntry.fromJson(Map<String, dynamic> json) => LeaveLedgerEntry(
        id: json['id'] as String,
        leaveTypeId: json['leave_type_id'] as String,
        entryType: json['entry_type'] as String,
        amount: parseNum(json['amount']),
        effectiveDate: json['effective_date'] as String,
        reason: json['reason'] as String?,
        createdAt: json['created_at'] as String,
      );
}

class LeaveApplication {
  LeaveApplication({
    required this.id,
    required this.employeeId,
    required this.leaveTypeId,
    required this.startDate,
    required this.endDate,
    this.totalDays,
    this.reason,
    required this.status,
    this.approvalStage,
    required this.version,
    this.raw = const {},
  });
  final String id;
  final String employeeId;
  final String leaveTypeId;
  final String startDate;
  final String endDate;
  final num? totalDays;
  final String? reason;
  final String status;
  final String? approvalStage;
  final int version;

  /// The full `LeaveApplicationRead` JSON (days, action history, review/cancellation facts) for
  /// the detail screen.
  final Map<String, dynamic> raw;

  factory LeaveApplication.fromJson(Map<String, dynamic> json) => LeaveApplication(
        id: json['id'] as String,
        employeeId: json['employee_id'] as String,
        leaveTypeId: json['leave_type_id'] as String,
        startDate: json['start_date'] as String,
        endDate: json['end_date'] as String,
        totalDays: parseNumOrNull(json['total_days']),
        reason: json['reason'] as String?,
        status: json['status'] as String,
        approvalStage: json['approval_stage'] as String?,
        version: json['version'] as int,
        raw: json,
      );
}

final leaveRepositoryProvider = Provider<LeaveRepository>((ref) => LeaveRepository(ref.watch(apiClientProvider)));

/// Covers Leave Types, Combination Rules, Statutory Minimums, Year Setting,
/// Balances and Applications — mirrors
/// `apps/api/src/hrms/modules/leave/{router,schemas}.py`. Leave Policies
/// reuse the generic `PolicyRepository` (identical identity+versions shape).
class LeaveRepository {
  LeaveRepository(this._client);
  final ApiClient _client;

  Future<Map<String, dynamic>> createLeavePolicy({required String leaveTypeId, required String name, String? code}) => _client.post(
        '/leave-policies',
        body: {'leave_type_id': leaveTypeId, 'name': name, if (code != null && code.isNotEmpty) 'code': code},
        parse: (d) => d as Map<String, dynamic>,
      );

  Future<List<LeaveType>> listLeaveTypes() =>
      _client.getList('/leave-types', parseItem: (d) => LeaveType.fromJson(d as Map<String, dynamic>)).then((e) => e.data);
  Future<LeaveType> createLeaveType(Map<String, dynamic> body) => _client.post(
        '/leave-types',
        body: body,
        parse: (d) => LeaveType.fromJson(d as Map<String, dynamic>),
      );
  Future<LeaveType> updateLeaveType(String id, Map<String, dynamic> body, {required String ifMatch}) => _client.patch(
        '/leave-types/$id',
        body: body,
        ifMatch: ifMatch,
        parse: (d) => LeaveType.fromJson(d as Map<String, dynamic>),
      );

  Future<List<LeaveCombinationRule>> listCombinationRules() => _client
      .getList('/leave-combination-rules', parseItem: (d) => LeaveCombinationRule.fromJson(d as Map<String, dynamic>))
      .then((e) => e.data);
  Future<LeaveCombinationRule> createCombinationRule(Map<String, dynamic> body) => _client.post(
        '/leave-combination-rules',
        body: body,
        parse: (d) => LeaveCombinationRule.fromJson(d as Map<String, dynamic>),
      );
  Future<void> deleteCombinationRule(String id) => _client.delete('/leave-combination-rules/$id', parse: (_) {});

  Future<List<StatutoryLeaveMinimum>> listStatutoryMinimums() => _client
      .getList('/statutory-leave-minimums', parseItem: (d) => StatutoryLeaveMinimum.fromJson(d as Map<String, dynamic>))
      .then((e) => e.data);
  Future<StatutoryLeaveMinimum> createStatutoryMinimum(Map<String, dynamic> body) => _client.post(
        '/statutory-leave-minimums',
        body: body,
        parse: (d) => StatutoryLeaveMinimum.fromJson(d as Map<String, dynamic>),
      );
  Future<void> deleteStatutoryMinimum(String id) => _client.delete('/statutory-leave-minimums/$id', parse: (_) {});

  Future<LeaveYearSetting> getLeaveYearSetting() => _client.get(
        '/leave-year-setting',
        parse: (d) => LeaveYearSetting.fromJson(d as Map<String, dynamic>),
      );
  Future<LeaveYearSetting> putLeaveYearSetting(Map<String, dynamic> body) => _client.put(
        '/leave-year-setting',
        body: body,
        parse: (d) => LeaveYearSetting.fromJson(d as Map<String, dynamic>),
      );

  Future<List<LeaveBalance>> listLeaveBalances(String employeeId) => _client
      .getList('/leave-balances', filters: {'employee_id': employeeId}, parseItem: (d) => LeaveBalance.fromJson(d as Map<String, dynamic>))
      .then((e) => e.data);

  Future<ListEnvelope<LeaveLedgerEntry>> listLeaveLedger(String employeeId, {int page = 1}) => _client.getList(
        '/leave-ledger',
        query: PageQuery(page: page),
        filters: {'employee_id': employeeId},
        parseItem: (d) => LeaveLedgerEntry.fromJson(d as Map<String, dynamic>),
      );

  /// `POST /leave-ledger/encashments` (`LeaveLedgerEncashmentCreate`) — needs `LEAVE.BALANCE_ADJUST`.
  Future<void> encashLeave({
    required String employeeId,
    required String leaveTypeId,
    required String days,
    required String effectiveDate,
    required String reason,
    String? idempotencyKey,
  }) =>
      _client.post(
        '/leave-ledger/encashments',
        headers: {'Idempotency-Key': idempotencyKey ?? ApiClient.newIdempotencyKey()},
        body: {'employee_id': employeeId, 'leave_type_id': leaveTypeId, 'days': days, 'effective_date': effectiveDate, 'reason': reason},
        parse: (_) {},
      );

  /// `POST /leave-ledger/adjustments` (`LeaveLedgerAdjustmentCreate`) — signed amount.
  Future<void> adjustLeave({
    required String employeeId,
    required String leaveTypeId,
    required String amount,
    required String effectiveDate,
    required String reason,
    String? idempotencyKey,
  }) =>
      _client.post(
        '/leave-ledger/adjustments',
        headers: {'Idempotency-Key': idempotencyKey ?? ApiClient.newIdempotencyKey()},
        body: {'employee_id': employeeId, 'leave_type_id': leaveTypeId, 'amount': amount, 'effective_date': effectiveDate, 'reason': reason},
        parse: (_) {},
      );

  Future<LeaveApplication> getLeaveApplication(String id) =>
      _client.get('/leave-applications/$id', parse: (d) => LeaveApplication.fromJson(d as Map<String, dynamic>));

  /// One page of applications (`date_from`/`date_to`/`application_status`/`employee_id` are the
  /// server's filter names). The server scopes the rows to what the caller may see.
  Future<ListEnvelope<LeaveApplication>> listLeaveApplicationsPage({String? employeeId, String? dateFrom, String? dateTo, String? status, int page = 1}) => _client.getList(
        '/leave-applications',
        query: PageQuery(page: page),
        filters: {
          if (employeeId != null) 'employee_id': employeeId,
          if (dateFrom != null) 'date_from': dateFrom,
          if (dateTo != null) 'date_to': dateTo,
          if (status != null) 'application_status': status,
        },
        parseItem: (d) => LeaveApplication.fromJson(d as Map<String, dynamic>),
      );

  Future<List<LeaveApplication>> listLeaveApplications({String? employeeId}) => _client
      .getList(
        '/leave-applications',
        filters: employeeId == null ? null : {'employee_id': employeeId},
        parseItem: (d) => LeaveApplication.fromJson(d as Map<String, dynamic>),
      )
      .then((e) => e.data);
  /// Requires an `Idempotency-Key`; pass the same [idempotencyKey] when retrying after a network
  /// failure so the application is created once.
  Future<LeaveApplication> submitLeaveApplication(Map<String, dynamic> body, {String? idempotencyKey}) => _client.post(
        '/leave-applications',
        headers: {'Idempotency-Key': idempotencyKey ?? ApiClient.newIdempotencyKey()},
        body: body,
        parse: (d) => LeaveApplication.fromJson(d as Map<String, dynamic>),
      );
  /// The approver's read-only screen data; deciding stays on the approve and reject routes.
  Future<LeaveDecisionCenter> getDecisionCenter(String tab) => _client.get('/leave-applications/decision-center?tab=$tab', parse: (d) => LeaveDecisionCenter.fromJson(d as Map<String, dynamic>));

  Future<LeaveApplication> approveLeaveApplication(String id, {required String ifMatch, String? comment, bool excessAsLop = false}) =>
      _client.post(
        '/leave-applications/$id/approve',
        ifMatch: ifMatch,
        body: {if (comment != null && comment.isNotEmpty) 'reviewer_comment': comment, if (excessAsLop) 'excess_as_lop': true},
        parse: (d) => LeaveApplication.fromJson(d as Map<String, dynamic>),
      );
  Future<LeaveApplication> rejectLeaveApplication(String id, {required String ifMatch, String? comment, String? reason}) => _client.post(
        '/leave-applications/$id/reject',
        ifMatch: ifMatch,
        body: {
          if (comment != null && comment.isNotEmpty) 'reviewer_comment': comment,
          if (reason != null && reason.isNotEmpty) 'rejection_reason': reason,
        },
        parse: (d) => LeaveApplication.fromJson(d as Map<String, dynamic>),
      );
  Future<LeaveApplication> cancelLeaveApplication(String id, {required String ifMatch, String? reason}) => _client.post(
        '/leave-applications/$id/cancel',
        ifMatch: ifMatch,
        body: {if (reason != null && reason.isNotEmpty) 'reason': reason},
        parse: (d) => LeaveApplication.fromJson(d as Map<String, dynamic>),
      );
}
