import '../../../core/api/api_client.dart';

class PayRun {
  PayRun({
    required this.id,
    required this.legalEntityId,
    required this.month,
    required this.status,
    this.payDate,
    this.periodStart,
    this.periodEnd,
    this.attendancePeriodId,
    this.varianceThresholdPercent,
    this.employeeCount,
    this.grossMinor,
    this.deductionsMinor,
    this.employerContributionsMinor,
    this.netMinor,
    this.errorCount = 0,
    this.warningCount = 0,
    this.varianceFlagCount = 0,
    this.varianceOpenCount = 0,
    this.lastRollbackReason,
    required this.version,
  });
  final String id;
  final String legalEntityId;
  final String month;
  final String status;
  final String? payDate;
  final String? periodStart;
  final String? periodEnd;
  final String? attendancePeriodId;
  final String? varianceThresholdPercent;
  final int? employeeCount;
  final int? grossMinor;
  final int? deductionsMinor;
  final int? employerContributionsMinor;
  final int? netMinor;
  final int errorCount;
  final int warningCount;
  final int varianceFlagCount;
  final int varianceOpenCount;
  final String? lastRollbackReason;
  final int version;

  /// Mirrors `payRunActions` in `apps/web/src/lib/payroll/types.ts` — the backend still decides.
  bool get canLockInputs => status == 'DRAFT';
  bool get canCompute => status == 'INPUTS_LOCKED' || status == 'COMPUTED';
  bool get canApprove => status == 'COMPUTED';
  bool get canFinalise => status == 'APPROVED';
  bool get canMarkPaid => status == 'FINALISED';
  bool get canEditPayDate => status != 'FINALISED' && status != 'PAID';
  bool get canDelete => status == 'DRAFT';
  List<String> get rollbackTargets => (status == 'COMPUTED' || status == 'APPROVED')
      ? const ['INPUTS_LOCKED', 'DRAFT']
      : status == 'INPUTS_LOCKED'
          ? const ['DRAFT']
          : const [];
  bool get isComputed => status != 'DRAFT' && status != 'INPUTS_LOCKED';
  bool get isClosed => status == 'FINALISED' || status == 'PAID';

  factory PayRun.fromJson(Map<String, dynamic> json) => PayRun(
        id: json['id'] as String,
        legalEntityId: json['legal_entity_id'] as String,
        month: json['month'] as String,
        status: json['status'] as String,
        payDate: json['pay_date'] as String?,
        periodStart: json['period_start'] as String?,
        periodEnd: json['period_end'] as String?,
        attendancePeriodId: json['attendance_period_id'] as String?,
        varianceThresholdPercent: json['variance_threshold_percent']?.toString(),
        employeeCount: json['employee_count'] as int?,
        grossMinor: json['gross_minor'] as int?,
        deductionsMinor: json['deductions_minor'] as int?,
        employerContributionsMinor: json['employer_contributions_minor'] as int?,
        netMinor: json['net_minor'] as int?,
        errorCount: (json['error_count'] as int?) ?? 0,
        warningCount: (json['warning_count'] as int?) ?? 0,
        varianceFlagCount: (json['variance_flag_count'] as int?) ?? 0,
        varianceOpenCount: (json['variance_open_count'] as int?) ?? 0,
        lastRollbackReason: json['last_rollback_reason'] as String?,
        version: json['version'] as int,
      );
}

class PayRunIssue {
  PayRunIssue({required this.code, required this.severity, required this.message});
  final String code;
  final String severity;
  final String message;
  bool get isError => severity == 'ERROR';

  factory PayRunIssue.fromJson(Map<String, dynamic> json) => PayRunIssue(
        code: json['code'] as String,
        severity: json['severity'] as String,
        message: json['message'] as String,
      );
}

