/// Field-for-field mirror of `apps/web/src/lib/onboarding/public-wizard.ts` (itself a mirror of
/// `apps/api/.../onboarding/schemas.py`). Each section is data: the generic wizard form reads
/// and writes the wire JSON through these specs, so adding a field is one line here.
library;

enum OnboardingFieldType { text, date, select, toggle, integer, decimal, money, pan, aadhaar, upper, hidden }

class OnboardingField {
  const OnboardingField(
    this.key,
    this.label, {
    this.type = OnboardingFieldType.text,
    this.required = false,
    this.options = const [],
    this.showWhen,
    this.hint,
  });

  /// Wire key in the section JSON (e.g. `pan_number_enc`).
  final String key;
  final String label;
  final OnboardingFieldType type;
  final bool required;

  /// Allowed values for [OnboardingFieldType.select] (value == label unless in [selectLabels]).
  final List<String> options;

  /// Only shown (and sent) when this toggle key in the same row/section is true (or false when
  /// prefixed with `!`).
  final String? showWhen;
  final String? hint;
}

class OnboardingSectionSpec {
  const OnboardingSectionSpec({
    required this.name,
    required this.label,
    required this.description,
    required this.fields,
    this.repeatable = false,
    this.itemNoun = 'entry',
    this.defaults = const {},
  });

  /// Wire section name — the `{section}` path segment and the case JSON key.
  final String name;
  final String label;
  final String description;
  final List<OnboardingField> fields;

  /// Stored as `{"items": [ {...}, ... ]}` instead of a flat object.
  final bool repeatable;
  final String itemNoun;
  final Map<String, dynamic> defaults;
}

const paymentModeLabels = {'BANK': 'Bank transfer', 'CASH': 'Cash', 'CHEQUE': 'Cheque', 'UPI': 'UPI'};

