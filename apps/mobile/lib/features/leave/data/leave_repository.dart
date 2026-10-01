import '../../../core/api/api_client.dart';

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
        minDaysPerYear: json['min_days_per_year'] as num,
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
  LeaveBalance({required this.employeeId, required this.leaveTypeCode, required this.leaveTypeName, required this.balance, required this.reservedBalance});
  final String employeeId;
  final String leaveTypeCode;
  final String leaveTypeName;
  final num balance;
  final num reservedBalance;

  factory LeaveBalance.fromJson(Map<String, dynamic> json) => LeaveBalance(
        employeeId: json['employee_id'] as String,
        leaveTypeCode: json['leave_type_code'] as String,
        leaveTypeName: json['leave_type_name'] as String,
        balance: json['balance'] as num,
        reservedBalance: json['reserved_balance'] as num,
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

  factory LeaveApplication.fromJson(Map<String, dynamic> json) => LeaveApplication(
        id: json['id'] as String,
        employeeId: json['employee_id'] as String,
        leaveTypeId: json['leave_type_id'] as String,
        startDate: json['start_date'] as String,
        endDate: json['end_date'] as String,
        totalDays: json['total_days'] as num?,
        reason: json['reason'] as String?,
        status: json['status'] as String,
        approvalStage: json['approval_stage'] as String?,
        version: json['version'] as int,
      );
}

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

  Future<List<LeaveApplication>> listLeaveApplications({String? employeeId}) => _client
      .getList(
        '/leave-applications',
        filters: employeeId == null ? null : {'employee_id': employeeId},
        parseItem: (d) => LeaveApplication.fromJson(d as Map<String, dynamic>),
      )
      .then((e) => e.data);
  Future<LeaveApplication> submitLeaveApplication(Map<String, dynamic> body) => _client.post(
        '/leave-applications',
        body: body,
        parse: (d) => LeaveApplication.fromJson(d as Map<String, dynamic>),
      );
  Future<LeaveApplication> approveLeaveApplication(String id, {required String ifMatch, String? comment, bool excessAsLop = false}) =>
      _client.post(
        '/leave-applications/$id/approve',
        body: {if (comment != null && comment.isNotEmpty) 'reviewer_comment': comment, 'excess_as_lop': excessAsLop},
        parse: (d) => LeaveApplication.fromJson(d as Map<String, dynamic>),
      );
  Future<LeaveApplication> rejectLeaveApplication(String id, {required String ifMatch, String? reason}) => _client.post(
        '/leave-applications/$id/reject',
        body: {if (reason != null && reason.isNotEmpty) 'rejection_reason': reason},
        parse: (d) => LeaveApplication.fromJson(d as Map<String, dynamic>),
      );
  Future<LeaveApplication> cancelLeaveApplication(String id, {required String ifMatch, String? reason}) => _client.post(
        '/leave-applications/$id/cancel',
        body: {if (reason != null && reason.isNotEmpty) 'reason': reason},
        parse: (d) => LeaveApplication.fromJson(d as Map<String, dynamic>),
      );
}
