import '../../../core/api/api_client.dart';

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
      );
}

class EmployeeRepository {
  EmployeeRepository(this._client);

  final ApiClient _client;

  Future<Employee> getEmployee(String employeeId) => _client.get(
        '/employees/$employeeId',
        parse: (data) => Employee.fromJson(data as Map<String, dynamic>),
      );

  Future<List<Employee>> listEmployees() =>
      _client.getList('/employees', parseItem: (d) => Employee.fromJson(d as Map<String, dynamic>)).then((e) => e.data);

  Future<Employee> createEmployee(Map<String, dynamic> body) => _client.post(
        '/employees',
        body: body,
        parse: (data) => Employee.fromJson(data as Map<String, dynamic>),
      );
}
