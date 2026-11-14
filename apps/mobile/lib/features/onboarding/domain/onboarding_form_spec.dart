/// Field-for-field mirror of `apps/web/src/lib/onboarding/public-wizard.ts` (itself a mirror of
/// `apps/api/.../onboarding/schemas.py`). Each section is a [FormSpec]; the shared form engine
/// (`core/forms`) reads and writes the wire JSON through them.
library;

import '../../../core/forms/form_spec.dart';

/// Nominee rules a per-field spec can't express (mirror `validateNominee`): a guardian for
/// minors, and a share % for each nominee scheme.
Map<String, String> _validateNominee(Map<String, dynamic> values) {
  final errors = <String, String>{};
  String text(String k) => ((values[k] ?? '') as String).trim();
  if (values['is_minor'] == true && text('guardian_name').isEmpty) errors['guardian_name'] = 'Guardian name is required for a minor.';
  if (values['is_pf_nominee'] == true && text('pf_nominee_share_percentage').isEmpty) errors['pf_nominee_share_percentage'] = 'PF share % is required.';
  if (values['is_gratuity_nominee'] == true && text('gratuity_nominee_share_percentage').isEmpty) {
    errors['gratuity_nominee_share_percentage'] = 'Gratuity share % is required.';
  }
  return errors;
}

const _paymentModeLabels = {'BANK': 'Bank transfer', 'CASH': 'Cash', 'CHEQUE': 'Cheque', 'UPI': 'UPI'};

