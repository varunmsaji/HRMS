import '../../../core/api/api_client.dart';

class LegalEntity {
  LegalEntity({
    required this.id,
    required this.name,
    this.registeredAddress,
    this.pan,
    this.tan,
    this.cin,
    this.gstin,
    required this.isActive,
    required this.version,
  });

  final String id;
  final String name;
  final String? registeredAddress;
  final String? pan;
  final String? tan;
  final String? cin;
  final String? gstin;
  final bool isActive;
  final int version;

  factory LegalEntity.fromJson(Map<String, dynamic> json) => LegalEntity(
        id: json['id'] as String,
        name: json['name'] as String,
        registeredAddress: json['registered_address'] as String?,
        pan: json['pan'] as String?,
        tan: json['tan'] as String?,
        cin: json['cin'] as String?,
        gstin: json['gstin'] as String?,
        isActive: json['is_active'] as bool,
        version: json['version'] as int,
      );
}

class Branch {
  Branch({
    required this.id,
    required this.legalEntityId,
    required this.name,
    this.code,
    this.city,
    this.stateCode,
    required this.isActive,
    required this.version,
  });

  final String id;
  final String legalEntityId;
  final String name;
  final String? code;
  final String? city;
  final String? stateCode;
  final bool isActive;
  final int version;

  factory Branch.fromJson(Map<String, dynamic> json) => Branch(
        id: json['id'] as String,
        legalEntityId: json['legal_entity_id'] as String,
        name: json['name'] as String,
        code: json['code'] as String?,
        city: json['city'] as String?,
        stateCode: json['state_code'] as String?,
        isActive: json['is_active'] as bool,
        version: json['version'] as int,
      );
}

class Department {
  Department({
    required this.id,
    this.branchId,
    this.parentId,
    required this.name,
    this.code,
    this.headEmployeeId,
    required this.isActive,
    required this.version,
  });

  final String id;
  final String? branchId;
  final String? parentId;
  final String name;
  final String? code;
  final String? headEmployeeId;
  final bool isActive;
  final int version;

  factory Department.fromJson(Map<String, dynamic> json) => Department(
        id: json['id'] as String,
        branchId: json['branch_id'] as String?,
        parentId: json['parent_id'] as String?,
        name: json['name'] as String,
        code: json['code'] as String?,
        headEmployeeId: json['head_employee_id'] as String?,
        isActive: json['is_active'] as bool,
        version: json['version'] as int,
      );
}

class Designation {
  Designation({
    required this.id,
    this.departmentId,
    this.gradeId,
    required this.title,
    this.code,
    required this.isActive,
    required this.version,
  });

  final String id;
  final String? departmentId;
  final String? gradeId;
  final String title;
  final String? code;
  final bool isActive;
  final int version;

  factory Designation.fromJson(Map<String, dynamic> json) => Designation(
        id: json['id'] as String,
        departmentId: json['department_id'] as String?,
        gradeId: json['grade_id'] as String?,
        title: json['title'] as String,
        code: json['code'] as String?,
        isActive: json['is_active'] as bool,
        version: json['version'] as int,
      );
}

class Grade {
  Grade({
    required this.id,
    required this.code,
    required this.name,
    this.level,
    this.minCtc,
    this.maxCtc,
    required this.isActive,
    required this.version,
  });

  final String id;
  final String code;
  final String name;
  final int? level;
  final int? minCtc;
  final int? maxCtc;
  final bool isActive;
  final int version;

  factory Grade.fromJson(Map<String, dynamic> json) => Grade(
        id: json['id'] as String,
        code: json['code'] as String,
        name: json['name'] as String,
        level: json['level'] as int?,
        minCtc: json['min_ctc'] as int?,
        maxCtc: json['max_ctc'] as int?,
        isActive: json['is_active'] as bool,
        version: json['version'] as int,
      );
}

class CompanyContact {
  CompanyContact({this.email, this.phone, this.website});
  final String? email;
  final String? phone;
  final String? website;

  factory CompanyContact.fromJson(Map<String, dynamic> json) =>
      CompanyContact(email: json['email'] as String?, phone: json['phone'] as String?, website: json['website'] as String?);

  Map<String, dynamic> toJson() => {'email': email, 'phone': phone, 'website': website};
}

class CompanyAddress {
  CompanyAddress({this.line1, this.line2, this.city, this.state, this.postalCode, this.countryCode});
  final String? line1;
  final String? line2;
  final String? city;
  final String? state;
  final String? postalCode;
  final String? countryCode;

  factory CompanyAddress.fromJson(Map<String, dynamic> json) => CompanyAddress(
        line1: json['line1'] as String?,
        line2: json['line2'] as String?,
        city: json['city'] as String?,
        state: json['state'] as String?,
        postalCode: json['postal_code'] as String?,
        countryCode: json['country_code'] as String?,
      );

  Map<String, dynamic> toJson() => {
        'line1': line1,
        'line2': line2,
        'city': city,
        'state': state,
        'postal_code': postalCode,
        'country_code': countryCode,
      };
}

/// `GET/PATCH /companies/current` — mirrors `CompanyProfileRead`. Only the
/// fields the mobile Company screen actually shows/edits; `locale`,
/// `fiscal_year`, `working_days`, `business_hours`, `branding` are read-only
/// passthrough here (shown if present, not editable yet).
class CompanyProfile {
  CompanyProfile({
    required this.id,
    required this.name,
    this.legalName,
    this.registrationNumber,
    required this.contact,
    required this.address,
    this.industryCode,
    this.companySize,
    required this.countryCode,
    required this.currency,
    required this.timezone,
    required this.status,
    required this.version,
  });

