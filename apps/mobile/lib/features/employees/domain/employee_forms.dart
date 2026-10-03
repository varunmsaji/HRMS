import '../../../core/forms/form_spec.dart';

/// Form specs for the employee record — each mirrors a `*Create`/`*Update` schema in
/// `apps/api/.../employee/schemas.py` (and the matching web form under
/// `apps/web/src/components/employee/`).

const genderOptions = ['Male', 'Female', 'Other', 'Prefer not to say'];
const maritalStatusOptions = ['Single', 'Married', 'Divorced', 'Widowed'];

const _same = '!permanent_same_as_present';

/// `EmployeeCreate` / `EmployeeUpdate`.
const employeeSpec = FormSpec(
  name: 'employee',
  label: 'Employee',
  defaults: {'permanent_same_as_present': true},
  fields: [
    FieldSpec('first_name', 'First name', required: true),
    FieldSpec('middle_name', 'Middle name'),
    FieldSpec('last_name', 'Last name'),
    FieldSpec('date_of_birth', 'Date of birth', kind: FieldKind.date),
    FieldSpec('gender', 'Gender', kind: FieldKind.select, options: genderOptions),
    FieldSpec('blood_group', 'Blood group'),
    FieldSpec('marital_status', 'Marital status', kind: FieldKind.select, options: maritalStatusOptions),
    FieldSpec('nationality', 'Nationality'),
    FieldSpec('father_or_husband_name', "Father's / husband's name"),
    FieldSpec('personal_email', 'Personal email', kind: FieldKind.email),
    FieldSpec('personal_mobile', 'Personal mobile'),
    FieldSpec('present_address_line1', 'Present address line 1'),
    FieldSpec('present_address_line2', 'Present address line 2'),
    FieldSpec('present_city', 'City'),
    FieldSpec('present_state_code', 'State code'),
    FieldSpec('present_pincode', 'Pincode'),
    FieldSpec('present_country_code', 'Country code', kind: FieldKind.upper, exactLength: 2, hint: '2 letters, e.g. IN'),
    FieldSpec('permanent_same_as_present', 'Permanent address is the same as present', kind: FieldKind.toggle),
    FieldSpec('permanent_address_line1', 'Permanent address line 1', showWhen: _same),
    FieldSpec('permanent_address_line2', 'Permanent address line 2', showWhen: _same),
    FieldSpec('permanent_city', 'Permanent city', showWhen: _same),
    FieldSpec('permanent_state_code', 'Permanent state code', showWhen: _same),
    FieldSpec('permanent_pincode', 'Permanent pincode', showWhen: _same),
    FieldSpec('permanent_country_code', 'Permanent country code', kind: FieldKind.upper, exactLength: 2, showWhen: _same),
    FieldSpec('emergency_contact_name', 'Emergency contact name'),
    FieldSpec('emergency_contact_relationship', 'Emergency contact relationship'),
    FieldSpec('emergency_contact_phone', 'Emergency contact phone'),
    FieldSpec('photo_url', 'Photo URL', kind: FieldKind.hidden),
  ],
);

const payBasisLabels = {'MONTHLY': 'Monthly', 'DAILY_WAGE': 'Daily wage'};

/// `EmploymentCreate` — a first hire or a rehire.
const employmentCreateSpec = FormSpec(
  name: 'employment',
  label: 'Employment',
  defaults: {'pay_basis': 'MONTHLY'},
  fields: [
    FieldSpec('legal_entity_id', 'Legal entity', kind: FieldKind.choice, choiceKey: 'legal_entities', required: true),
    FieldSpec('joining_date', 'Joining date', kind: FieldKind.date, required: true),
    FieldSpec('probation_end_date', 'Probation end date', kind: FieldKind.date),
    FieldSpec('pay_basis', 'Pay basis', kind: FieldKind.select, required: true, options: ['MONTHLY', 'DAILY_WAGE'], optionLabels: payBasisLabels),
  ],
);

/// `EmploymentUpdate` — a correction to the current episode.
const employmentEditSpec = FormSpec(
  name: 'employment_edit',
  label: 'Employment',
  fields: [
    FieldSpec('legal_entity_id', 'Legal entity', kind: FieldKind.choice, choiceKey: 'legal_entities', required: true),
    FieldSpec('probation_end_date', 'Probation end date', kind: FieldKind.date),
    FieldSpec('pay_basis', 'Pay basis', kind: FieldKind.select, required: true, options: ['MONTHLY', 'DAILY_WAGE'], optionLabels: payBasisLabels),
  ],
);

