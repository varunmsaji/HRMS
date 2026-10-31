import 'package:flutter/material.dart';

import '../../../features/attendance/data/attendance_repository.dart';
import '../../../features/attendance/domain/today_state.dart';
import '../../../features/attendance/presentation/attendance_summary.dart';
import '../../theme/employee_tokens.dart';
import '../../time.dart';
import 'employee_status_chip.dart';
import 'layout.dart';
import 'status_map.dart';

/// The one sentence that describes a [TodayState], used by the panel and as its screen-reader label.
/// Wording follows API matrix §5.3. It never says "Absent" for today, never invents a status,
/// and never turns a missing row into a fact about the employee.
String todayHeadline(TodayState state, String zone) {
  final last = state.lastPunch;
  String punchFact(String verb) {
    final at = formatClockTime(last?.punchTime, zone);
    return switch (state.lastPunchDay) {
      PunchDay.today => '$verb at $at',
      PunchDay.yesterday => '$verb yesterday at $at',
      PunchDay.earlier => '$verb on ${formatDateTime(last?.punchTime, zone)}',
    };
  }

  switch (state.kind) {
    case TodayStateKind.noEmployee:
      return 'No employee record is linked to your account.';
    case TodayStateKind.loading:
      return 'Loading today\'s status';
    case TodayStateKind.noData:
      return 'No attendance recorded yet today.';
    case TodayStateKind.notPunchedIn:
      return 'Not punched in yet.';
    case TodayStateKind.punchedIn:
      return punchFact('Punched in');
    case TodayStateKind.punchedOut:
      return punchFact('Punched out');
    case TodayStateKind.calculating:
      return last == null ? 'Attendance is being calculated.' : punchFact(last.direction == 'IN' ? 'Punched in' : 'Punched out');
    case TodayStateKind.calculationFailed:
      return 'We couldn\'t calculate this day. Contact HR.';
    case TodayStateKind.notWorkingDay:
      final day = state.day;
      final name = day?.raw['holiday_name'] as String?;
      if (day?.raw['calendar_day_type'] == 'HOLIDAY') return name == null ? 'Holiday' : 'Holiday: $name';
      return day?.raw['calendar_day_type'] == 'WEEKLY_OFF' ? 'Weekly off' : 'Not a working day';
    case TodayStateKind.onLeave:
      return 'On leave';
    case TodayStateKind.unavailable:
      return 'Today\'s status is unavailable.';
    case TodayStateKind.partial:
      return 'Showing what is recorded for today.';
    case TodayStateKind.recorded:
      return 'Today is recorded.';
    case TodayStateKind.notEmployed:
      return 'Not employed on this date.';
  }
}

/// Exceptions on a calculated day, as short labels. Only what the day row itself says.
List<String> todayExceptions(AttendanceDay day) {
  final raw = day.raw;
  return [
    if (raw['missing_punch'] == true) 'Missing punch',
    if (raw['is_late'] == true || (day.lateMinutes ?? 0) > 0) (day.lateMinutes ?? 0) > 0 ? 'Late ${day.lateMinutes}m' : 'Late',
    if (raw['is_early_out'] == true) 'Left early',
    if (raw['is_pending_approval'] == true) 'Pending approval',
    if (raw['is_regularized'] == true) 'Regularized',
    if (raw['worked_on_holiday'] == true) 'Worked on holiday',
    if (raw['worked_on_weekly_off'] == true) 'Worked on weekly off',
    if (raw['work_on_leave_flagged'] == true && raw['work_on_leave_resolution'] == null) 'Punched on leave',
  ];
}

/// "Scheduled 9:30 am – 6:30 pm IST" (or, [compact], "Shift 09:30 – 18:30") from a day row's scheduled times, or null. This is the schedule the
/// engine used for that day (the shift's name is not readable by an employee: `/shifts` needs
/// `ORG.SHIFT.MANAGE`), not an attendance claim, so it is safe to show even for a provisional row.
String? scheduleCaption(AttendanceDay? day, String zone, {bool compact = false}) {
  final start = day?.raw['scheduled_start'] as String?;
  final end = day?.raw['scheduled_end'] as String?;
  if (start == null || end == null) return null;
  if (compact) return 'Shift ${formatClock24(start, zone)} – ${formatClock24(end, zone)}';
  final zoneText = ' ${zoneLabel(zone)}';
  final s = formatClockTime(start, zone);
  final e = formatClockTime(end, zone);
  return 'Scheduled ${s.endsWith(zoneText) ? s.substring(0, s.length - zoneText.length) : s} – $e';
}

