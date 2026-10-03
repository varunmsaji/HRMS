import 'package:flutter_test/flutter_test.dart';
import 'package:hrms_mobile/core/time.dart';

void main() {
  test('formatMinutes', () {
    expect(formatMinutes(null), '—');
    expect(formatMinutes(0), '0h 0m');
    expect(formatMinutes(125), '2h 5m');
    expect(formatMinutes(-30), '-0h 30m');
  });

  test('zoneLabel shortens only the India zone', () {
    expect(zoneLabel('Asia/Kolkata'), 'IST');
    expect(zoneLabel('Asia/Calcutta'), 'IST');
    expect(zoneLabel('Europe/London'), 'Europe/London');
  });

  test('times render in the company zone regardless of the device zone', () {
    // 03:30 UTC is 09:00 in Kolkata
    expect(formatClockTime('2026-10-01T03:30:00Z', 'Asia/Kolkata'), '9:00 am IST');
    expect(formatDateTime('2026-10-01T03:30:00Z', 'Asia/Kolkata'), 'Oct 1, 2026, 9:00 am IST');
    // 18:30 UTC on the 30th is already the 1st, 00:00 in Kolkata
    expect(formatDateTime('2026-09-30T18:30:00Z', 'Asia/Kolkata'), 'Oct 1, 2026, 12:00 am IST');
    expect(formatClockTime('2026-10-01T15:05:00Z', 'Asia/Kolkata'), '8:35 pm IST');
    expect(formatDateTime(null, 'Asia/Kolkata'), '—');
    expect(formatDateTime('garbage', 'Asia/Kolkata'), '—');
    expect(formatClockTime('2026-10-01T03:30:00Z', 'Nowhere/Land'), '3:30 am Nowhere/Land'); // unknown zone -> UTC, labelled honestly
  });

  test('the business date is the zone\'s date, not the UTC date', () {
    // 20:00 UTC on Sep 30 is 01:30 on Oct 1 in Kolkata — the UTC date would be a day behind
    final now = DateTime.utc(2026, 9, 30, 20, 0);
    expect(businessToday('Asia/Kolkata', now: now), '2026-10-01');
    expect(businessToday('UTC', now: now), '2026-09-30');
    expect(businessDayOffset('Asia/Kolkata', -13, now: now), '2026-09-18');
    expect(businessDayOffset('Asia/Kolkata', 1, now: DateTime.utc(2026, 12, 31, 20)), '2027-01-02');
  });

  test('wall time in a zone converts to the right UTC instant', () {
    expect(wallTimeToUtcIso('2026-09-15T09:00', 'Asia/Kolkata'), '2026-09-15T03:30:00.000Z');
    expect(wallTimeToUtcIso('2026-09-15T00:15:30', 'Asia/Kolkata'), '2026-09-14T18:45:30.000Z');
    // DST: London is UTC+1 in summer, UTC+0 in winter
    expect(wallTimeToUtcIso('2026-07-01T09:00', 'Europe/London'), '2026-07-01T08:00:00.000Z');
    expect(wallTimeToUtcIso('2026-12-01T09:00', 'Europe/London'), '2026-12-01T09:00:00.000Z');
    expect(() => wallTimeToUtcIso('nope', 'Asia/Kolkata'), throwsFormatException);
  });

  test('nowInZoneForInput seeds a date-time field from the zone\'s clock', () {
    expect(nowInZoneForInput('Asia/Kolkata', now: DateTime.utc(2026, 9, 30, 20, 0)), '2026-10-01T01:30');
  });
}