const onboardingSections = <FormSpec>[
  FormSpec(
    name: 'personal_info',
    label: 'Personal Info',
    description: 'Basic details HR needs for your employee record.',
    fields: [
      FieldSpec('first_name', 'First name', required: true),
      FieldSpec('middle_name', 'Middle name'),
      FieldSpec('last_name', 'Last name'),
      FieldSpec('date_of_birth', 'Date of birth', kind: FieldKind.date),
      FieldSpec('gender', 'Gender', kind: FieldKind.select, options: ['Male', 'Female', 'Other', 'Prefer not to say']),
      FieldSpec('blood_group', 'Blood group'),
      FieldSpec('marital_status', 'Marital status', kind: FieldKind.select, options: ['Single', 'Married', 'Divorced', 'Widowed']),
      FieldSpec('nationality', 'Nationality'),
      FieldSpec('father_or_husband_name', "Father's / husband's name"),
      FieldSpec('pan_number_enc', 'PAN number', kind: FieldKind.pan, hint: 'e.g. ABCDE1234F'),
      FieldSpec('aadhaar_number_enc', 'Aadhaar number', kind: FieldKind.aadhaar, hint: '12 digits'),
      FieldSpec('photo_url', 'Photo URL', kind: FieldKind.hidden),
    ],
  ),
  FormSpec(
    name: 'address_info',
    label: 'Address',
    description: 'Where you currently live.',
    defaults: {'permanent_same_as_present': true},
    fields: [
      FieldSpec('address_line1', 'Address line 1'),
      FieldSpec('address_line2', 'Address line 2'),
      FieldSpec('city', 'City'),
      FieldSpec('state_code', 'State code'),
      FieldSpec('pincode', 'Pincode'),
      FieldSpec('country_code', 'Country code'),
      FieldSpec('permanent_same_as_present', 'Permanent address is the same as present', kind: FieldKind.toggle),
      FieldSpec('permanent_address_line1', 'Permanent address line 1', showWhen: '!permanent_same_as_present'),
      FieldSpec('permanent_address_line2', 'Permanent address line 2', showWhen: '!permanent_same_as_present'),
      FieldSpec('permanent_city', 'Permanent city', showWhen: '!permanent_same_as_present'),
      FieldSpec('permanent_state_code', 'Permanent state code', showWhen: '!permanent_same_as_present'),
      FieldSpec('permanent_pincode', 'Permanent pincode', showWhen: '!permanent_same_as_present'),
      FieldSpec('permanent_country_code', 'Permanent country code', showWhen: '!permanent_same_as_present'),
    ],
  ),
  FormSpec(
    name: 'emergency_contact',
    label: 'Emergency Contact',
    description: 'Who we should contact if something happens at work.',
    fields: [
      FieldSpec('contact_name', 'Contact name', required: true),
      FieldSpec('relationship', 'Relationship'),
      FieldSpec('phone', 'Phone number', required: true),
    ],
  ),
  FormSpec(
    name: 'bank_info',
    label: 'Bank Details',
    description: 'Where your salary will be paid.',
    fields: [
      FieldSpec('account_holder_name', 'Account holder name'),
      FieldSpec('account_number_enc', 'Account number'),
      FieldSpec('bank_name', 'Bank name'),
      FieldSpec('ifsc', 'IFSC'),
      FieldSpec('branch_name', 'Branch name'),
      FieldSpec('payment_mode', 'Payment mode', kind: FieldKind.select, required: true, options: ['BANK', 'CASH', 'CHEQUE', 'UPI'], optionLabels: _paymentModeLabels),
    ],
  ),
  FormSpec(
    name: 'statutory_info',
    label: 'Statutory Details',
    description: 'Tax and statutory registration details.',
    fields: [
      FieldSpec('is_pf_applicable', 'PF applicable', kind: FieldKind.toggle),
      FieldSpec('pf_number', 'PF number'),
      FieldSpec('uan_number', 'UAN'),
      FieldSpec('pf_wage_ceiling_opt_out', 'Opted out of PF wage ceiling', kind: FieldKind.toggle),
      FieldSpec('vpf_amount', 'VPF amount', kind: FieldKind.integer),
      FieldSpec('vpf_percentage', 'VPF percentage', kind: FieldKind.decimal),
      FieldSpec('is_esi_applicable', 'ESI applicable', kind: FieldKind.toggle),
      FieldSpec('esi_ip_number', 'ESI IP number'),
      FieldSpec('pt_state_code', 'Professional-tax state code'),
      FieldSpec('is_lwf_applicable', 'LWF applicable', kind: FieldKind.toggle),
      FieldSpec('tax_regime', 'Tax regime', kind: FieldKind.select, required: true, options: ['OLD', 'NEW']),
      FieldSpec('is_director', 'Is a director', kind: FieldKind.toggle),
      FieldSpec('is_international_worker', 'International worker', kind: FieldKind.toggle),
    ],
  ),
  FormSpec(
    name: 'previous_employment_info',
    label: 'Previous Employment',
    description: 'Help HR carry forward your PF account from a past employer, if any.',
    repeatable: true,
    itemNoun: 'employer',
    fields: [
      FieldSpec('company_name', 'Company name', required: true),
      FieldSpec('designation', 'Designation'),
      FieldSpec('from_date', 'From date', kind: FieldKind.date, required: true),
      FieldSpec('to_date', 'To date', kind: FieldKind.date),
      FieldSpec('last_ctc_minor', 'Last drawn annual CTC', kind: FieldKind.money),
      FieldSpec('reason_for_leaving', 'Reason for leaving'),
      FieldSpec('had_prior_pf_membership', 'I was a PF member at this employer', kind: FieldKind.toggle),
      FieldSpec('previous_uan', 'Previous UAN'),
      FieldSpec('previous_pf_account_number', 'Previous PF account number'),
      FieldSpec('previous_esi_ip_number', 'Previous ESI IP number'),
    ],
  ),
  FormSpec(
    name: 'education_info',
    label: 'Education',
    description: 'Your educational qualifications.',
    repeatable: true,
    itemNoun: 'qualification',
    fields: [
      FieldSpec('qualification', 'Qualification', required: true),
      FieldSpec('institution_name', 'Institution name'),
      FieldSpec('year_of_passing', 'Year of passing', kind: FieldKind.integer),
    ],
  ),
  FormSpec(
    name: 'nominee_info',
    extraValidate: _validateNominee,
    label: 'Nominees & Family',
    description: 'Your PF/Gratuity nominees and ESI-covered family members.',
    repeatable: true,
    itemNoun: 'person',
    fields: [
      FieldSpec('full_name', 'Full name', required: true),
      FieldSpec('relationship', 'Relationship', required: true),
      FieldSpec('date_of_birth', 'Date of birth', kind: FieldKind.date),
      FieldSpec('gender', 'Gender', kind: FieldKind.select, options: ['Male', 'Female', 'Other', 'Prefer not to say']),
      FieldSpec('is_minor', 'Minor', kind: FieldKind.toggle),
      FieldSpec('guardian_name', 'Guardian name', showWhen: 'is_minor'),
      FieldSpec('guardian_relationship', 'Guardian relationship', showWhen: 'is_minor'),
      FieldSpec('aadhaar_number_enc', 'Aadhaar number', kind: FieldKind.aadhaar),
      FieldSpec('is_pf_nominee', 'PF nominee', kind: FieldKind.toggle),
      FieldSpec('pf_nominee_share_percentage', 'PF nominee share %', kind: FieldKind.decimal, showWhen: 'is_pf_nominee'),
      FieldSpec('is_gratuity_nominee', 'Gratuity nominee', kind: FieldKind.toggle),
      FieldSpec('gratuity_nominee_share_percentage', 'Gratuity nominee share %', kind: FieldKind.decimal, showWhen: 'is_gratuity_nominee'),
      FieldSpec('is_esi_dependent', 'ESI family member', kind: FieldKind.toggle),
    ],
  ),
];