class PayRunEmployee {
  PayRunEmployee({
    required this.id,
    required this.employeeId,
    this.employeeCode,
    this.employeeName,
    this.payBasis,
    this.paidDays,
    this.lopDays,
    this.payableDays,
    this.netMinor,
    this.grossMinor,
    this.previousNetMinor,
    this.variancePercent,
    this.varianceFlagged = false,
    this.varianceReason,
    this.issues = const [],
    required this.hasError,
    required this.isComputed,
  });
  final String id;
  final String employeeId;
  final String? employeeCode;
  final String? employeeName;
  final String? payBasis;
  final String? paidDays;
  final String? lopDays;
  final String? payableDays;
  final int? netMinor;
  final int? grossMinor;
  final int? previousNetMinor;
  final String? variancePercent;
  final bool varianceFlagged;
  final String? varianceReason;
  final List<PayRunIssue> issues;
  final bool hasError;
  final bool isComputed;

  String get displayName => (employeeName == null || employeeName!.isEmpty) ? (employeeCode ?? 'Employee') : employeeName!;

  factory PayRunEmployee.fromJson(Map<String, dynamic> json) => PayRunEmployee(
        id: json['id'] as String,
        employeeId: json['employee_id'] as String,
        employeeCode: json['employee_code'] as String?,
        employeeName: json['employee_name'] as String?,
        payBasis: json['pay_basis'] as String?,
        paidDays: json['paid_days']?.toString(),
        lopDays: json['lop_days']?.toString(),
        payableDays: json['payable_days']?.toString(),
        netMinor: json['net_minor'] as int?,
        grossMinor: json['gross_minor'] as int?,
        previousNetMinor: json['previous_net_minor'] as int?,
        variancePercent: json['variance_percent']?.toString(),
        varianceFlagged: (json['variance_flagged'] as bool?) ?? false,
        varianceReason: json['variance_reason'] as String?,
        issues: ((json['issues'] as List?) ?? const []).map((e) => PayRunIssue.fromJson(e as Map<String, dynamic>)).toList(),
        hasError: json['has_error'] as bool,
        isComputed: json['is_computed'] as bool,
      );
}

class PayRunLine {
  PayRunLine({required this.componentCode, required this.componentName, required this.lineType, this.fullMonthlyMinor, required this.amountMinor, this.formula});
  final String componentCode;
  final String componentName;
  final String lineType; // EARNING | DEDUCTION | EMPLOYER_CONTRIBUTION | ROUNDING
  final int? fullMonthlyMinor;
  final int amountMinor;
  final String? formula;

  factory PayRunLine.fromJson(Map<String, dynamic> json) => PayRunLine(
        componentCode: json['component_code'] as String,
        componentName: json['component_name'] as String,
        lineType: json['line_type'] as String,
        fullMonthlyMinor: json['full_monthly_minor'] as int?,
        amountMinor: json['amount_minor'] as int,
        formula: (json['trace'] is Map) ? (json['trace'] as Map)['formula'] as String? : null,
      );
}

/// `GET /payroll/pay-runs/{id}/employees/{employee_id}` — the summary plus every pay line.
class PayRunEmployeeDetail {
  PayRunEmployeeDetail({required this.employee, required this.lines});
  final PayRunEmployee employee;
  final List<PayRunLine> lines;

  factory PayRunEmployeeDetail.fromJson(Map<String, dynamic> json) => PayRunEmployeeDetail(
        employee: PayRunEmployee.fromJson(json),
        lines: ((json['lines'] as List?) ?? const []).map((e) => PayRunLine.fromJson(e as Map<String, dynamic>)).toList(),
      );
}

class PayslipLine {
  PayslipLine({required this.componentCode, required this.componentName, this.fullMonthlyMinor, required this.amountMinor, this.note});
  final String componentCode;
  final String componentName;
  final int? fullMonthlyMinor;
  final int amountMinor;
  final String? note;