const onboardingSections = <OnboardingSectionSpec>[
  OnboardingSectionSpec(
    name: 'personal_info',
    label: 'Personal Info',
    description: 'Basic details HR needs for your employee record.',
    fields: [
      OnboardingField('first_name', 'First name', required: true),
      OnboardingField('middle_name', 'Middle name'),
      OnboardingField('last_name', 'Last name'),
      OnboardingField('date_of_birth', 'Date of birth', type: OnboardingFieldType.date),
      OnboardingField('gender', 'Gender', type: OnboardingFieldType.select, options: ['Male', 'Female', 'Other', 'Prefer not to say']),
      OnboardingField('blood_group', 'Blood group'),
      OnboardingField('marital_status', 'Marital status', type: OnboardingFieldType.select, options: ['Single', 'Married', 'Divorced', 'Widowed']),
      OnboardingField('nationality', 'Nationality'),
      OnboardingField('father_or_husband_name', "Father's / husband's name"),
      OnboardingField('pan_number_enc', 'PAN', type: OnboardingFieldType.pan, hint: 'e.g. ABCDE1234F'),
      OnboardingField('aadhaar_number_enc', 'Aadhaar', type: OnboardingFieldType.aadhaar, hint: '12 digits'),
      OnboardingField('photo_url', 'Photo URL', type: OnboardingFieldType.hidden),
    ],
  ),
  OnboardingSectionSpec(
    name: 'address_info',
    label: 'Address',
    description: 'Where you currently live.',
    defaults: {'permanent_same_as_present': true},
    fields: [
      OnboardingField('address_line1', 'Address line 1'),
      OnboardingField('address_line2', 'Address line 2'),
      OnboardingField('city', 'City'),
      OnboardingField('state_code', 'State code'),
      OnboardingField('pincode', 'Pincode'),
      OnboardingField('country_code', 'Country code'),
      OnboardingField('permanent_same_as_present', 'Permanent address is the same as present', type: OnboardingFieldType.toggle),
      OnboardingField('permanent_address_line1', 'Permanent address line 1', showWhen: '!permanent_same_as_present'),
      OnboardingField('permanent_address_line2', 'Permanent address line 2', showWhen: '!permanent_same_as_present'),
      OnboardingField('permanent_city', 'Permanent city', showWhen: '!permanent_same_as_present'),
      OnboardingField('permanent_state_code', 'Permanent state code', showWhen: '!permanent_same_as_present'),
      OnboardingField('permanent_pincode', 'Permanent pincode', showWhen: '!permanent_same_as_present'),
      OnboardingField('permanent_country_code', 'Permanent country code', showWhen: '!permanent_same_as_present'),
    ],
  ),
  OnboardingSectionSpec(
    name: 'emergency_contact',
    label: 'Emergency Contact',
    description: 'Who we should contact if something happens at work.',
    fields: [
      OnboardingField('contact_name', 'Contact name', required: true),
      OnboardingField('relationship', 'Relationship'),
      OnboardingField('phone', 'Phone', required: true),
    ],
  ),
  OnboardingSectionSpec(
    name: 'bank_info',
    label: 'Bank Details',
    description: 'Where your salary will be paid.',
    fields: [
      OnboardingField('account_holder_name', 'Account holder name'),
      OnboardingField('account_number_enc', 'Account number'),
      OnboardingField('bank_name', 'Bank name'),
      OnboardingField('ifsc', 'IFSC'),
      OnboardingField('branch_name', 'Branch name'),
      OnboardingField('payment_mode', 'Payment mode', type: OnboardingFieldType.select, required: true, options: ['BANK', 'CASH', 'CHEQUE', 'UPI']),
    ],
  ),
  OnboardingSectionSpec(
    name: 'statutory_info',
    label: 'Statutory Details',
    description: 'Tax and statutory registration details.',
    fields: [
      OnboardingField('is_pf_applicable', 'PF applicable', type: OnboardingFieldType.toggle),
      OnboardingField('pf_number', 'PF number'),
      OnboardingField('uan_number', 'UAN'),
      OnboardingField('pf_wage_ceiling_opt_out', 'Opt out of PF wage ceiling', type: OnboardingFieldType.toggle),
      OnboardingField('vpf_amount', 'VPF amount', type: OnboardingFieldType.integer),
      OnboardingField('vpf_percentage', 'VPF percentage', type: OnboardingFieldType.decimal),
      OnboardingField('is_esi_applicable', 'ESI applicable', type: OnboardingFieldType.toggle),
      OnboardingField('esi_ip_number', 'ESI IP number'),
      OnboardingField('pt_state_code', 'Professional-tax state code'),
      OnboardingField('is_lwf_applicable', 'LWF applicable', type: OnboardingFieldType.toggle),
      OnboardingField('tax_regime', 'Tax regime', type: OnboardingFieldType.select, required: true, options: ['OLD', 'NEW']),
      OnboardingField('is_director', 'Director', type: OnboardingFieldType.toggle),
      OnboardingField('is_international_worker', 'International worker', type: OnboardingFieldType.toggle),
    ],
  ),
  OnboardingSectionSpec(
    name: 'compensation_info',
    label: 'Compensation',
    description: 'Your agreed compensation for this role.',
    defaults: {'currency': 'INR'},
    fields: [
      OnboardingField('annual_ctc_minor', 'Annual CTC', type: OnboardingFieldType.money, required: true),
      OnboardingField('currency', 'Currency (3-letter code)', type: OnboardingFieldType.upper, required: true),
    ],
  ),
  OnboardingSectionSpec(
    name: 'previous_employment_info',
    label: 'Previous Employment',
    description: 'Help HR carry forward your PF account from a past employer, if any.',
    repeatable: true,
    itemNoun: 'employer',
    fields: [
      OnboardingField('company_name', 'Company name', required: true),
      OnboardingField('designation', 'Designation'),
      OnboardingField('from_date', 'From', type: OnboardingFieldType.date, required: true),
      OnboardingField('to_date', 'To', type: OnboardingFieldType.date),
      OnboardingField('last_ctc_minor', 'Last CTC', type: OnboardingFieldType.money),
      OnboardingField('reason_for_leaving', 'Reason for leaving'),
      OnboardingField('had_prior_pf_membership', 'Had a prior PF membership', type: OnboardingFieldType.toggle),
      OnboardingField('previous_uan', 'Previous UAN'),
      OnboardingField('previous_pf_account_number', 'Previous PF account number'),
      OnboardingField('previous_esi_ip_number', 'Previous ESI IP number'),
    ],
  ),
  OnboardingSectionSpec(
    name: 'education_info',
    label: 'Education',
    description: 'Your educational qualifications.',
    repeatable: true,
    itemNoun: 'qualification',
    fields: [
      OnboardingField('qualification', 'Qualification', required: true),
      OnboardingField('institution_name', 'Institution'),
      OnboardingField('year_of_passing', 'Year of passing', type: OnboardingFieldType.integer),
    ],
  ),
  OnboardingSectionSpec(
    name: 'nominee_info',
    label: 'Nominees & Family',
    description: 'Your PF/Gratuity nominees and ESI-covered family members.',
    repeatable: true,
    itemNoun: 'person',
    fields: [
      OnboardingField('full_name', 'Full name', required: true),
      OnboardingField('relationship', 'Relationship', required: true),
      OnboardingField('date_of_birth', 'Date of birth', type: OnboardingFieldType.date),
      OnboardingField('gender', 'Gender', type: OnboardingFieldType.select, options: ['Male', 'Female', 'Other', 'Prefer not to say']),
      OnboardingField('is_minor', 'Is a minor', type: OnboardingFieldType.toggle),
      OnboardingField('guardian_name', 'Guardian name', showWhen: 'is_minor'),
      OnboardingField('guardian_relationship', 'Guardian relationship', showWhen: 'is_minor'),
      OnboardingField('aadhaar_number_enc', 'Aadhaar', type: OnboardingFieldType.aadhaar),
      OnboardingField('is_pf_nominee', 'PF nominee', type: OnboardingFieldType.toggle),
      OnboardingField('pf_nominee_share_percentage', 'PF share %', type: OnboardingFieldType.decimal, showWhen: 'is_pf_nominee'),
      OnboardingField('is_gratuity_nominee', 'Gratuity nominee', type: OnboardingFieldType.toggle),
      OnboardingField('gratuity_nominee_share_percentage', 'Gratuity share %', type: OnboardingFieldType.decimal, showWhen: 'is_gratuity_nominee'),
      OnboardingField('is_esi_dependent', 'ESI dependent', type: OnboardingFieldType.toggle),
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

// ---- wire <-> form-string conversion ----------------------------------------------------------

final _panPattern = RegExp(r'^[A-Z]{5}[0-9]{4}[A-Z]$');
final _aadhaarPattern = RegExp(r'^[0-9]{12}$');

bool fieldVisible(OnboardingField f, Map<String, dynamic> values) {
  final cond = f.showWhen;
  if (cond == null) return true;
  if (cond.startsWith('!')) return values[cond.substring(1)] != true;
  return values[cond] == true;
}

/// Wire JSON value -> the form's working value (strings for text-like, bool for toggles).
dynamic toFormValue(OnboardingField f, dynamic wire) {
  switch (f.type) {
    case OnboardingFieldType.toggle:
      return wire == true;
    case OnboardingFieldType.money:
      return wire is num ? (wire / 100).toString().replaceAll(RegExp(r'\.0$'), '') : '';
    case OnboardingFieldType.hidden:
      return wire;
    default:
      return wire == null ? '' : wire.toString();
  }
}

/// Form working value -> wire JSON value (mirrors each `*ToPayload` in public-wizard.ts).
dynamic toWireValue(OnboardingField f, dynamic form) {
  switch (f.type) {
    case OnboardingFieldType.toggle:
      return form == true;
    case OnboardingFieldType.hidden:
      return form;
    case OnboardingFieldType.integer:
      final s = (form ?? '').toString().trim();
      return s.isEmpty ? null : num.tryParse(s)?.truncate();
    case OnboardingFieldType.decimal:
      final s = (form ?? '').toString().trim();
      return s.isEmpty ? null : num.tryParse(s);
    case OnboardingFieldType.money:
      final s = (form ?? '').toString().trim();
      final n = s.isEmpty ? null : num.tryParse(s);
      return n == null ? null : (n * 100).round();
    case OnboardingFieldType.pan:
      final s = (form ?? '').toString().trim().toUpperCase();
      return s.isEmpty ? null : s;
    case OnboardingFieldType.aadhaar:
      final s = (form ?? '').toString().replaceAll(RegExp(r'\s+'), '');
      return s.isEmpty ? null : s;
    case OnboardingFieldType.upper:
      final s = (form ?? '').toString().trim().toUpperCase();
      return s.isEmpty ? null : s;
    default:
      final s = (form ?? '').toString().trim();
      return s.isEmpty ? null : s;
  }
}

/// Section/row form values -> wire payload (hidden-by-condition fields are sent as null/false).
Map<String, dynamic> rowToPayload(OnboardingSectionSpec spec, Map<String, dynamic> values) {
  return {
    for (final f in spec.fields)
      f.key: fieldVisible(f, values)
          ? toWireValue(f, values[f.key])
          : (f.type == OnboardingFieldType.toggle ? false : null),
  };
}

Map<String, dynamic> rowFromWire(OnboardingSectionSpec spec, Map<String, dynamic> wire) {
  return {
    for (final f in spec.fields) f.key: toFormValue(f, wire.containsKey(f.key) ? wire[f.key] : spec.defaults[f.key]),
  };
}

/// Per-field validation for one row/section. Returns `{fieldKey: message}`.
Map<String, String> validateRow(OnboardingSectionSpec spec, Map<String, dynamic> values) {
  final errors = <String, String>{};
  for (final f in spec.fields) {
    if (!fieldVisible(f, values)) continue;
    final raw = values[f.key];
    final text = raw is String ? raw.trim() : '';
    if (f.required && f.type != OnboardingFieldType.toggle && text.isEmpty) {
      errors[f.key] = '${f.label} is required.';
      continue;
    }
    switch (f.type) {
      case OnboardingFieldType.pan:
        if (text.isNotEmpty && !_panPattern.hasMatch(text.toUpperCase())) {
          errors[f.key] = 'Enter a valid 10-character PAN (e.g. ABCDE1234F).';
        }
      case OnboardingFieldType.aadhaar:
        if (text.isNotEmpty && !_aadhaarPattern.hasMatch(text.replaceAll(RegExp(r'\s+'), ''))) {
          errors[f.key] = 'Enter a valid 12-digit Aadhaar number.';
        }
      case OnboardingFieldType.money:
        if (text.isNotEmpty) {
          final n = num.tryParse(text);
          if (n == null || n < 0) errors[f.key] = 'Enter a valid amount.';
        }
      case OnboardingFieldType.integer || OnboardingFieldType.decimal:
        if (text.isNotEmpty && num.tryParse(text) == null) errors[f.key] = 'Enter a valid number.';
      case OnboardingFieldType.upper:
        if (f.required && text.length != 3) errors[f.key] = 'Enter a 3-letter currency code (e.g. INR).';
      default:
        break;
    }
  }
  // Nominee-specific rules (mirror `validateNominee`): guardian for minors, share % for schemes.
  if (spec.name == 'nominee_info') {
    if (values['is_minor'] == true && ((values['guardian_name'] ?? '') as String).trim().isEmpty) {
      errors['guardian_name'] = 'Guardian name is required for a minor.';
    }
    if (values['is_pf_nominee'] == true && ((values['pf_nominee_share_percentage'] ?? '') as String).trim().isEmpty) {
      errors['pf_nominee_share_percentage'] = 'PF share % is required.';
    }
    if (values['is_gratuity_nominee'] == true && ((values['gratuity_nominee_share_percentage'] ?? '') as String).trim().isEmpty) {
      errors['gratuity_nominee_share_percentage'] = 'Gratuity share % is required.';
    }
  }
  return errors;
}

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
