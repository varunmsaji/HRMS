import '../../../core/time.dart' show formatMinutes;

/// Why a day has its result, as the API wrote it (R-C01..C03; web `AttendanceDayExplanation`).
/// The app shows these words and never works them out. Only the single-day read carries one, and an
/// older API sends none, in which case [DayExplanation.tryParse] returns `null`.
class DayExplanation {
  const DayExplanation({
    required this.reason,
    required this.facts,
    required this.payLabel,
    this.overtimeLine,
    this.actionLine,
  });

  final String reason;
  final List<(String, String)> facts;
  final String payLabel;
  final String? overtimeLine;

  /// "Fix by 30 Nov. Counts as absent (unpaid) if not fixed." for a day still to be corrected.
  final String? actionLine;

  static DayExplanation? tryParse(Object? raw) {
    if (raw is! Map) return null;
    final reason = raw['reason'];
    if (reason is! String || reason.isEmpty) return null;
    final facts = <(String, String)>[
      for (final f in (raw['facts'] as List? ?? const []))
        if (f is Map && f['label'] is String && f['value'] is String) (f['label'] as String, f['value'] as String),
    ];
    final pay = raw['pay'];
    final ot = raw['overtime'];
    final action = raw['action'];
    return DayExplanation(
      reason: reason,
      facts: facts,
      payLabel: pay is Map && pay['label'] is String ? pay['label'] as String : 'No pay effect',
      overtimeLine: ot is Map ? _overtime(ot) : null,
      actionLine: action is Map ? _action(action) : null,
    );
  }

  static String _overtime(Map ot) {
    int n(String k) => (ot[k] as num?)?.toInt() ?? 0;
    final waiting = n('pending_min') > 0 ? ', ${formatMinutes(n('pending_min'))} waiting for approval' : '';
    return '${formatMinutes(n('found_min'))} found, ${formatMinutes(n('approved_min'))} approved$waiting';
  }

  static String _action(Map action) {
    final deadline = DateTime.tryParse('${action['deadline'] ?? ''}');
    final by = deadline == null ? '' : 'Fix by ${deadline.day} ${_months[deadline.month - 1]}. ';
    return '$by${action['consequence'] ?? ''}.';
  }

  static const _months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
}