  final String id;
  final String name;
  final String? legalName;
  final String? registrationNumber;
  final CompanyContact contact;
  final CompanyAddress address;
  final String? industryCode;
  final String? companySize;
  final String countryCode;
  final String currency;
  final String timezone;
  final String status;
  final int version;

  factory CompanyProfile.fromJson(Map<String, dynamic> json) => CompanyProfile(
        id: json['id'] as String,
        name: json['name'] as String,
        legalName: json['legal_name'] as String?,
        registrationNumber: json['registration_number'] as String?,
        contact: CompanyContact.fromJson(json['contact'] as Map<String, dynamic>),
        address: CompanyAddress.fromJson(json['address'] as Map<String, dynamic>),
        industryCode: json['industry_code'] as String?,
        companySize: json['company_size'] as String?,
        countryCode: json['country_code'] as String,
        currency: json['currency'] as String,
        timezone: json['timezone'] as String,
        status: json['status'] as String,
        version: json['version'] as int,
      );
}

/// Every Organisation-settings resource — mirrors
/// `apps/api/src/hrms/modules/organisation/{router,schemas}.py`. Delete is
/// always soft (`is_active=false`, returns 200 with the resource), never a
/// hard 204 delete.
class OrganisationRepository {
  OrganisationRepository(this._client);

  final ApiClient _client;

  Future<CompanyProfile> getCompanyProfile() => _client.get(
        '/companies/current',
        parse: (data) => CompanyProfile.fromJson(data as Map<String, dynamic>),
      );

  Future<CompanyProfile> updateCompanyProfile(Map<String, dynamic> body, {required String ifMatch}) => _client.patch(
        '/companies/current',
        body: body,
        ifMatch: ifMatch,
        parse: (data) => CompanyProfile.fromJson(data as Map<String, dynamic>),
      );

  Future<List<LegalEntity>> listLegalEntities() => _client
      .getList('/legal-entities', parseItem: (d) => LegalEntity.fromJson(d as Map<String, dynamic>))
      .then((e) => e.data);

  Future<LegalEntity> createLegalEntity(Map<String, dynamic> body) => _client.post(
        '/legal-entities',
        body: body,
        parse: (data) => LegalEntity.fromJson(data as Map<String, dynamic>),
      );

  Future<LegalEntity> updateLegalEntity(String id, Map<String, dynamic> body, {required String ifMatch}) => _client.patch(
        '/legal-entities/$id',
        body: body,
        ifMatch: ifMatch,
        parse: (data) => LegalEntity.fromJson(data as Map<String, dynamic>),
      );

  Future<List<Branch>> listBranches() =>
      _client.getList('/branches', parseItem: (d) => Branch.fromJson(d as Map<String, dynamic>)).then((e) => e.data);

  Future<Branch> createBranch(Map<String, dynamic> body) => _client.post(
        '/branches',
        body: body,
        parse: (data) => Branch.fromJson(data as Map<String, dynamic>),
      );

  Future<Branch> updateBranch(String id, Map<String, dynamic> body, {required String ifMatch}) => _client.patch(
        '/branches/$id',
        body: body,
        ifMatch: ifMatch,
        parse: (data) => Branch.fromJson(data as Map<String, dynamic>),
      );

  Future<List<Department>> listDepartments() => _client
      .getList('/departments', parseItem: (d) => Department.fromJson(d as Map<String, dynamic>))
      .then((e) => e.data);

  Future<Department> createDepartment(Map<String, dynamic> body) => _client.post(
        '/departments',
        body: body,
        parse: (data) => Department.fromJson(data as Map<String, dynamic>),
      );

  Future<Department> updateDepartment(String id, Map<String, dynamic> body, {required String ifMatch}) => _client.patch(
        '/departments/$id',
        body: body,
        ifMatch: ifMatch,
        parse: (data) => Department.fromJson(data as Map<String, dynamic>),
      );

  Future<List<Designation>> listDesignations() => _client
      .getList('/designations', parseItem: (d) => Designation.fromJson(d as Map<String, dynamic>))
      .then((e) => e.data);

  Future<Designation> createDesignation(Map<String, dynamic> body) => _client.post(
        '/designations',
        body: body,
        parse: (data) => Designation.fromJson(data as Map<String, dynamic>),
      );

  Future<Designation> updateDesignation(String id, Map<String, dynamic> body, {required String ifMatch}) => _client.patch(
        '/designations/$id',
        body: body,
        ifMatch: ifMatch,
        parse: (data) => Designation.fromJson(data as Map<String, dynamic>),
      );

  Future<List<Grade>> listGrades() =>
      _client.getList('/grades', parseItem: (d) => Grade.fromJson(d as Map<String, dynamic>)).then((e) => e.data);

  Future<Grade> createGrade(Map<String, dynamic> body) => _client.post(
        '/grades',
        body: body,
        parse: (data) => Grade.fromJson(data as Map<String, dynamic>),
      );

  Future<Grade> updateGrade(String id, Map<String, dynamic> body, {required String ifMatch}) => _client.patch(
        '/grades/$id',
        body: body,
        ifMatch: ifMatch,
        parse: (data) => Grade.fromJson(data as Map<String, dynamic>),
      );
}
