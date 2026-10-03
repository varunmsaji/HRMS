import '../../../core/forms/form_spec.dart';
import '../../../core/time.dart';

/// The company profile edit form — mirrors `apps/web/src/components/company/company-profile-form.tsx`
/// and `validate-company-profile.ts`. The wire profile is nested (contact, address, locale, …);
/// the form is flat, converted by [profileToForm] and [buildProfilePatch].

const companySizeBands = ['1-10', '11-50', '51-200', '201-500', '501-1000', '1000+'];
const weekDays = ['MON', 'TUE', 'WED', 'THU', 'FRI', 'SAT', 'SUN'];
const weekDayLabels = {'MON': 'Monday', 'TUE': 'Tuesday', 'WED': 'Wednesday', 'THU': 'Thursday', 'FRI': 'Friday', 'SAT': 'Saturday', 'SUN': 'Sunday'};
const monthNames = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'];

/// Currency can only change while the company is on trial (the web disables it otherwise).
FormSpec companyProfileSpec({required bool currencyLocked}) => FormSpec(
      name: 'company_profile',
      label: 'Company profile',
      extraValidate: (v) => {
        if (!weekDays.any((d) => v['wd_$d'] == true)) 'wd_MON': 'Select at least one working day.',
        if ((v['bh_start'] ?? '').toString().isNotEmpty != (v['bh_end'] ?? '').toString().isNotEmpty) 'bh_end': 'Set both start and end, or neither.',
        if ((v['bh_start'] ?? '').toString().isNotEmpty && (v['bh_end'] ?? '').toString().isNotEmpty && (v['bh_end'] as String).compareTo(v['bh_start'] as String) <= 0) 'bh_end': 'End must be later than start.',
      },
      fields: [
        const FieldSpec('name', 'Company name', required: true),
        const FieldSpec('legal_name', 'Legal name'),
        const FieldSpec('registration_number', 'Registration number'),
        const FieldSpec('industry_code', 'Industry code'),
        const FieldSpec('company_size', 'Company size', kind: FieldKind.select, options: companySizeBands),
        const FieldSpec('country_code', 'Country code', kind: FieldKind.upper, required: true, exactLength: 2),
        FieldSpec('currency', 'Currency', kind: FieldKind.upper, required: true, exactLength: 3, readOnlyOnEdit: currencyLocked, hint: currencyLocked ? 'Currency cannot be changed after trial.' : null),
        FieldSpec('timezone', 'Timezone', kind: FieldKind.select, required: true, options: allTimeZones()),
        const FieldSpec('contact_email', 'Contact email', kind: FieldKind.email),
        const FieldSpec('contact_phone', 'Contact phone'),
        const FieldSpec('contact_website', 'Website'),
        const FieldSpec('address_line1', 'Address line 1'),
        const FieldSpec('address_line2', 'Address line 2'),
        const FieldSpec('address_city', 'City'),
        const FieldSpec('address_state', 'State'),
        const FieldSpec('address_postal_code', 'Postal code'),
        const FieldSpec('address_country_code', 'Address country code', kind: FieldKind.upper, exactLength: 2),
        const FieldSpec('locale_language_code', 'Language code', required: true),
        const FieldSpec('locale_date_format', 'Date format', required: true),
        FieldSpec('fiscal_start_month', 'Fiscal year start', kind: FieldKind.select, required: true, intValue: true, options: [for (var i = 1; i <= 12; i++) '$i'], optionLabels: {for (var i = 1; i <= 12; i++) '$i': monthNames[i - 1]}),
        for (final d in weekDays) FieldSpec('wd_$d', weekDayLabels[d]!, kind: FieldKind.toggle),
        const FieldSpec('bh_start', 'Business hours start', kind: FieldKind.time),
        const FieldSpec('bh_end', 'Business hours end', kind: FieldKind.time),
        const FieldSpec('logo_url', 'Logo URL'),
        const FieldSpec('primary_color', 'Primary color', hint: 'e.g. #4F46E5'),
      ],
    );

Map<String, dynamic> _m(dynamic v) => v is Map ? Map<String, dynamic>.from(v) : <String, dynamic>{};

/// `CompanyProfileRead` -> the flat wire values the form edits.
Map<String, dynamic> profileToForm(Map<String, dynamic> p) {
  final contact = _m(p['contact']), address = _m(p['address']), locale = _m(p['locale']), hours = _m(p['business_hours']), branding = _m(p['branding']);
  final working = <String, bool>{
    for (final d in ((p['working_days'] as List?) ?? const [])) if (d is Map) d['day'] as String: d['is_working'] == true,
  };
  return {
    'name': p['name'],
    'legal_name': p['legal_name'],
    'registration_number': p['registration_number'],
    'industry_code': p['industry_code'],
    'company_size': p['company_size'],
    'country_code': p['country_code'],
    'currency': p['currency'],
    'timezone': p['timezone'],
    'contact_email': contact['email'],
    'contact_phone': contact['phone'],
    'contact_website': contact['website'],
    'address_line1': address['line1'],
    'address_line2': address['line2'],
    'address_city': address['city'],
    'address_state': address['state'],
    'address_postal_code': address['postal_code'],
    'address_country_code': address['country_code'],
    'locale_language_code': locale['language_code'] ?? 'en-IN',
    'locale_date_format': locale['date_format'] ?? 'DD/MM/YYYY',
    'fiscal_start_month': _m(p['fiscal_year'])['start_month'] ?? 4,
    for (final d in weekDays) 'wd_$d': working[d] ?? false,
    'bh_start': hours['start_time'],
    'bh_end': hours['end_time'],
    'logo_url': branding['logo_url'],
    'primary_color': _m(branding['theme'])['primary_color'],
  };
}

/// The nested `PATCH /companies/current` body for the flat keys that [changed] — a nested group is
/// sent whole as soon as any of its members changed (the server replaces it).
Map<String, dynamic> buildProfilePatch(Map<String, dynamic> payload, Map<String, dynamic> changed) {
  final patch = <String, dynamic>{};
  for (final k in const ['name', 'legal_name', 'registration_number', 'industry_code', 'company_size', 'country_code', 'currency', 'timezone']) {
    if (changed.containsKey(k)) patch[k] = payload[k];
  }
  bool any(String prefix) => changed.keys.any((k) => k.startsWith(prefix));
  if (any('contact_')) {
    patch['contact'] = {'email': payload['contact_email'], 'phone': payload['contact_phone'], 'website': payload['contact_website']};
  }
  if (any('address_')) {
    patch['address'] = {
      'line1': payload['address_line1'],
      'line2': payload['address_line2'],
      'city': payload['address_city'],
      'state': payload['address_state'],
      'postal_code': payload['address_postal_code'],
      'country_code': payload['address_country_code'],
    };
  }
  if (any('locale_')) patch['locale'] = {'language_code': payload['locale_language_code'], 'date_format': payload['locale_date_format']};
  if (changed.containsKey('fiscal_start_month')) patch['fiscal_year'] = {'start_month': payload['fiscal_start_month']};
  if (any('wd_')) patch['working_days'] = [for (final d in weekDays) {'day': d, 'is_working': payload['wd_$d'] == true, 'is_alternate': false}];
  if (any('bh_')) {
    final s = payload['bh_start'], e = payload['bh_end'];
    patch['business_hours'] = (s != null && e != null) ? {'start_time': s, 'end_time': e} : null;
  }
  if (any('logo_url') || any('primary_color')) {
    final color = payload['primary_color'];
    patch['branding'] = {'logo_url': payload['logo_url'], 'theme': color != null ? {'primary_color': color} : null};
  }
  return patch;
}