/// `EmploymentTerminate`.
const employmentTerminateSpec = FormSpec(
  name: 'employment_terminate',
  label: 'Terminate employment',
  fields: [FieldSpec('last_working_day', 'Last working day', kind: FieldKind.date, required: true)],
);

const assignmentChangeLabels = {
  'INITIAL': 'Initial placement',
  'TRANSFER': 'Transfer',
  'PROMOTION': 'Promotion',
  'MANAGER_CHANGE': 'Manager change',
  'SHIFT_CHANGE': 'Shift change',
};

const workLocationLabels = {'OFFICE': 'Office', 'WFH': 'Work from home', 'HYBRID': 'Hybrid', 'FIELD': 'Field'};

/// `AssignmentCreate` — empty reference fields carry forward from the current assignment.
FormSpec assignmentSpec(List<String> allowedChangeTypes) => FormSpec(
      name: 'assignment',
      label: 'Assignment',
      fields: [
        FieldSpec('change_type', 'Change type', kind: FieldKind.select, required: true, options: allowedChangeTypes, optionLabels: assignmentChangeLabels),
        const FieldSpec('effective_from', 'Effective from', kind: FieldKind.date, required: true),
        const FieldSpec('change_reason', 'Reason', kind: FieldKind.multiline),
        const FieldSpec('branch_id', 'Branch', kind: FieldKind.choice, choiceKey: 'branches'),
        const FieldSpec('department_id', 'Department', kind: FieldKind.choice, choiceKey: 'departments'),
        const FieldSpec('designation_id', 'Designation', kind: FieldKind.choice, choiceKey: 'designations'),
        const FieldSpec('grade_id', 'Grade', kind: FieldKind.choice, choiceKey: 'grades'),
        const FieldSpec('reporting_manager_id', 'Reporting manager', kind: FieldKind.choice, choiceKey: 'employees'),
        const FieldSpec('dotted_line_manager_id', 'Dotted-line manager', kind: FieldKind.choice, choiceKey: 'employees'),
        const FieldSpec('shift_id', 'Shift', kind: FieldKind.choice, choiceKey: 'shifts'),
        const FieldSpec('work_location_type', 'Work location', kind: FieldKind.select, options: ['OFFICE', 'WFH', 'HYBRID', 'FIELD'], optionLabels: workLocationLabels),
      ],
    );

const revisionTypeLabels = {'JOINING': 'Joining', 'ANNUAL': 'Annual', 'PROMOTION': 'Promotion', 'CORRECTION': 'Correction', 'MARKET': 'Market adjustment'};

/// `CompensationCreate` — nothing carries forward; every field is supplied.
const compensationSpec = FormSpec(
  name: 'compensation',
  label: 'Compensation',
  defaults: {'currency': 'INR'},
  fields: [
    FieldSpec('effective_from', 'Effective from', kind: FieldKind.date, required: true),
    FieldSpec('annual_ctc_minor', 'Annual CTC', kind: FieldKind.money, required: true),
    FieldSpec('currency', 'Currency (3-letter code)', kind: FieldKind.upper, required: true, exactLength: 3),
    FieldSpec('revision_type', 'Revision type', kind: FieldKind.select, required: true, options: ['JOINING', 'ANNUAL', 'PROMOTION', 'CORRECTION', 'MARKET'], optionLabels: revisionTypeLabels),
    FieldSpec('revision_reason', 'Revision reason', kind: FieldKind.multiline, required: true),
  ],
);

/// `StatutoryCreate`.
const statutorySpec = FormSpec(
  name: 'statutory',
  label: 'Statutory',
  fields: [
    FieldSpec('effective_from', 'Effective from', kind: FieldKind.date, required: true),
    FieldSpec('is_pf_applicable', 'PF applicable', kind: FieldKind.toggle),
    FieldSpec('pf_number', 'PF number'),
    FieldSpec('pf_wage_ceiling_opt_out', 'Opt out of PF wage ceiling', kind: FieldKind.toggle),
    FieldSpec('vpf_amount', 'VPF amount', kind: FieldKind.integer),
    FieldSpec('vpf_percentage', 'VPF percentage', kind: FieldKind.decimal),
    FieldSpec('is_esi_applicable', 'ESI applicable', kind: FieldKind.toggle),
    FieldSpec('esi_ip_number', 'ESI IP number'),
    FieldSpec('pt_state_code', 'Professional-tax state code'),
    FieldSpec('is_lwf_applicable', 'LWF applicable', kind: FieldKind.toggle),
    FieldSpec('tax_regime', 'Tax regime', kind: FieldKind.select, required: true, options: ['OLD', 'NEW']),
    FieldSpec('is_director', 'Director', kind: FieldKind.toggle),
    FieldSpec('is_international_worker', 'International worker', kind: FieldKind.toggle),
    FieldSpec('revision_reason', 'Revision reason', kind: FieldKind.multiline, required: true),
  ],
);

