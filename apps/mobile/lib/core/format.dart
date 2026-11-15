/// ₹ with Indian digit grouping (12,34,567); paise shown only when present. Mirrors the web
/// app's `formatInr` (`apps/web/src/lib/payroll/types.ts`).
String formatInr(num minor) {
  final negative = minor < 0;
  final abs = minor.abs();
  final rupees = abs ~/ 100;
  final paise = (abs % 100).round();
  final digits = rupees.toString();
  String grouped;
  if (digits.length <= 3) {
    grouped = digits;
  } else {
    final last3 = digits.substring(digits.length - 3);
    var rest = digits.substring(0, digits.length - 3);
    final parts = <String>[];
    while (rest.length > 2) {
      parts.insert(0, rest.substring(rest.length - 2));
      rest = rest.substring(0, rest.length - 2);
    }
    if (rest.isNotEmpty) parts.insert(0, rest);
    grouped = '${parts.join(',')},$last3';
  }
  final fraction = paise == 0 ? '' : '.${paise.toString().padLeft(2, '0')}';
  return '${negative ? '-' : ''}₹$grouped$fraction';
}

const _months = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'];

/// "2026-09" -> "September 2026".
String formatPayMonth(String month) {
  final parts = month.split('-');
  if (parts.length != 2) return month;
  final m = int.tryParse(parts[1]);
  if (m == null || m < 1 || m > 12) return month;
  return '${_months[m - 1]} ${parts[0]}';
}

/// "12,00,000" / "1200000.50" -> paise; null when it is not a valid non-negative amount.
int? rupeesToMinor(String value) {
  final cleaned = value.replaceAll(',', '').trim();
  if (!RegExp(r'^\d+(\.\d{1,2})?$').hasMatch(cleaned)) return null;
  return (double.parse(cleaned) * 100).round();
}

const _shortMonths = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

/// "2026-11-12" -> "12 Nov". Anything that is not a date comes back unchanged.
String formatShortDate(String iso) {
  final d = DateTime.tryParse(iso);
  return d == null ? iso : '${d.day} ${_shortMonths[d.month - 1]}';
}

/// "12 Nov", "12–13 Nov", or "30 Oct – 2 Nov" for an inclusive range of ISO dates, with the year
/// added when the range is not in this year ("28 Dec 2025 – 2 Jan 2026").
String formatDateRange(String start, String end, {DateTime? now}) {
  final s = DateTime.tryParse(start), e = DateTime.tryParse(end);
  if (s == null || e == null) return start == end ? start : '$start – $end';
  final thisYear = (now ?? DateTime.now()).year;
  final withYear = s.year != thisYear || e.year != thisYear;
  String day(DateTime d) => '${d.day} ${_shortMonths[d.month - 1]}${withYear ? ' ${d.year}' : ''}';
  if (start == end) return day(s);
  if (s.year == e.year && s.month == e.month) return '${s.day}–${day(e)}';
  if (s.year == e.year && withYear) return '${s.day} ${_shortMonths[s.month - 1]} – ${day(e)}';
  return '${day(s)} – ${day(e)}';
}

/// "1 Apr 2026": always with the year, for effective dates and records that span years.
String formatFullDate(String iso) {
  final d = DateTime.tryParse(iso);
  return d == null ? iso : '${d.day} ${_shortMonths[d.month - 1]} ${d.year}';
}

/// An effective period: "1 Apr 2026 – 31 Mar 2027", or "From 1 Apr 2026" when it has no end.
/// [openEnd] names a missing end when the screen needs a word ("present").
String formatPeriod(String? from, String? to, {String? openEnd}) {
  if (from == null || from.isEmpty) return to == null || to.isEmpty ? '—' : 'Until ${formatFullDate(to)}';
  if (to == null || to.isEmpty) return openEnd == null ? 'From ${formatFullDate(from)}' : '${formatFullDate(from)} – $openEnd';
  return '${formatFullDate(from)} – ${formatFullDate(to)}';
}

/// "1 day", "2 days", "0.5 day".
String formatDayCount(num days) => '${formatLeaveDays(days)} ${days == 1 || days == 0.5 ? 'day' : 'days'}';

const _weekdays = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];

/// "2026-11-12" -> "Thu, 12 Nov" (with the year when it is not this year's).
String formatDayDate(String iso, {DateTime? now}) {
  final d = DateTime.tryParse(iso);
  if (d == null) return iso;
  final year = (now ?? DateTime.now()).year == d.year ? '' : ' ${d.year}';
  return '${_weekdays[d.weekday - 1]}, ${d.day} ${_shortMonths[d.month - 1]}$year';
}

/// A leave day count: whole numbers without decimals ("4"), halves as written ("8.5").
String formatLeaveDays(num days) => days == days.roundToDouble() ? '${days.toInt()}' : days.toStringAsFixed(1);