  factory PayslipLine.fromJson(Map<String, dynamic> json) => PayslipLine(
        componentCode: json['component_code'] as String,
        componentName: json['component_name'] as String,
        fullMonthlyMinor: json['full_monthly_minor'] as int?,
        amountMinor: json['amount_minor'] as int,
        note: json['note'] as String?,
      );
}

/// `GET /payroll/pay-runs/{id}/employees/{eid}/payslip` and `/me/payslips/{run_id}`.
class Payslip {
  Payslip({
    required this.month,
    required this.periodEnd,
    required this.payDate,
    required this.isFinal,
    this.companyName,
    this.legalEntityName,
    this.legalEntityAddress,
    this.employeeName,
    this.employeeCode,
    this.designation,
    this.department,
    this.dateOfJoining,
    this.panMasked,
    this.uanNumber,
    this.esiIpNumber,
    this.paymentMode,
    this.bankName,
    this.accountLast4,
    required this.daysInMonth,
    this.paidDays,
    this.lopDays,
    required this.earnings,
    required this.deductions,
    required this.employerContributions,
    required this.grossMinor,
    required this.deductionsMinor,
    required this.netMinor,
    required this.netInWords,
    required this.leaveBalances,
  });
  final String month;
  final String periodEnd;
  final String payDate;
  final bool isFinal;
  final String? companyName;
  final String? legalEntityName;
  final String? legalEntityAddress;
  final String? employeeName;
  final String? employeeCode;
  final String? designation;
  final String? department;
  final String? dateOfJoining;
  final String? panMasked;
  final String? uanNumber;
  final String? esiIpNumber;
  final String? paymentMode;
  final String? bankName;
  final String? accountLast4;
  final int daysInMonth;
  final String? paidDays;
  final String? lopDays;
  final List<PayslipLine> earnings;
  final List<PayslipLine> deductions;
  final List<PayslipLine> employerContributions;
  final int grossMinor;
  final int deductionsMinor;
  final int netMinor;
  final String netInWords;
  final List<({String name, String balance})> leaveBalances;

  factory Payslip.fromJson(Map<String, dynamic> json) {
    List<PayslipLine> lines(String key) =>
        ((json[key] as List?) ?? const []).map((e) => PayslipLine.fromJson(e as Map<String, dynamic>)).toList();
    return Payslip(
      month: json['month'] as String,
      periodEnd: json['period_end'] as String,
      payDate: json['pay_date'] as String,
      isFinal: json['is_final'] as bool,
      companyName: json['company_name'] as String?,
      legalEntityName: json['legal_entity_name'] as String?,
      legalEntityAddress: json['legal_entity_address'] as String?,
      employeeName: json['employee_name'] as String?,
      employeeCode: json['employee_code'] as String?,
      designation: json['designation'] as String?,
      department: json['department'] as String?,
      dateOfJoining: json['date_of_joining'] as String?,
      panMasked: json['pan_masked'] as String?,
      uanNumber: json['uan_number'] as String?,
      esiIpNumber: json['esi_ip_number'] as String?,
      paymentMode: json['payment_mode'] as String?,
      bankName: json['bank_name'] as String?,
      accountLast4: json['account_last4'] as String?,
      daysInMonth: json['days_in_month'] as int,
      paidDays: json['paid_days']?.toString(),
      lopDays: json['lop_days']?.toString(),
      earnings: lines('earnings'),
      deductions: lines('deductions'),
      employerContributions: lines('employer_contributions'),
      grossMinor: json['gross_minor'] as int,
      deductionsMinor: json['deductions_minor'] as int,
      netMinor: json['net_minor'] as int,
      netInWords: (json['net_in_words'] as String?) ?? '',
      leaveBalances: ((json['leave_balances'] as List?) ?? const [])
          .map((e) => (name: (e as Map)['name'] as String, balance: e['balance'].toString()))
          .toList(),
    );
  }
}

