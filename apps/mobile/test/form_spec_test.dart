import 'package:flutter_test/flutter_test.dart';
import 'package:hrms_mobile/core/forms/form_spec.dart';

const _spec = FormSpec(name: 't', label: 'T', fields: [
  FieldSpec('when', 'When', kind: FieldKind.dateTime, required: true),
  FieldSpec('mail', 'Mail', kind: FieldKind.email),
  FieldSpec('at', 'At', kind: FieldKind.time),
  FieldSpec('on', 'On', kind: FieldKind.date),
  FieldSpec('amt', 'Amt', kind: FieldKind.money),
  FieldSpec('cur', 'Cur', kind: FieldKind.upper, exactLength: 3),
  FieldSpec('flag', 'Flag', kind: FieldKind.toggle),
  FieldSpec('extra', 'Extra', showWhen: 'flag'),
]);

Map<String, dynamic> _v(Map<String, dynamic> over) => {'when': '2026-09-15T09:00', 'mail': '', 'at': '', 'on': '', 'amt': '', 'cur': '', 'flag': false, 'extra': '', ...over};

void main() {
  test('valid values pass', () => expect(validateRow(_spec, _v({'mail': 'a@b.co', 'at': '09:30', 'on': '2026-09-15', 'amt': '12.5', 'cur': 'INR'})), isEmpty));

  test('date-time must be a full local date and time', () {
    expect(validateRow(_spec, _v({'when': ''})).keys, ['when']);
    expect(validateRow(_spec, _v({'when': '2026-09-15'})).keys, ['when']);
    expect(validateRow(_spec, _v({'when': '2026-09-15T25:00'})).keys, ['when']);
    expect(validateRow(_spec, _v({'when': '2026-09-15T09:00:30'})), isEmpty);
  });

  test('email, time, date, money and fixed-length codes are checked only when filled', () {
    expect(validateRow(_spec, _v({'mail': 'nope'})).keys, ['mail']);
    expect(validateRow(_spec, _v({'at': '9:5'})).keys, ['at']);
    expect(validateRow(_spec, _v({'on': '15/09/2026'})).keys, ['on']);
    expect(validateRow(_spec, _v({'amt': '-3'})).keys, ['amt']);
    expect(validateRow(_spec, _v({'cur': 'IN'})).keys, ['cur']);
  });

  test('conditional fields are not validated or sent while hidden', () {
    final payload = rowToPayload(_spec, _v({'extra': 'secret'}));
    expect(payload['extra'], isNull);
    expect(rowToPayload(_spec, _v({'flag': true, 'extra': 'x'}))['extra'], 'x');
  });

  test('payload converts money to minor units and codes to upper case', () {
    final p = rowToPayload(_spec, _v({'amt': '12.5', 'cur': 'inr'}));
    expect(p['amt'], 1250);
    expect(p['cur'], 'INR');
    expect(p['mail'], isNull);
  });

  test('changedOnly sends just what differs, comparing numbers and numeric strings', () {
    expect(changedOnly({'a': 1, 'b': '2.50', 'c': 'x'}, {'a': 1, 'b': 2.5, 'c': 'y'}), {'c': 'y'});
    expect(changedOnly({'a': null}, {'a': null}), isEmpty);
  });
}
