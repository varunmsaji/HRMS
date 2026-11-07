import 'package:flutter_test/flutter_test.dart';
import 'package:hrms_mobile/core/export/csv_export.dart';

void main() {
  test('cells are quoted only when needed, with quotes doubled (web csvCell rule)', () {
    expect(csvCell('plain'), 'plain');
    expect(csvCell(null), '');
    expect(csvCell('a,b'), '"a,b"');
    expect(csvCell('say "hi"'), '"say ""hi"""');
    expect(csvCell('two\nlines'), '"two\nlines"');
  });

  test('a document is the header then one line per row, joined with newlines', () {
    expect(toCsv(['A', 'B'], [['1', null], ['x,y', '2']]), 'A,B\n1,\n"x,y",2');
    expect(toCsv(['A'], const []), 'A');
  });
}
