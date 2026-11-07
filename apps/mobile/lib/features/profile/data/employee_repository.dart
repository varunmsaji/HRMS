import '../../../core/api/api_client.dart';
import '../../employees/domain/employee_directory.dart';

/// `GET /employees/{id}` — mirrors `EmployeeRead` (employee/schemas.py). Only
/// the personal-record fields the mobile "My Profile" screen shows; the web
/// `/app/me` page's Employment/Assignment/Compensation/Statutory/Banking tabs
/// (separate join-heavy endpoints) aren't ported yet.
class Employee {
  Employee({
    required this.id,
    required this.employeeCode,
    required this.firstName,
    this.middleName,
    this.lastName,
    this.displayName,
    this.dateOfBirth,
    this.gender,
    this.bloodGroup,
    this.maritalStatus,
    this.nationality,
    this.personalEmail,
    this.personalMobile,
    this.presentAddressLine1,
    this.presentAddressLine2,
    this.presentCity,
    this.presentStateCode,
    this.presentPincode,
    this.presentCountryCode,
    this.emergencyContactName,
    this.emergencyContactRelationship,
    this.emergencyContactPhone,
    required this.status,
    required this.isActive,
    required this.version,
    required this.raw,
  });

  final String id;
  final String employeeCode;
  final String firstName;
  final String? middleName;
  final String? lastName;
  final String? displayName;
  final String? dateOfBirth;
  final String? gender;
  final String? bloodGroup;
  final String? maritalStatus;
  final String? nationality;
  final String? personalEmail;
  final String? personalMobile;
  final String? presentAddressLine1;
  final String? presentAddressLine2;
  final String? presentCity;
  final String? presentStateCode;
  final String? presentPincode;
  final String? presentCountryCode;
  final String? emergencyContactName;
  final String? emergencyContactRelationship;
  final String? emergencyContactPhone;
  final String status;
  final bool isActive;
  final int version;

  /// The wire JSON, so edit forms can diff against exactly what the server sent.
  final Map<String, dynamic> raw;

  /// Mirrors `employee-overview.tsx`'s name resolution:
  /// `display_name?.trim() || [first, middle, last].filter(Boolean).join(' ')`.
  String get fullName {
    if (displayName != null && displayName!.trim().isNotEmpty) return displayName!.trim();
    return [firstName, middleName, lastName].where((p) => p != null && p.trim().isNotEmpty).join(' ');
  }

  factory Employee.fromJson(Map<String, dynamic> json) => Employee(
        id: json['id'] as String,
        employeeCode: json['employee_code'] as String,
        firstName: json['first_name'] as String,
        middleName: json['middle_name'] as String?,
        lastName: json['last_name'] as String?,
        displayName: json['display_name'] as String?,
        dateOfBirth: json['date_of_birth'] as String?,
        gender: json['gender'] as String?,
        bloodGroup: json['blood_group'] as String?,
        maritalStatus: json['marital_status'] as String?,
        nationality: json['nationality'] as String?,
        personalEmail: json['personal_email'] as String?,
        personalMobile: json['personal_mobile'] as String?,
        presentAddressLine1: json['present_address_line1'] as String?,
        presentAddressLine2: json['present_address_line2'] as String?,
        presentCity: json['present_city'] as String?,
        presentStateCode: json['present_state_code'] as String?,
        presentPincode: json['present_pincode'] as String?,
        presentCountryCode: json['present_country_code'] as String?,
        emergencyContactName: json['emergency_contact_name'] as String?,
        emergencyContactRelationship: json['emergency_contact_relationship'] as String?,
        emergencyContactPhone: json['emergency_contact_phone'] as String?,
        status: json['status'] as String,
        isActive: json['is_active'] as bool,
        version: json['version'] as int,
        raw: json,
      );
}

class EmployeeRepository {
  EmployeeRepository(this._client);

  final ApiClient _client;

  Future<Employee> getEmployee(String employeeId) => _client.get(
        '/employees/$employeeId',
        parse: (data) => Employee.fromJson(data as Map<String, dynamic>),
      );

  Future<Employee> updateEmployee(String employeeId, Map<String, dynamic> changes, {required int version}) => _client.patch(
        '/employees/$employeeId',
        body: changes,
        ifMatch: version.toString(),
        parse: (data) => Employee.fromJson(data as Map<String, dynamic>),
      );

  /// `DELETE /employees/{id}` deactivates (soft) — reactivation is `PATCH {is_active: true}`.
  Future<Employee> deactivateEmployee(String employeeId, {required int version}) => _client.delete(
        '/employees/$employeeId',
        ifMatch: version.toString(),
        parse: (data) => Employee.fromJson(data as Map<String, dynamic>),
      );

  Future<Employee> confirmEmployee(String employeeId, {required int version}) => _client.post(
        '/employees/$employeeId/confirm',
        body: const {},
        ifMatch: version.toString(),
        parse: (data) => Employee.fromJson(data as Map<String, dynamic>),
      );

  /// `POST /employees/{id}/invite` — emails the employee a login invite.
  Future<({String email, bool emailSent})> inviteEmployee(String employeeId) => _client.post(
        '/employees/$employeeId/invite',
        body: const {},
        parse: (data) {
          final m = data as Map<String, dynamic>;
          return (email: m['email'] as String, emailSent: m['email_sent'] == true);
        },
      );

  /// One page of the directory. [search] is matched on the server (name, code, email, mobile) before
  /// paging, so it reaches every employee, not only the ones already loaded.
  Future<({List<Employee> rows, bool hasNext})> listEmployeesPage({String? search, int page = 1, int perPage = 50}) async {
    final q = search?.trim();
    final env = await _client.getList<Employee>(
      '/employees',
      query: PageQuery(page: page, perPage: perPage),
      filters: {if (q != null && q.isNotEmpty) 'q': q},
      parseItem: (d) => Employee.fromJson(d as Map<String, dynamic>),
    );
    return (rows: env.data, hasNext: env.pagination?.hasNext ?? false);
  }

  /// Headline counts over every employee the caller may see (`EMPLOYEE.VIEW_ALL`).
  Future<DirectorySummary> directorySummary() =>
      _client.get('/employees/directory/summary', parse: (d) => DirectorySummary.fromJson(d as Map<String, dynamic>));

  /// Job title, department, manager and shift for [ids], keyed by employee id. Sent in batches of
  /// [directoryRowsChunk] (the endpoint's limit), never one request per employee.
  Future<Map<String, DirectoryRow>> directoryRows(List<String> ids) async {
    final chunks = [for (var i = 0; i < ids.length; i += directoryRowsChunk) ids.sublist(i, (i + directoryRowsChunk).clamp(0, ids.length))];
    final pages = await Future.wait([
      for (final chunk in chunks)
        _client.get<List<DirectoryRow>>(
          '/employees/directory/rows?${chunk.map((id) => 'ids=${Uri.encodeQueryComponent(id)}').join('&')}',
          parse: (d) => [for (final r in (d as List)) DirectoryRow.fromJson(r as Map<String, dynamic>)],
        ),
    ]);
    return {for (final rows in pages) for (final r in rows) r.employeeId: r};
  }

  Future<List<Employee>> listEmployees() =>
      _client.getList('/employees', parseItem: (d) => Employee.fromJson(d as Map<String, dynamic>)).then((e) => e.data);

  Future<Employee> createEmployee(Map<String, dynamic> body) => _client.post(
        '/employees',
        body: body,
        parse: (data) => Employee.fromJson(data as Map<String, dynamic>),
      );
}
