import '../../../core/api/api_client.dart';

class PayRun {
  PayRun({
    required this.id,
    required this.legalEntityId,
    required this.month,
    required this.status,
    this.payDate,
    this.employeeCount,
    this.grossMinor,
    this.netMinor,
    required this.version,
  });
  final String id;
  final String legalEntityId;
  final String month;
  final String status;
  final String? payDate;
  final int? employeeCount;
  final int? grossMinor;
  final int? netMinor;
  final int version;

  factory PayRun.fromJson(Map<String, dynamic> json) => PayRun(
        id: json['id'] as String,
        legalEntityId: json['legal_entity_id'] as String,
        month: json['month'] as String,
        status: json['status'] as String,
        payDate: json['pay_date'] as String?,
        employeeCount: json['employee_count'] as int?,
        grossMinor: json['gross_minor'] as int?,
        netMinor: json['net_minor'] as int?,
        version: json['version'] as int,
      );
}

class PayRunEmployee {
  PayRunEmployee({required this.id, required this.employeeId, required this.employeeName, this.netMinor, required this.hasError, required this.isComputed});
  final String id;
  final String employeeId;
  final String employeeName;
  final int? netMinor;
  final bool hasError;
  final bool isComputed;

  factory PayRunEmployee.fromJson(Map<String, dynamic> json) => PayRunEmployee(
        id: json['id'] as String,
        employeeId: json['employee_id'] as String,
        employeeName: json['employee_name'] as String,
        netMinor: json['net_minor'] as int?,
        hasError: json['has_error'] as bool,
        isComputed: json['is_computed'] as bool,
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
  Future<PayRun> lockInputs(String runId, {required String ifMatch}) => _client.post(
        '/payroll/pay-runs/$runId/lock-inputs',
        parse: (d) => PayRun.fromJson(d as Map<String, dynamic>),
      );
  Future<PayRun> compute(String runId, {required String ifMatch}) => _client.post(
        '/payroll/pay-runs/$runId/compute',
        parse: (d) => PayRun.fromJson(d as Map<String, dynamic>),
      );
  Future<PayRun> approve(String runId, {required String ifMatch}) => _client.post(
        '/payroll/pay-runs/$runId/approve',
        parse: (d) => PayRun.fromJson(d as Map<String, dynamic>),
      );
  Future<PayRun> finalise(String runId, {required String ifMatch}) => _client.post(
        '/payroll/pay-runs/$runId/finalise',
        parse: (d) => PayRun.fromJson(d as Map<String, dynamic>),
      );
  Future<PayRun> markPaid(String runId, {required String ifMatch}) => _client.post(
        '/payroll/pay-runs/$runId/mark-paid',
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
        parse: (d) => StatutoryRate.fromJson(d as Map<String, dynamic>),
      );

  Future<List<PayslipSummary>> listMyPayslips() =>
      _client.getList('/me/payslips', parseItem: (d) => PayslipSummary.fromJson(d as Map<String, dynamic>)).then((e) => e.data);
  Future<Map<String, dynamic>> getMyPayslip(String runId) => _client.get('/me/payslips/$runId', parse: (d) => d as Map<String, dynamic>);
}
