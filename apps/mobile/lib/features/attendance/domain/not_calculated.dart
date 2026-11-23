import '../../profile/data/employee_repository.dart';

/// The API takes at most this many employees in one range request (`employee_ids`, max 1000).
const recalculateMaxEmployees = 1000;

/// Is [e] inside an employment spell that covers [date] (`YYYY-MM-DD`)? Mirrors the web's
/// `isEmployedOn` (`apps/web/src/lib/attendance/dashboard.ts`): `joining <= date` and
/// `last_working_day` empty or `>= date`. `GET /employees` carries both dates; an employee with no
/// joining date (still pre-joining) is not counted.
bool isEmployedOn(Employee e, String date) {
  final joined = e.raw['employment_joining_date'] as String?;
  if (joined == null || joined.isEmpty || joined.compareTo(date) > 0) return false;
  final last = e.raw['employment_last_working_day'] as String?;
  if (last != null && last.isNotEmpty && last.compareTo(date) < 0) return false;
  return true;
}

/// R-D06: employed people with no calculated attendance day on [date]. On a past date they are
/// missing from every figure, and at period close an unresolved day becomes absent. Mirrors the
/// web's `employeesWithoutRecord` (without the department / branch / shift filters, which this
/// screen does not have).
List<Employee> employeesWithoutRecord(List<Employee> employees, Set<String> employeeIdsWithRow, String date) => [
      for (final e in employees)
        if (!employeeIdsWithRow.contains(e.id) && e.isActive && isEmployedOn(e, date)) e,
    ];
