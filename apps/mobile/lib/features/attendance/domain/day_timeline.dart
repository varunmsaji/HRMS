import '../data/attendance_repository.dart';

/// The day's punches and break events in one list — web `buildTimeline` in
/// `apps/web/src/lib/attendance/day-detail.ts`.

enum TimelineKind { punchIn, punchOut, breakStart, breakEnd, missingOut }

class TimelineItem {
  const TimelineItem({required this.key, required this.time, required this.kind, required this.label, this.source});
  final String key;

  /// UTC instant; null for the missing punch-out marker.
  final String? time;
  final TimelineKind kind;
  final String label;

  /// Where the record came from, e.g. "Web", "Regularization".
  final String? source;
}

/// `BreakEventRead` from `GET /attendance/breaks/day` — only what the timeline shows.
class BreakEvent {
  const BreakEvent({required this.id, required this.eventType, required this.eventTime, this.breakName, required this.source});
  final String id;
  final String eventType;
  final String eventTime;
  final String? breakName;
  final String source;

  factory BreakEvent.fromJson(Map<String, dynamic> json) => BreakEvent(
        id: json['id'] as String,
        eventType: json['event_type'] as String,
        eventTime: json['event_time'] as String,
        breakName: json['break_name'] as String?,
        source: json['source'] as String,
      );
}

const _sourceLabels = {
  'WEB': 'Web',
  'MOBILE': 'Mobile app',
  'DEVICE': 'Device',
  'IMPORT': 'Import',
  'ADMIN': 'Entered by HR',
  'API': 'API',
  'REGULARIZATION': 'Correction',
};

String? sourceLabel(String? source) {
  if (source == null || source.isEmpty) return null;
  return _sourceLabels[source] ?? source[0] + source.substring(1).toLowerCase();
}

/// The ids of the punches the backend assigned to this day
/// (`computation_snapshot.inputs.punch_ids`), or `null` when the row carries none.
Set<String>? ownedPunchIds(AttendanceDay day) {
  final snapshot = day.raw['computation_snapshot'];
  if (snapshot is! Map) return null;
  final inputs = snapshot['inputs'];
  if (inputs is! Map) return null;
  final ids = inputs['punch_ids'];
  if (ids is! List) return null;
  return {for (final id in ids) if (id is String) id};
}

/// Punches that belong to this day. The backend decides ownership (shift window, overnight shifts,
/// the company's business date) and records it on the row, so the screen shows exactly that set
/// instead of re-deriving it. A day that has never been calculated has no owned set; the fetched
/// list is shown as is.
List<Punch> punchesForDay(List<Punch> punches, AttendanceDay day) {
  final owned = ownedPunchIds(day);
  if (owned == null) return punches;
  return [for (final p in punches) if (owned.contains(p.id)) p];
}

/// One chronological list of the day's punches and break events; a day flagged with a missing
/// punch ends with an explicit gap marker instead of silently stopping.
List<TimelineItem> buildTimeline(AttendanceDay day, List<Punch> punches, List<BreakEvent> breakEvents) {
  final items = <TimelineItem>[
    for (final p in punchesForDay(punches, day))
      TimelineItem(
        key: 'p-${p.id}',
        time: p.punchTime,
        kind: p.direction == 'IN' ? TimelineKind.punchIn : TimelineKind.punchOut,
        label: p.direction == 'IN' ? 'Punched in' : 'Punched out',
        source: sourceLabel(p.source),
      ),
    // The API sends "" for an event with no time; there is nowhere to place it.
    for (final e in breakEvents)
      if (e.eventTime.isNotEmpty)
      TimelineItem(
        key: 'b-${e.id}',
        time: e.eventTime,
        kind: e.eventType == 'START' ? TimelineKind.breakStart : TimelineKind.breakEnd,
        label: '${e.eventType == 'START' ? 'Break started' : 'Break ended'}${e.breakName != null && e.breakName!.isNotEmpty ? ' — ${e.breakName}' : ''}',
        source: sourceLabel(e.source),
      ),
  ];
  // Compare instants, not strings: punches and break events may not share one offset format.
  items.sort((a, b) => DateTime.parse(a.time!).compareTo(DateTime.parse(b.time!)));
  final punchesOnly = items.where((i) => i.kind == TimelineKind.punchIn || i.kind == TimelineKind.punchOut);
  final last = punchesOnly.isEmpty ? null : punchesOnly.last;
  if (day.raw['missing_punch'] == true && (last == null || last.kind == TimelineKind.punchIn)) {
    items.add(const TimelineItem(key: 'missing-out', time: null, kind: TimelineKind.missingOut, label: 'Punch-out missing'));
  }
  return items;
}
