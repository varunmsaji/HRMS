import 'package:flutter_test/flutter_test.dart';
import 'package:hrms_mobile/features/onboarding/domain/onboarding_form_spec.dart';

OnboardingSectionSpec _spec(String name) => onboardingSections.firstWhere((s) => s.name == name);

void main() {
  test('covers the same nine sections as the web wizard, in order', () {
    expect(onboardingSections.map((s) => s.name), [
      'personal_info',
      'address_info',
      'emergency_contact',
      'bank_info',
      'statutory_info',
      'compensation_info',
      'previous_employment_info',
      'education_info',
      'nominee_info',
    ]);
  });

  test('personal info: required, PAN and Aadhaar validation, normalised payload', () {
    final spec = _spec('personal_info');
    expect(validateRow(spec, rowFromWire(spec, {})).keys, ['first_name']);
    final values = rowFromWire(spec, {'first_name': 'Asha'})
      ..['pan_number_enc'] = 'abcde1234f'
      ..['aadhaar_number_enc'] = '1234 5678 9012';
    expect(validateRow(spec, values), isEmpty);
    final payload = rowToPayload(spec, values);
    expect(payload['pan_number_enc'], 'ABCDE1234F');
    expect(payload['aadhaar_number_enc'], '123456789012');
    expect(payload['middle_name'], isNull);
    values['pan_number_enc'] = 'bad';
    values['aadhaar_number_enc'] = '12';
    expect(validateRow(spec, values).keys, containsAll(['pan_number_enc', 'aadhaar_number_enc']));
  });

  test('address: permanent fields are hidden and nulled when same as present', () {
    final spec = _spec('address_info');
    final values = rowFromWire(spec, {})..['permanent_city'] = 'Pune';
    expect(values['permanent_same_as_present'], true);
    expect(rowToPayload(spec, values)['permanent_city'], isNull);
    values['permanent_same_as_present'] = false;
    expect(rowToPayload(spec, values)['permanent_city'], 'Pune');
  });

  test('compensation: CTC converts to minor units and back', () {
    final spec = _spec('compensation_info');
    final values = rowFromWire(spec, {'annual_ctc_minor': 1250050, 'currency': 'INR'});
    expect(values['annual_ctc_minor'], '12500.5');
    expect(rowToPayload(spec, values)['annual_ctc_minor'], 1250050);
    values['currency'] = 'RU';
    expect(validateRow(spec, values).keys, ['currency']);
    expect(validateRow(spec, rowFromWire(spec, {})).keys, contains('annual_ctc_minor'));
  });

  test('bank and statutory require their enum choices', () {
    expect(validateRow(_spec('bank_info'), rowFromWire(_spec('bank_info'), {})).keys, ['payment_mode']);
    expect(validateRow(_spec('statutory_info'), rowFromWire(_spec('statutory_info'), {})).keys, ['tax_regime']);
  });

  test('nominees: guardian for minors, share % per scheme, 100% ceiling', () {
    final spec = _spec('nominee_info');
    final row = rowFromWire(spec, {'full_name': 'Ravi', 'relationship': 'Son'})
      ..['is_minor'] = true
      ..['is_pf_nominee'] = true;
    expect(validateRow(spec, row).keys, containsAll(['guardian_name', 'pf_nominee_share_percentage']));

    Map<String, dynamic> pf(String share) =>
        rowFromWire(spec, {'full_name': 'A', 'relationship': 'B'})..['is_pf_nominee'] = true..['pf_nominee_share_percentage'] = share;
    expect(validateNomineeTotals([pf('60'), pf('40')]), isNull);
    expect(validateNomineeTotals([pf('60'), pf('50')]), contains('PF'));
  });

  test('round-trips a repeatable row through the wire format', () {
    final spec = _spec('education_info');
    final wire = {'qualification': 'B.Tech', 'institution_name': 'IIT', 'year_of_passing': 2019};
    final back = rowToPayload(spec, rowFromWire(spec, wire));
    expect(back, wire);
  });
}