/// `GET /payroll/adjustments` — a paid-days correction against a finalised month (D7).
class PayAdjustment {
  PayAdjustment({required this.id, required this.employeeId, required this.month, required this.paidDaysDelta, required this.reason, required this.status, required this.version});
  final String id;
  final String employeeId;
  final String month;
  final String paidDaysDelta;
  final String reason;
  final String status; // PENDING | APPLIED
  final int version;

  factory PayAdjustment.fromJson(Map<String, dynamic> json) => PayAdjustment(
        id: json['id'] as String,
        employeeId: json['employee_id'] as String,
        month: json['month'] as String,
        paidDaysDelta: json['paid_days_delta'].toString(),
        reason: json['reason'] as String,
        status: json['status'] as String,
        version: json['version'] as int,
      );
}

class PayrollSetting {
  PayrollSetting({required this.varianceThresholdPercent, required this.version});
  final String varianceThresholdPercent;
  final int version;

  factory PayrollSetting.fromJson(Map<String, dynamic> json) => PayrollSetting(
        varianceThresholdPercent: json['variance_threshold_percent'].toString(),
        version: json['version'] as int,
      );
}

class SalaryComponent {
  SalaryComponent({required this.id, required this.code, required this.name, required this.componentType, required this.isActive, required this.version});
  final String id;
  final String code;
  final String name;
  final String componentType;
  final bool isActive;
  final int version;

  factory SalaryComponent.fromJson(Map<String, dynamic> json) => SalaryComponent(
        id: json['id'] as String,
        code: json['code'] as String,
        name: json['name'] as String,
        componentType: json['component_type'] as String,
        isActive: json['is_active'] as bool,
        version: json['version'] as int,
      );
}

class SalaryStructure {
  SalaryStructure({required this.id, required this.code, required this.name, this.description, required this.isActive, required this.version});
  final String id;
  final String code;
  final String name;
  final String? description;
  final bool isActive;
  final int version;

  factory SalaryStructure.fromJson(Map<String, dynamic> json) => SalaryStructure(
        id: json['id'] as String,
        code: json['code'] as String,
        name: json['name'] as String,
        description: json['description'] as String?,
        isActive: json['is_active'] as bool,
        version: json['version'] as int,
      );
}

class StatutoryRate {
  StatutoryRate({required this.id, required this.scheme, this.stateCode, required this.effectiveFrom, this.effectiveTo, required this.verified, required this.parameters, required this.version});
  final String id;
  final String scheme;
  final String? stateCode;
  final String effectiveFrom;
  final String? effectiveTo;
  final bool verified;
  final Map<String, dynamic> parameters;
  final int version;

  factory StatutoryRate.fromJson(Map<String, dynamic> json) => StatutoryRate(
        id: json['id'] as String,
        scheme: json['scheme'] as String,
        stateCode: json['state_code'] as String?,
        effectiveFrom: json['effective_from'] as String,
        effectiveTo: json['effective_to'] as String?,
        verified: json['verified'] as bool,
        parameters: json['parameters'] as Map<String, dynamic>,
        version: json['version'] as int,
      );
}

class PayslipSummary {
  PayslipSummary({required this.payRunId, required this.month, this.payDate, required this.netMinor, required this.status});
  final String payRunId;
  final String month;
  final String? payDate;
  final int netMinor;
  final String status;

  factory PayslipSummary.fromJson(Map<String, dynamic> json) => PayslipSummary(
        payRunId: json['pay_run_id'] as String,
        month: json['month'] as String,
        payDate: json['pay_date'] as String?,
        netMinor: json['net_minor'] as int,
        status: json['status'] as String,
      );
}

/// Mirrors `apps/api/src/hrms/modules/payroll/{router,schemas}.py`. Payroll
/// list endpoints don't paginate either (same as most attendance/leave/org
/// config endpoints).
class PayrollRepository {
  PayrollRepository(this._client);
  final ApiClient _client;