const paymentModeLabels = {'BANK': 'Bank transfer', 'CASH': 'Cash', 'CHEQUE': 'Cheque', 'UPI': 'UPI'};

/// `BankCreate`.
const bankSpec = FormSpec(
  name: 'bank',
  label: 'Banking',
  fields: [
    FieldSpec('effective_from', 'Effective from', kind: FieldKind.date, required: true),
    FieldSpec('account_holder_name', 'Account holder name'),
    FieldSpec('account_number_enc', 'Account number'),
    FieldSpec('bank_name', 'Bank name'),
    FieldSpec('ifsc', 'IFSC', kind: FieldKind.upper),
    FieldSpec('branch_name', 'Branch name'),
    FieldSpec('payment_mode', 'Payment mode', kind: FieldKind.select, required: true, options: ['BANK', 'CASH', 'CHEQUE', 'UPI'], optionLabels: paymentModeLabels),
  ],
);

/// `EmployeeIdentityUpdate` (PAN / Aadhaar / UAN).
const identitySpec = FormSpec(
  name: 'identity',
  label: 'Identity',
  fields: [
    FieldSpec('pan_number', 'PAN', kind: FieldKind.pan, hint: 'e.g. ABCDE1234F'),
    FieldSpec('aadhaar_number', 'Aadhaar', kind: FieldKind.aadhaar, hint: '12 digits'),
    FieldSpec('uan_number', 'UAN'),
    FieldSpec('father_or_husband_name', "Father's / husband's name"),
  ],
);

/// `EmployeeExperienceCreate`.
const experienceSpec = FormSpec(
  name: 'experience',
  label: 'Experience',
  fields: [
    FieldSpec('company_name', 'Company name', required: true),
    FieldSpec('designation', 'Designation'),
    FieldSpec('from_date', 'From', kind: FieldKind.date, required: true),
    FieldSpec('to_date', 'To', kind: FieldKind.date),
    FieldSpec('last_ctc_minor', 'Last CTC', kind: FieldKind.money),
    FieldSpec('reason_for_leaving', 'Reason for leaving', kind: FieldKind.multiline),
    FieldSpec('had_prior_pf_membership', 'Had a prior PF membership', kind: FieldKind.toggle),
    FieldSpec('previous_uan', 'Previous UAN'),
    FieldSpec('previous_pf_account_number', 'Previous PF account number'),
    FieldSpec('previous_esi_ip_number', 'Previous ESI IP number'),
  ],
);

/// `EmployeeEducationCreate`.
const educationSpec = FormSpec(
  name: 'education',
  label: 'Education',
  fields: [
    FieldSpec('qualification', 'Qualification', required: true),
    FieldSpec('institution_name', 'Institution'),
    FieldSpec('year_of_passing', 'Year of passing', kind: FieldKind.integer),
  ],
);

/// `EmployeeDependentCreate`.
const dependentSpec = FormSpec(
  name: 'dependent',
  label: 'Dependent',
  fields: [
    FieldSpec('full_name', 'Full name', required: true),
    FieldSpec('relationship', 'Relationship', required: true),
    FieldSpec('date_of_birth', 'Date of birth', kind: FieldKind.date),
    FieldSpec('gender', 'Gender', kind: FieldKind.select, options: genderOptions),
    FieldSpec('is_minor', 'Is a minor', kind: FieldKind.toggle),
    FieldSpec('guardian_name', 'Guardian name', showWhen: 'is_minor'),
    FieldSpec('guardian_relationship', 'Guardian relationship', showWhen: 'is_minor'),
    FieldSpec('aadhaar_number_enc', 'Aadhaar', kind: FieldKind.aadhaar),
    FieldSpec('is_pf_nominee', 'PF nominee', kind: FieldKind.toggle),
    FieldSpec('pf_nominee_share_percentage', 'PF share %', kind: FieldKind.decimal, showWhen: 'is_pf_nominee'),
    FieldSpec('is_gratuity_nominee', 'Gratuity nominee', kind: FieldKind.toggle),
    FieldSpec('gratuity_nominee_share_percentage', 'Gratuity share %', kind: FieldKind.decimal, showWhen: 'is_gratuity_nominee'),
    FieldSpec('is_esi_dependent', 'ESI dependent', kind: FieldKind.toggle),
  ],
);
