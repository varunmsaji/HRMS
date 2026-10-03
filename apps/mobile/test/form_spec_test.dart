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
  rowsTests();
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

// ---- repeating rows ---------------------------------------------------------------------------

const _bandSpec = FormSpec(name: 'band', label: 'Band', fields: [
  FieldSpec('min_minutes', 'From', kind: FieldKind.integer, required: true),
  FieldSpec('classification', 'Class', kind: FieldKind.select, required: true, options: ['LATE', 'ABSENT']),
]);

const _rowsSpec = FormSpec(name: 'p', label: 'P', fields: [
  FieldSpec('bands', 'Bands', kind: FieldKind.rows, rowSpec: _bandSpec, rowNoun: 'band', orderKey: 'sort_order'),
  FieldSpec('blocks', 'Blocks', kind: FieldKind.rows, rowSpec: _bandSpec, required: true, orderKey: 'sequence', orderStart: 1),
]);

void rowsTests() {
  group('rows', () {
    test('wire rows become working rows and back, numbering them by position', () {
      final values = rowFromWire(_rowsSpec, {
        'bands': [
          {'id': 'x', 'min_minutes': 5, 'classification': 'LATE', 'sort_order': 9},
          {'id': 'y', 'min_minutes': 30, 'classification': 'ABSENT', 'sort_order': 3},
        ],
      });
      expect((values['bands'] as List).length, 2);
      expect((values['bands'] as List).first['min_minutes'], '5');
      final payload = rowToPayload(_rowsSpec, values);
      expect(payload['bands'], [
        {'min_minutes': 5, 'classification': 'LATE', 'sort_order': 0},
        {'min_minutes': 30, 'classification': 'ABSENT', 'sort_order': 1},
      ]);
    });

    test('1-based ordering keys start where asked', () {
      final values = rowFromWire(_rowsSpec, {'blocks': [{'min_minutes': 1, 'classification': 'LATE'}, {'min_minutes': 2, 'classification': 'LATE'}]});
      final blocks = rowToPayload(_rowsSpec, values)['blocks'] as List;
      expect(blocks.map((b) => b['sequence']), [1, 2]);
    });

    test('a required list needs at least one row, and each row is validated with its position in the key', () {
      var errors = validateRow(_rowsSpec, rowFromWire(_rowsSpec, {}));
      expect(errors['blocks'], 'Add at least one row.');
      errors = validateRow(_rowsSpec, rowFromWire(_rowsSpec, {
        'blocks': [{'min_minutes': 1, 'classification': 'LATE'}],
        'bands': [{'min_minutes': 5, 'classification': 'LATE'}, {'min_minutes': '', 'classification': ''}],
      }));
      expect(errors.keys, containsAll(['bands.1.min_minutes', 'bands.1.classification']));
      expect(errors.keys.where((k) => k.startsWith('bands.0')), isEmpty);
    });

    test('an unchanged list is not reported as a change, even though stored rows carry ids and extra keys', () {
      final original = {
        'bands': [
          {'id': 'x', 'min_minutes': 5, 'classification': 'LATE', 'sort_order': 0, 'created_at': 'z'},
        ],
        'blocks': [
          {'id': 'b', 'min_minutes': 1, 'classification': 'LATE', 'sequence': 1},
        ],
      };
      final payload = rowToPayload(_rowsSpec, rowFromWire(_rowsSpec, original));
      expect(changedOnly(original, payload), isEmpty);
    });

    test('an edited row is reported as a change', () {
      final original = {
        'bands': [
          {'id': 'x', 'min_minutes': 5, 'classification': 'LATE', 'sort_order': 0},
        ],
        'blocks': <dynamic>[],
      };
      final values = rowFromWire(_rowsSpec, original);
      ((values['bands'] as List).first as Map)['min_minutes'] = '10';
      final changed = changedOnly(original, rowToPayload(_rowsSpec, values));
      expect(changed.keys, ['bands']);
    });
  });
}
