import 'package:timezone/data/latest_all.dart' as tzdata;
import 'package:timezone/timezone.dart' as tz;

/// Business-time helpers — the mobile counterpart of `apps/web/src/lib/attendance/format.ts`
/// (TZ-06/TZ-07): every attendance time is shown in the *company's* zone, never the device's, and
/// "today" is the business date. These are display/date-derivation helpers only.

var _ready = false;

/// Loads the tz database. Called from `main()`; the helpers also call it lazily so tests and
/// background code never trip over an uninitialised database.
void initTimeZones() {
  if (_ready) return;
  tzdata.initializeTimeZones();
  _ready = true;
}

tz.Location _location(String zone) {
  initTimeZones();
  try {
    return tz.getLocation(zone);
  } catch (_) {
    return tz.UTC;
  }
}

/// "5h 30m" style duration; null -> "—".
String formatMinutes(int? minutes) {
  if (minutes == null) return '—';
  final sign = minutes < 0 ? '-' : '';
  final abs = minutes.abs();
  return '$sign${abs ~/ 60}h ${abs % 60}m';
}

/// The short label shown next to a rendered time. A deliberately small lookup — India is the only
/// zone V1 resolves to; anything else shows its IANA identifier rather than a guessed label.
String zoneLabel(String zone) => (zone == 'Asia/Kolkata' || zone == 'Asia/Calcutta') ? 'IST' : zone;

const _months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

String _clock(tz.TZDateTime t) {
  final h12 = t.hour % 12 == 0 ? 12 : t.hour % 12;
  return '$h12:${t.minute.toString().padLeft(2, '0')} ${t.hour < 12 ? 'am' : 'pm'}';
}

tz.TZDateTime? _inZone(String? iso, String zone) {
  if (iso == null || iso.isEmpty) return null;
  final parsed = DateTime.tryParse(iso);
  if (parsed == null) return null;
  return tz.TZDateTime.from(parsed, _location(zone));
}

/// "just now", "5 mins ago", "3 hours ago", "2 days ago", and the date once it is over a month old.
String relativeTime(String iso, {DateTime? now}) {
  final then = DateTime.tryParse(iso);
  if (then == null) return '—';
  final mins = (now ?? DateTime.now()).difference(then).inSeconds / 60;
  final m = mins.round() < 0 ? 0 : mins.round();
  if (m < 1) return 'just now';
  if (m < 60) return '$m min${m == 1 ? '' : 's'} ago';
  final hours = (m / 60).round();
  if (hours < 24) return '$hours hour${hours == 1 ? '' : 's'} ago';
  final days = (hours / 24).round();
  if (days < 31) return '$days day${days == 1 ? '' : 's'} ago';
  final d = then.toUtc();
  return '${d.day} ${_months[d.month - 1]} ${d.year}';
}

/// "5:30 am IST"; null/empty -> "—".
String formatClockTime(String? iso, String zone) {
  final t = _inZone(iso, zone);
  return t == null ? '—' : '${_clock(t)} ${zoneLabel(zone)}';
}

/// "05:30" (24-hour, company zone, no zone suffix); null/empty -> "—".
String formatClock24(String? iso, String zone) {
  final t = _inZone(iso, zone);
  return t == null ? '—' : '${t.hour.toString().padLeft(2, '0')}:${t.minute.toString().padLeft(2, '0')}';
}

/// "Oct 1, 2026, 5:30 am IST"; null/empty -> "—".
String formatDateTime(String? iso, String zone) {
  final t = _inZone(iso, zone);
  return t == null ? '—' : '${_months[t.month - 1]} ${t.day}, ${t.year}, ${_clock(t)} ${zoneLabel(zone)}';
}

String _date(tz.TZDateTime t) => '${t.year.toString().padLeft(4, '0')}-${t.month.toString().padLeft(2, '0')}-${t.day.toString().padLeft(2, '0')}';

/// The date (YYYY-MM-DD) of the instant [iso] in [zone]; null if [iso] is empty or unparsable.
String? dateInZone(String? iso, String zone) {
  final t = _inZone(iso, zone);
  return t == null ? null : _date(t);
}

/// The current business date (YYYY-MM-DD) in [zone] — never the device's date.
String businessToday(String zone, {DateTime? now}) => _date(tz.TZDateTime.from(now ?? DateTime.now(), _location(zone)));

/// [businessToday] shifted by [days] (negative = past), as YYYY-MM-DD.
String businessDayOffset(String zone, int days, {DateTime? now}) {
  final t = tz.TZDateTime.from(now ?? DateTime.now(), _location(zone));
  return _date(tz.TZDateTime(t.location, t.year, t.month, t.day + days));
}

/// Interprets a `YYYY-MM-DDTHH:mm[:ss]` wall-clock string as time *in [zone]* and returns the UTC
/// instant — correct across DST, and independent of the device's own zone.
String wallTimeToUtcIso(String local, String zone) {
  final m = RegExp(r'^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})(?::(\d{2}))?$').firstMatch(local);
  if (m == null) throw FormatException('not a local date-time', local);
  final t = tz.TZDateTime(_location(zone), int.parse(m[1]!), int.parse(m[2]!), int.parse(m[3]!), int.parse(m[4]!), int.parse(m[5]!), int.parse(m[6] ?? '0'));
  return t.toUtc().toIso8601String();
}

/// Current wall-clock time in [zone] as `YYYY-MM-DDTHH:mm` (to seed a date-time field).
String nowInZoneForInput(String zone, {DateTime? now}) {
  final t = tz.TZDateTime.from(now ?? DateTime.now(), _location(zone));
  return '${_date(t)}T${t.hour.toString().padLeft(2, '0')}:${t.minute.toString().padLeft(2, '0')}';
}

/// Every IANA zone the tz database knows, sorted — the options for a timezone picker. (The
/// backend validates against `zoneinfo.available_timezones()`, which this list covers.)
List<String> allTimeZones() {
  initTimeZones();
  return tz.timeZoneDatabase.locations.keys.where((k) => k.contains('/') || k == 'UTC').toList()..sort();
}
