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

  /// What a name search matches (mirrors web's `employeeNameSearchText`): the display name and
  /// every part of the legal name, so someone shown by a preferred name is still found by their
  /// first, middle or last name.
  String get nameSearchText =>
      [displayName, firstName, middleName, lastName].map((p) => p?.trim()).where((p) => p != null && p.isNotEmpty).join(' ');

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

  /// `POST /employees/{id}/invite` — emails the employee a login invite. [inviteUrl] is the
  /// one-time link itself, shown to HR as well because email delivery isn't set up everywhere.
  Future<({String email, bool emailSent, String? inviteUrl})> inviteEmployee(String employeeId) => _client.post(
        '/employees/$employeeId/invite',
        body: const {},
        parse: (data) {
          final m = data as Map<String, dynamic>;
          return (email: m['email'] as String, emailSent: m['email_sent'] == true, inviteUrl: m['invite_url'] as String?);
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

  /// `GET /employees/{id}/documents` — the files on the employee's record.
  Future<List<EmployeeDocumentRow>> listDocuments(String employeeId) => _client.get(
        '/employees/$employeeId/documents',
        parse: (data) => [for (final d in data as List) EmployeeDocumentRow.fromJson(d as Map<String, dynamic>)],
      );

  Future<List<Map<String, dynamic>>> _rows(String path) => _client.get(
        path,
        parse: (data) => [for (final d in data as List) d as Map<String, dynamic>],
      );

  /// The employee's current employment and assignment with every id resolved to a name; mirrors
  /// web's `useEmployeeWorkSummary`. The two employee calls must succeed (they carry the
  /// permission check); the lookup lists fall back to empty, as on web.
  Future<EmployeeWorkSummary> workSummary(String employeeId) async {
    Future<List<Map<String, dynamic>>> lookup(String path) => _rows(path).catchError((Object _) => <Map<String, dynamic>>[]);
    final results = await Future.wait([
      _rows('/employees/$employeeId/employments'),
      _rows('/employees/$employeeId/assignments'),
      lookup('/branches'),
      lookup('/departments'),
      lookup('/designations'),
      lookup('/shifts'),
      lookup('/legal-entities'),
    ]);
    final employment = results[0].where((e) => e['status'] == 'ACTIVE').firstOrNull;
    final assignment = results[1].where((a) => a['effective_to'] == null).firstOrNull;

    String? nameOf(List<Map<String, dynamic>> list, Object? id, [String key = 'name']) {
      if (id == null) return null;
      final hit = list.where((e) => e['id'] == id).firstOrNull;
      if (hit == null) return 'Unknown';
      return (hit[key] ?? hit['name'] ?? hit['title'] ?? 'Unknown') as String;
    }

    ({String id, String name})? manager;
    final managerId = assignment?['reporting_manager_id'];
    if (managerId is String) {
      try {
        final record = await getEmployee(managerId);
        manager = (id: record.id, name: record.fullName.isEmpty ? record.employeeCode : record.fullName);
      } catch (_) {
        manager = null;
      }
    }
    return EmployeeWorkSummary(
      employment: employment,
      assignment: assignment,
      company: employment == null ? null : nameOf(results[6], employment['legal_entity_id']),
      department: nameOf(results[3], assignment?['department_id']),
      designation: assignment == null ? null : (results[4].where((e) => e['id'] == assignment['designation_id']).firstOrNull?['title'] as String?),
      branch: nameOf(results[2], assignment?['branch_id']),
      shift: nameOf(results[5], assignment?['shift_id']),
      manager: manager,
    );
  }
}

/// Web's `EmployeeWorkSummary`: current employment and assignment with names resolved.
class EmployeeWorkSummary {
  const EmployeeWorkSummary({this.employment, this.assignment, this.company, this.department, this.designation, this.branch, this.shift, this.manager});
  final Map<String, dynamic>? employment;
  final Map<String, dynamic>? assignment;
  final String? company;
  final String? department;
  final String? designation;
  final String? branch;
  final String? shift;
  final ({String id, String name})? manager;

  String? get workLocationType => assignment?['work_location_type'] as String?;
  String? get joiningDate => employment?['joining_date'] as String?;
  String? get probationEndDate => employment?['probation_end_date'] as String?;
  String? get payBasis => employment?['pay_basis'] as String?;
}

/// `EmployeeDocumentRead` — only what the Overview's documents card shows.
class EmployeeDocumentRow {
  const EmployeeDocumentRow({required this.id, required this.documentType, required this.originalFilename, required this.status});
  final String id;
  final String documentType;
  final String originalFilename;
  final String status;

  factory EmployeeDocumentRow.fromJson(Map<String, dynamic> json) => EmployeeDocumentRow(
        id: json['id'] as String,
        documentType: (json['document_type'] as String?) ?? '',
        originalFilename: (json['original_filename'] as String?) ?? '',
        status: (json['status'] as String?) ?? 'PENDING',
      );
}
