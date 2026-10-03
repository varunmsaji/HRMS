import '../api/api_client.dart';
import 'form_spec.dart';

/// Where the options for a `FieldKind.choice` field come from: a list endpoint plus how to label a
/// row. Keys are the `choiceKey` used in specs.
class _Source {
  const _Source(this.path, this.label, {this.filter});
  final String path;
  final String Function(Map<String, dynamic>) label;
  final bool Function(Map<String, dynamic>)? filter;
}

String _name(Map<String, dynamic> m) => (m['name'] ?? m['code'] ?? m['id']).toString();

String _person(Map<String, dynamic> m) {
  final display = (m['display_name'] ?? '').toString().trim();
  final name = display.isNotEmpty ? display : [m['first_name'], m['last_name']].where((s) => s != null && s.toString().isNotEmpty).join(' ');
  final code = (m['employee_code'] ?? '').toString();
  return '${name.isEmpty ? 'Unnamed' : name}${code.isEmpty ? '' : ' ($code)'}';
}

final Map<String, _Source> _sources = {
  'legal_entities': _Source('/legal-entities', _name, filter: (m) => m['is_active'] != false),
  'branches': _Source('/branches', _name, filter: (m) => m['is_active'] != false),
  'departments': _Source('/departments', _name, filter: (m) => m['is_active'] != false),
  'designations': _Source('/designations', _name, filter: (m) => m['is_active'] != false),
  'grades': _Source('/grades', _name, filter: (m) => m['is_active'] != false),
  'shifts': _Source('/shifts', _name, filter: (m) => m['is_active'] != false),
  'employees': _Source('/employees', _person),
  'leave_types': _Source('/leave-types', _name, filter: (m) => m['is_active'] != false),
  'holiday_calendars': _Source('/holiday-calendars', _name),
  'weekly_off_patterns': _Source('/weekly-off-patterns', _name),
  'work_calendars': _Source('/work-calendars', _name),
  'attendance_policies': _Source('/attendance-policies', _name),
  'overtime_policies': _Source('/overtime-policies', _name),
  'regularization_policies': _Source('/regularization-policies', _name),
  'leave_policies': _Source('/leave-policies', _name),
  'salary_structures': _Source('/payroll/salary-structures', _name, filter: (m) => m['is_active'] != false),
  'salary_components': _Source('/payroll/salary-components', (m) => '${m['name']} (${m['code']})', filter: (m) => m['is_active'] != false),
};

/// Loads every page (the API caps a page at 100) of each requested source.
Future<Map<String, List<Choice>>> loadChoices(ApiClient client, Iterable<String> keys) async {
  final out = <String, List<Choice>>{};
  for (final key in keys.toSet()) {
    final source = _sources[key];
    if (source == null) throw ArgumentError('Unknown choice source "$key"');
    final choices = <Choice>[];
    for (var page = 1; page <= 20; page++) {
      final env = await client.getList<Map<String, dynamic>>(
        source.path,
        query: PageQuery(page: page, perPage: 100),
        parseItem: (d) => d as Map<String, dynamic>,
      );
      for (final row in env.data) {
        if (source.filter != null && !source.filter!(row)) continue;
        choices.add((value: row['id'] as String, label: source.label(row)));
      }
      if (!(env.pagination?.hasNext ?? false)) break;
    }
    out[key] = choices;
  }
  return out;
}