/// Today's attendance, in one of the states of API matrix §5.3 (T1-05). Pure presentation of a
/// [TodayState]: it calculates nothing and hides every field the resolver withheld.
class TodayStatusPanel extends StatelessWidget {
  const TodayStatusPanel({super.key, required this.state, required this.zone, this.onRetry, this.scheduleText, this.hero = false});

  final TodayState state;
  final String zone;

  /// Offered only for [TodayStateKind.unavailable].
  final VoidCallback? onRetry;

  /// Optional "Scheduled 9:30 am – 6:30 pm IST" line ([scheduleCaption]).
  final String? scheduleText;

  /// Home's layout: the first-in time as a large figure, the worked time beneath it, then the
  /// shift. Same facts and same withholding rules as the default layout; only the arrangement differs.
  final bool hero;

  @override
  Widget build(BuildContext context) {
    final t = EmployeeTokens.of(context);
    final theme = Theme.of(context);
    final headline = todayHeadline(state, zone);

    if (state.kind == TodayStateKind.loading) {
      return _shell(t, Semantics(label: headline, child: const Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        SkeletonBlock(width: 96, height: 20, radius: 10),
        SizedBox(height: 12),
        SkeletonBlock(width: 200, height: 18),
        SizedBox(height: 8),
        SkeletonBlock(width: 140),
      ])));
    }

    final day = state.day;
    var chip = (state.showRowStatus && day != null) ? statusForAttendanceBucket(attendanceBucketOf(day)) : null;
    // The sentence already says it ("On leave", "Weekly off"): no second, identical label.
    if (chip != null && chip.label == headline) chip = null;
    final facts = <(String, String)>[
      if (day != null && state.showRowStatus && day.actualFirstIn != null) ('First in', formatClockTime(day.actualFirstIn, day.timezone)),
      if (day != null && state.showRowStatus && day.actualLastOut != null) ('Last out', formatClockTime(day.actualLastOut, day.timezone)),
      if (day != null && state.showWorked && day.workedMinutes != null) ('Worked', formatMinutes(day.workedMinutes)),
    ];
    // While the day is open the worked time is the engine's last calculation, labelled as such.
    final workedOpen = state.kind == TodayStateKind.punchedIn && day != null && state.showWorked && day.workedMinutes != null;
    final exceptions = (day != null && (state.showRowStatus || state.showWorked)) ? todayExceptions(day) : const <String>[];
    final caption = switch (state.kind) {
      TodayStateKind.calculating => 'Attendance is being calculated.',
      TodayStateKind.noData || TodayStateKind.notPunchedIn || TodayStateKind.unavailable => null,
      _ => null,
    };
    final large = MediaQuery.textScalerOf(context).scale(16) / 16 >= 1.4;
    final firstIn = (day != null && state.showRowStatus && day.actualFirstIn != null) ? formatClock24(day.actualFirstIn, day.timezone) : null;

    if (hero && firstIn != null) {
      final lastOut = (day != null && state.showRowStatus && day.actualLastOut != null) ? formatClock24(day.actualLastOut, day.timezone) : null;
      final worked = (day != null && state.showWorked && day.workedMinutes != null) ? formatMinutes(day.workedMinutes) : null;
      return _shell(
        t,
        Semantics(
          container: true,
          liveRegion: true,
          label: [headline, 'First in $firstIn', if (lastOut != null) 'Last out $lastOut', if (worked != null) '$worked ${workedOpen ? 'worked so far' : 'worked'}', if (scheduleText != null) scheduleText!, ...exceptions].join('. '),
          child: ExcludeSemantics(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                if (chip != null) ...[EmployeeStatusChip(status: chip), const SizedBox(height: 12)],
                Wrap(crossAxisAlignment: WrapCrossAlignment.end, spacing: 8, children: [
                  Text(firstIn, style: theme.textTheme.displaySmall?.copyWith(fontWeight: FontWeight.w700, height: 1.1)),
                  Padding(padding: const EdgeInsets.only(bottom: 6), child: Text('First in', style: theme.textTheme.bodyLarge?.copyWith(color: t.inkSecondary))),
                ]),
                if (worked != null) ...[const SizedBox(height: 8), Text('$worked ${workedOpen ? 'worked so far' : 'worked'}', style: theme.textTheme.titleMedium?.copyWith(fontWeight: FontWeight.w700))],
                if (lastOut != null) ...[const SizedBox(height: 4), Text('Last out $lastOut', style: theme.textTheme.bodyMedium?.copyWith(color: t.inkSecondary))],
                if (scheduleText != null) ...[const SizedBox(height: 4), Text(scheduleText!, style: theme.textTheme.bodyMedium?.copyWith(color: t.inkSecondary))],
                if (exceptions.isNotEmpty) ...[
                  const SizedBox(height: 8),
                  Wrap(spacing: 8, runSpacing: 6, children: [for (final e in exceptions) EmployeeStatusChip(status: (kind: StatusKind.warning, label: e, glyph: glyphFor(StatusKind.warning)))]),
                ],
              ],
            ),
          ),
        ),
      );
    }

    return _shell(
      t,
      Semantics(
        container: true,
        liveRegion: true,
        label: [headline, if (caption != null) caption, for (final f in facts) '${f.$1} ${f.$2}', ...exceptions].join('. '),
        child: ExcludeSemantics(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              if (chip != null) ...[EmployeeStatusChip(status: chip), const SizedBox(height: 12)],
              Text(headline, style: theme.textTheme.headlineSmall),
              if (caption != null) ...[const SizedBox(height: 4), Text(caption, style: theme.textTheme.bodySmall?.copyWith(color: t.inkSecondary))],
              if (scheduleText != null) ...[const SizedBox(height: 4), Text(scheduleText!, style: theme.textTheme.bodySmall?.copyWith(color: t.inkSecondary))],
              if (facts.isNotEmpty) ...[
                const SizedBox(height: 12),
                // Three figures side by side when they fit; stacked at large text or narrow widths.
                LayoutBuilder(builder: (context, c) {
                  final stack = large || c.maxWidth < 300;
                  final cells = [for (final f in facts) _Fact(label: f.$1 == 'Worked' && workedOpen ? 'Worked so far' : f.$1, value: f.$2)];
                  return stack
                      ? Column(crossAxisAlignment: CrossAxisAlignment.start, children: [for (final c in cells) Padding(padding: const EdgeInsets.only(bottom: 8), child: c)])
                      : Row(crossAxisAlignment: CrossAxisAlignment.start, children: [for (final c in cells) Expanded(child: c)]);
                }),
              ],
              if (exceptions.isNotEmpty) ...[
                const SizedBox(height: 8),
                Wrap(spacing: 8, runSpacing: 6, children: [for (final e in exceptions) EmployeeStatusChip(status: (kind: StatusKind.warning, label: e, glyph: glyphFor(StatusKind.warning)))]),
              ],
              if (state.kind == TodayStateKind.unavailable && onRetry != null) ...[
                const SizedBox(height: 8),
                TextButton(onPressed: onRetry, child: const Text('Reload status')),
              ],
            ],
          ),
        ),
      ),
    );
  }

  Widget _shell(EmployeeTokens t, Widget child) => Container(
        width: double.infinity,
        padding: const EdgeInsets.all(16),
        decoration: BoxDecoration(
          color: t.sheet,
          borderRadius: BorderRadius.circular(EmployeeTokens.radiusSurface),
          border: Border.all(color: t.line),
        ),
        child: child,
      );
}

class _Fact extends StatelessWidget {
  const _Fact({required this.label, required this.value});
  final String label;
  final String value;

  @override
  Widget build(BuildContext context) {
    final t = EmployeeTokens.of(context);
    final theme = Theme.of(context);
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Text(label, style: theme.textTheme.labelSmall?.copyWith(color: t.inkSecondary)),
      const SizedBox(height: 2),
      Text(value, style: theme.textTheme.bodyLarge?.copyWith(fontWeight: FontWeight.w600)),
    ]);
  }
}