  Future<List<PayRun>> listPayRuns() =>
      _client.getList('/payroll/pay-runs', parseItem: (d) => PayRun.fromJson(d as Map<String, dynamic>)).then((e) => e.data);
  Future<PayRun> createPayRun(Map<String, dynamic> body) => _client.post(
        '/payroll/pay-runs',
        body: body,
        parse: (d) => PayRun.fromJson(d as Map<String, dynamic>),
      );
  Future<List<PayRunEmployee>> listPayRunEmployees(String runId) => _client
      .getList('/payroll/pay-runs/$runId/employees', parseItem: (d) => PayRunEmployee.fromJson(d as Map<String, dynamic>))
      .then((e) => e.data);
  Future<PayRun> getPayRun(String runId) => _client.get('/payroll/pay-runs/$runId', parse: (d) => PayRun.fromJson(d as Map<String, dynamic>));
  Future<PayRunEmployeeDetail> getPayRunEmployee(String runId, String employeeId) => _client.get(
        '/payroll/pay-runs/$runId/employees/$employeeId',
        parse: (d) => PayRunEmployeeDetail.fromJson(d as Map<String, dynamic>),
      );
  Future<Payslip> getPayRunPayslip(String runId, String employeeId) => _client.get(
        '/payroll/pay-runs/$runId/employees/$employeeId/payslip',
        parse: (d) => Payslip.fromJson(d as Map<String, dynamic>),
      );
  Future<PayRun> updatePayDate(String runId, {required String payDate, required String ifMatch}) => _client.patch(
        '/payroll/pay-runs/$runId',
        body: {'pay_date': payDate},
        ifMatch: ifMatch,
        parse: (d) => PayRun.fromJson(d as Map<String, dynamic>),
      );
  Future<PayRun> rollback(String runId, {required String toStatus, required String reason, required String ifMatch}) => _client.post(
        '/payroll/pay-runs/$runId/rollback',
        body: {'to_status': toStatus, 'reason': reason},
        ifMatch: ifMatch,
        parse: (d) => PayRun.fromJson(d as Map<String, dynamic>),
      );
  Future<void> deletePayRun(String runId) => _client.delete('/payroll/pay-runs/$runId', parse: (_) {});
  Future<PayRunEmployee> acknowledgeVariance(String runId, String employeeId, {required String reason}) => _client.post(
        '/payroll/pay-runs/$runId/employees/$employeeId/acknowledge-variance',
        body: {'reason': reason},
        parse: (d) => PayRunEmployee.fromJson(d as Map<String, dynamic>),
      );
  /// FR-PAY-018 — built on demand, never stored; the server audits each download.
  Future<DownloadedFile> downloadBankAdvice(String runId) => _client.download('/payroll/pay-runs/$runId/bank-advice');

  Future<List<PayAdjustment>> listAdjustments({required String sourcePayRunId}) => _client
      .getList('/payroll/adjustments', filters: {'source_pay_run_id': sourcePayRunId}, parseItem: (d) => PayAdjustment.fromJson(d as Map<String, dynamic>))
      .then((e) => e.data);
  /// Requires an `Idempotency-Key`; pass the same [idempotencyKey] when retrying after a network
  /// failure so the correction is recorded once.
  Future<PayAdjustment> createAdjustment({required String sourcePayRunId, required String employeeId, required String paidDaysDelta, required String reason, String? idempotencyKey}) =>
      _client.post(
        '/payroll/adjustments',
        headers: {'Idempotency-Key': idempotencyKey ?? ApiClient.newIdempotencyKey()},
        body: {'source_pay_run_id': sourcePayRunId, 'employee_id': employeeId, 'paid_days_delta': paidDaysDelta, 'reason': reason},
        parse: (d) => PayAdjustment.fromJson(d as Map<String, dynamic>),
      );
  Future<void> deleteAdjustment(String id) => _client.delete('/payroll/adjustments/$id', parse: (_) {});

