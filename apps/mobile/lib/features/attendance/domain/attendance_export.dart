/// Server-built exports of the muster register and the attendance reports (web
/// `apps/web/src/lib/attendance/export.ts`). The server covers up to a year and only the employees
/// the caller may see, so a file is not limited to the rows the phone loaded.
const exportFormatLabels = {'csv': 'CSV', 'xlsx': 'Excel', 'pdf': 'PDF'};

const exportMimeTypes = {
  'csv': 'text/csv',
  'xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
  'pdf': 'application/pdf',
};

/// A PDF register is a page of columns: past this many days the server refuses it.
const maxPdfRegisterDays = 62;

/// The longest period the server will export: a year, to the day.
const maxExportDays = 366;

/// Mobile report key -> the server's report name (payroll attendance has no server export).
const serverReports = {
  'daily': 'daily',
  'present_absent': 'present-absent',
  'late_early': 'late-early',
  'hours': 'hours',
  'overtime': 'overtime',
};

int _days(String from, String to) => DateTime.parse('${to}T00:00:00Z').difference(DateTime.parse('${from}T00:00:00Z')).inDays + 1;

/// Why [from]..[to] (`YYYY-MM-DD`) cannot be exported, or null when it can. ISO dates compare as text.
String? exportWindowError(String from, String to, String today) {
  if (from.isEmpty || to.isEmpty) return 'Choose both dates.';
  if (from.compareTo(to) > 0) return 'The start date must be on or before the end date.';
  if (to.compareTo(today) > 0) return 'The period cannot end in the future.';
  if (_days(from, to) > maxExportDays) return 'The period can be at most $maxExportDays days.';
  return null;
}

/// Why a PDF register cannot cover [from]..[to], or null.
String? pdfRegisterError(String from, String to) =>
    _days(from, to) > maxPdfRegisterDays ? 'A PDF register can cover at most $maxPdfRegisterDays days. Choose Excel or CSV for a longer period.' : null;

String musterExportPath(String from, String to, String format) => '/attendance/export/muster?${Uri(queryParameters: {'date_from': from, 'date_to': to, 'format': format}).query}';

String reportExportPath(String report, String from, String to, String format) => '/attendance/reports/$report/export?${Uri(queryParameters: {'date_from': from, 'date_to': to, 'format': format}).query}';