const onboardingDocumentTypes = {
  'PHOTO': 'Photo',
  'PAN': 'PAN card',
  'AADHAAR': 'Aadhaar card',
  'ADDRESS_PROOF': 'Address proof',
  'EDUCATION_CERTIFICATE': 'Education certificate',
  'PREVIOUS_EMPLOYMENT_PROOF': 'Previous employment proof',
  'BANK_PROOF': 'Bank proof',
  'OTHER': 'Other',
};

/// Cross-row rule for nominees: each scheme's shares may not add up to more than 100%.
String? validateNomineeTotals(List<Map<String, dynamic>> rows) {
  double total(String flag, String share) => rows
      .where((r) => r[flag] == true)
      .fold<double>(0, (sum, r) => sum + (double.tryParse((r[share] ?? '').toString()) ?? 0));
  if (total('is_pf_nominee', 'pf_nominee_share_percentage') > 100) {
    return 'PF nominee share percentages add up to more than 100%.';
  }
  if (total('is_gratuity_nominee', 'gratuity_nominee_share_percentage') > 100) {
    return 'Gratuity nominee share percentages add up to more than 100%.';
  }
  return null;
}

/// Read-only `(label, value)` rows for HR review: wire JSON through the spec's labels/types.
List<(String, String)> displayRows(FormSpec spec, Map<String, dynamic> wire) {
  final out = <(String, String)>[];
  for (final f in spec.fields) {
    if (f.kind == FieldKind.hidden) continue;
    final v = wire[f.key];
    if (v == null || v == '') continue;
    if (f.kind == FieldKind.toggle) {
      out.add((f.label, v == true ? 'Yes' : 'No'));
    } else if (f.kind == FieldKind.money && v is num) {
      out.add((f.label, (v / 100).toStringAsFixed(2)));
    } else {
      out.add((f.label, v.toString()));
    }
  }
  return out;
}

/// HR starts an onboarding case — `OnboardingCaseCreate` (and the web `OnboardingCaseForm`). The
/// candidate then fills in the eight sections themselves from their invite link.
const onboardingCaseSpec = FormSpec(name: 'onboarding_case', label: 'Onboarding case', fields: [
  FieldSpec('candidate_first_name', 'First name', required: true),
  FieldSpec('candidate_last_name', 'Last name'),
  FieldSpec('personal_email', 'Personal email', kind: FieldKind.email, required: true),
  FieldSpec('personal_mobile', 'Personal mobile'),
  FieldSpec('proposed_joining_date', 'Proposed joining date', kind: FieldKind.date, required: true),
  FieldSpec('branch_id', 'Branch', kind: FieldKind.choice, choiceKey: 'branches'),
  FieldSpec('department_id', 'Department', kind: FieldKind.choice, choiceKey: 'departments'),
  FieldSpec('designation_id', 'Designation', kind: FieldKind.choice, choiceKey: 'designations'),
]);