  Future<PayrollSetting> getSettings() => _client.get('/payroll/settings', parse: (d) => PayrollSetting.fromJson(d as Map<String, dynamic>));
  Future<PayrollSetting> updateSettings({required String varianceThresholdPercent, required int ifMatch}) => _client.put(
        '/payroll/settings',
        body: {'variance_threshold_percent': varianceThresholdPercent},
        ifMatch: ifMatch.toString(),
        parse: (d) => PayrollSetting.fromJson(d as Map<String, dynamic>),
      );

  Future<PayRun> lockInputs(String runId, {required String ifMatch}) => _client.post(
        '/payroll/pay-runs/$runId/lock-inputs',
        ifMatch: ifMatch,
        parse: (d) => PayRun.fromJson(d as Map<String, dynamic>),
      );
  Future<PayRun> compute(String runId, {required String ifMatch}) => _client.post(
        '/payroll/pay-runs/$runId/compute',
        ifMatch: ifMatch,
        parse: (d) => PayRun.fromJson(d as Map<String, dynamic>),
      );
  Future<PayRun> approve(String runId, {required String ifMatch}) => _client.post(
        '/payroll/pay-runs/$runId/approve',
        ifMatch: ifMatch,
        parse: (d) => PayRun.fromJson(d as Map<String, dynamic>),
      );
  Future<PayRun> finalise(String runId, {required String ifMatch}) => _client.post(
        '/payroll/pay-runs/$runId/finalise',
        ifMatch: ifMatch,
        parse: (d) => PayRun.fromJson(d as Map<String, dynamic>),
      );
  Future<PayRun> markPaid(String runId, {required String ifMatch}) => _client.post(
        '/payroll/pay-runs/$runId/mark-paid',
        ifMatch: ifMatch,
        parse: (d) => PayRun.fromJson(d as Map<String, dynamic>),
      );

  Future<List<SalaryComponent>> listSalaryComponents() => _client
      .getList('/payroll/salary-components', parseItem: (d) => SalaryComponent.fromJson(d as Map<String, dynamic>))
      .then((e) => e.data);
  Future<SalaryComponent> createSalaryComponent(Map<String, dynamic> body) => _client.post(
        '/payroll/salary-components',
        body: body,
        parse: (d) => SalaryComponent.fromJson(d as Map<String, dynamic>),
      );

  Future<List<SalaryStructure>> listSalaryStructures() => _client
      .getList('/payroll/salary-structures', parseItem: (d) => SalaryStructure.fromJson(d as Map<String, dynamic>))
      .then((e) => e.data);
  Future<SalaryStructure> createSalaryStructure(Map<String, dynamic> body) => _client.post(
        '/payroll/salary-structures',
        body: body,
        parse: (d) => SalaryStructure.fromJson(d as Map<String, dynamic>),
      );

  Future<List<StatutoryRate>> listStatutoryRates() => _client
      .getList('/payroll/statutory-rates', parseItem: (d) => StatutoryRate.fromJson(d as Map<String, dynamic>))
      .then((e) => e.data);
  Future<StatutoryRate> createStatutoryRate(Map<String, dynamic> body) => _client.post(
        '/payroll/statutory-rates',
        body: body,
        parse: (d) => StatutoryRate.fromJson(d as Map<String, dynamic>),
      );
  Future<StatutoryRate> verifyStatutoryRate(String id, {required String ifMatch}) => _client.post(
        '/payroll/statutory-rates/$id/verify',
        ifMatch: ifMatch,
        parse: (d) => StatutoryRate.fromJson(d as Map<String, dynamic>),
      );

  Future<List<PayslipSummary>> listMyPayslips() =>
      _client.getList('/me/payslips', parseItem: (d) => PayslipSummary.fromJson(d as Map<String, dynamic>)).then((e) => e.data);
  Future<Payslip> getMyPayslip(String runId) => _client.get('/me/payslips/$runId', parse: (d) => Payslip.fromJson(d as Map<String, dynamic>));
}
