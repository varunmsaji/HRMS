import '../../../core/export/csv_export.dart';
import '../../profile/data/employee_repository.dart';

/// `GET /employees/directory/summary` (API `employee/directory.py` `DirectorySummary`): the
/// headline counts above the directory, over every employee the caller may see. Every figure is
/// the backend's — mirrors web `lib/employee/directory.ts`.
class DirectorySummary {
  const DirectorySummary({required this.total, required this.active, required this.onProbation, required this.onNotice, required this.departmentCount, required this.departmentNames});

  factory DirectorySummary.fromJson(Map<String, dynamic> json) => DirectorySummary(
    total: (json['total'] as num?)?.toInt() ?? 0,
    active: (json['active'] as num?)?.toInt() ?? 0,
    onProbation: (json['on_probation'] as num?)?.toInt() ?? 0,
    onNotice: (json['on_notice'] as num?)?.toInt() ?? 0,
    departmentCount: (json['department_count'] as num?)?.toInt() ?? 0,
    departmentNames: [for (final n in (json['department_names'] as List?) ?? const []) n.toString()],
  );

  final int total;
  final int active;
  final int onProbation;
  final int onNotice;
  final int departmentCount;
  final List<String> departmentNames;
}

/// `GET /employees/directory/rows?ids=…` (API `DirectoryRow`): job title, department, branch,
/// manager and shift for the employees asked about.
class DirectoryRow {
  const DirectoryRow({required this.employeeId, this.designation, this.department, this.branch, this.managerName, this.shiftName});

  factory DirectoryRow.fromJson(Map<String, dynamic> json) => DirectoryRow(
    employeeId: json['employee_id'] as String,
    designation: json['designation'] as String?,
    department: json['department'] as String?,
    branch: json['branch'] as String?,
    managerName: json['manager_name'] as String?,
    shiftName: json['shift_name'] as String?,
  );

  final String employeeId;
  final String? designation;
  final String? department;
  final String? branch;
  final String? managerName;
  final String? shiftName;
}

/// The directory endpoint takes at most this many ids per request.
const directoryRowsChunk = 200;

/// Record states, as web's "All states / Active only / Inactive only" filter.
enum RecordState { all, active, inactive }

/// The filters web applies to the rows on screen (status and record state; the text search is the
/// server's). On mobile they apply to every row loaded so far.
List<Employee> filterEmployees(List<Employee> rows, {String? status, RecordState state = RecordState.all}) => [
  for (final e in rows)
    if ((status == null || e.status == status) && (state == RecordState.all || (state == RecordState.active) == e.isActive)) e,
];

/// The employee's display name as both apps show it: the full name, or the code when there is none.
String employeeDisplayName(Employee e) => e.fullName.isEmpty ? e.employeeCode : e.fullName;

/// The employees CSV, with web's columns in web's order (`employeesToCsv`), for exactly the rows
/// given — the directory exports what it shows.
String employeesCsv(List<Employee> rows, Map<String, DirectoryRow> details) => toCsv(
  const ['Employee code', 'Name', 'Email', 'Mobile', 'Status', 'Designation', 'Department', 'Reporting manager', 'Shift'],
  [
    for (final e in rows)
      [
        e.employeeCode,
        employeeDisplayName(e),
        e.personalEmail,
        e.personalMobile,
        e.status,
        details[e.id]?.designation,
        details[e.id]?.department,
        details[e.id]?.managerName,
        details[e.id]?.shiftName,
      ],
  ],
);
