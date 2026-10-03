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
