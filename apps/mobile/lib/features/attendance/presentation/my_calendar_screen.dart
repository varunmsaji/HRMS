import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api/api_error.dart';
import '../../../core/theme/employee_tokens.dart';
import '../../../core/time.dart';
import '../../../core/widgets/employee/status_map.dart';
import '../../../core/widgets/ui.dart';
import '../../auth/state/auth_controller.dart';
import '../data/schedule_repository.dart';
import '../domain/employee_calendar.dart';

/// The signed-in employee's own read-only calendar — mirrors `apps/web/src/app/app/me/calendar`.
/// The server works out who the employee is from the session. A phone cell is too small for the
/// web's text, so each day shows a glyph and tapping it opens the words.
class MyCalendarScreen extends ConsumerStatefulWidget {
  const MyCalendarScreen({super.key, this.now});

  /// Overrides the clock (tests, so "today" and the opening month are fixed). Null = now.
  final DateTime? now;

  @override
  ConsumerState<MyCalendarScreen> createState() => _MyCalendarScreenState();
}

/// Icon per kind of day, matching the web legend's symbols: colour is never the only signal. Icons
/// rather than text, because the app font does not carry all of those symbols.
const _dayIcons = {
  CalendarDayKind.working: Icons.fiber_manual_record,
  CalendarDayKind.weeklyOff: Icons.circle_outlined,
  CalendarDayKind.holiday: Icons.star_rounded,
  CalendarDayKind.specialWorking: Icons.diamond_rounded,
  CalendarDayKind.shutdown: Icons.close_rounded,
  CalendarDayKind.notSetUp: Icons.remove_rounded,
};
const _approvedIcon = Icons.check_rounded;
const _pendingIcon = Icons.question_mark_rounded;

StatusKind? _kindOf(CalendarDayKind kind) => switch (kind) {
      CalendarDayKind.specialWorking => StatusKind.warning,
      CalendarDayKind.shutdown => StatusKind.danger,
      CalendarDayKind.weeklyOff => StatusKind.neutral,
      _ => null,
    };

class _MyCalendarScreenState extends ConsumerState<MyCalendarScreen> {
  late final String _today;
  late String _month;
  EmployeeCalendar? _calendar;
  bool _loading = true;
  ApiError? _error;
  int _request = 0;

  bool get _hasEmployee => ref.read(authControllerProvider).user?.employeeId != null;

  @override
  void initState() {
    super.initState();
    final zone = ref.read(authControllerProvider).user?.companyTimezone ?? 'Asia/Kolkata';
    _today = businessToday(zone, now: widget.now);
    _month = _today.substring(0, 7);
    if (_hasEmployee) _load();
  }

  /// A slower answer for a month the user has left never overwrites the current one.
  Future<void> _load() async {
    final mine = ++_request;
    setState(() {
      _loading = true;
      _error = null;
      _calendar = null;
    });
    final range = monthGridRange(_month);
    try {
      final calendar = await ref.read(scheduleRepositoryProvider).getMyCalendar(from: range.from, to: range.to);
      if (mounted && mine == _request) setState(() => _calendar = calendar);
    } catch (e) {
      if (mounted && mine == _request) setState(() => _error = e is ApiError ? e : ApiError(status: 0, code: 'UNKNOWN_ERROR', message: 'Something went wrong.'));
    } finally {
      if (mounted && mine == _request) setState(() => _loading = false);
    }
  }

  void _goTo(String month) {
    setState(() => _month = month);
    _load();
  }

  void _openDay(EmployeeCalendarDay day) {
    final detail = day.detail;
    showModalBottomSheet<void>(
      context: context,
      showDragHandle: true,
      builder: (ctx) => SafeArea(
        child: Padding(
          padding: const EdgeInsets.fromLTRB(20, 0, 20, 20),
          child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text(formatLongIsoDate(day.date), style: Theme.of(ctx).textTheme.titleMedium),
            const SizedBox(height: 8),
            Text(day.label),
            if (detail != null) Padding(padding: const EdgeInsets.only(top: 4), child: Text(detail, style: TextStyle(color: EmployeeTokens.of(ctx).inkSecondary))),
            for (final l in day.leave)
              Padding(
                padding: const EdgeInsets.only(top: 8),
                child: Row(children: [
                  Icon(l.isApproved ? _approvedIcon : _pendingIcon, size: 16),
                  const SizedBox(width: 6),
                  Expanded(child: Text(l.label)),
                ]),
              ),
          ]),
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('My Calendar')),
      body: !_hasEmployee
          ? const StateMessage(icon: Icons.calendar_month_outlined, title: 'No employee record', message: 'Your account is not linked to an employee record, so there is no personal calendar to show.')
          : RefreshIndicator(
              onRefresh: _load,
              child: ListView(
                padding: const EdgeInsets.all(16),
                children: [
                  _MonthBar(
                    label: formatMonthKey(_month),
                    onPrevious: () => _goTo(shiftMonthKey(_month, -1)),
                    onNext: () => _goTo(shiftMonthKey(_month, 1)),
                    onThisMonth: _month == _today.substring(0, 7) ? null : () => _goTo(_today.substring(0, 7)),
                  ),
                  const SizedBox(height: 12),
                  ..._content(context),
                ],
              ),
            ),
    );
  }

  List<Widget> _content(BuildContext context) {
    final t = EmployeeTokens.of(context);
    if (_loading) return const [Padding(padding: EdgeInsets.all(32), child: Center(child: CircularProgressIndicator(strokeWidth: 2.5)))];
    if (_error != null) {
      return [StateMessage(icon: Icons.error_outline_rounded, tone: Tone.danger, title: "Couldn't load your calendar", message: _error!.status == 403 ? "You don't have permission to see this calendar." : _error!.message, actionLabel: 'Retry', onAction: _load)];
    }
    final calendar = _calendar;
    if (calendar == null) return const [];
    if (calendar.configuration == 'INCOMPLETE') {
      return const [StateMessage(icon: Icons.calendar_month_outlined, title: 'Your work calendar is not set up yet', message: 'No work calendar applies to you for this month. Please contact HR; until then, working days and holidays cannot be shown.')];
    }
    final summary = summariseCalendarMonth(calendar, _month);
    String plural(int n, String word) => '$n $word ${n == 1 ? 'day' : 'days'}';
    return [
      AppCard(
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          if (calendar.configuration == 'PARTIAL')
            Padding(
              padding: const EdgeInsets.only(bottom: 10),
              child: Text('A work calendar applies to you only for part of this month. Dates marked as not set up have no calendar yet.', style: TextStyle(color: t.warningText)),
            ),
          Text('${plural(summary.working, 'working')} · ${summary.nonWorking} non-working · ${plural(summary.approvedLeave, 'approved leave')} · ${plural(summary.pendingLeave, 'pending leave')}', style: TextStyle(fontSize: 13, color: t.inkSecondary)),
          if (!calendar.leaveIncluded) Padding(padding: const EdgeInsets.only(top: 4), child: Text('Leave is not shown for your account.', style: TextStyle(fontSize: 12, color: t.inkSecondary))),
          const SizedBox(height: 12),
          _MonthGrid(calendar: calendar, month: _month, today: _today, onDay: _openDay),
          const SizedBox(height: 12),
          const _Legend(),
        ]),
      ),
    ];
  }
}

class _MonthBar extends StatelessWidget {
  const _MonthBar({required this.label, required this.onPrevious, required this.onNext, required this.onThisMonth});
  final String label;
  final VoidCallback onPrevious;
  final VoidCallback onNext;
  final VoidCallback? onThisMonth;

  @override
  Widget build(BuildContext context) {
    return Column(children: [
      Row(children: [
        IconButton(onPressed: onPrevious, tooltip: 'Previous month', icon: const Icon(Icons.chevron_left)),
        Expanded(child: Text(label, textAlign: TextAlign.center, style: const TextStyle(fontWeight: FontWeight.w700))),
        IconButton(onPressed: onNext, tooltip: 'Next month', icon: const Icon(Icons.chevron_right)),
      ]),
      if (onThisMonth != null) TextButton(onPressed: onThisMonth, child: const Text('This month')),
    ]);
  }
}

class _MonthGrid extends StatelessWidget {
  const _MonthGrid({required this.calendar, required this.month, required this.today, required this.onDay});
  final EmployeeCalendar calendar;
  final String month;
  final String today;
  final ValueChanged<EmployeeCalendarDay> onDay;

  @override
  Widget build(BuildContext context) {
    final t = EmployeeTokens.of(context);
    final byDate = {for (final d in calendar.days) d.date: d};
    return GridView(
      shrinkWrap: true,
      physics: const NeverScrollableScrollPhysics(),
      // Cells grow with the text size so the numeral and glyphs never clip.
      gridDelegate: SliverGridDelegateWithFixedCrossAxisCount(crossAxisCount: 7, mainAxisExtent: 56 * MediaQuery.textScalerOf(context).scale(1)),
      children: [
        for (final w in const ['Mo', 'Tu', 'We', 'Th', 'Fr', 'Sa', 'Su']) Center(child: Text(w, style: TextStyle(fontSize: 11, color: t.inkSecondary, fontWeight: FontWeight.w600))),
        for (final date in datesBetween(calendar.fromDate, calendar.toDate))
          byDate[date] == null ? const SizedBox.shrink() : _DayCell(day: byDate[date]!, inMonth: date.startsWith(month), isToday: date == today, onTap: () => onDay(byDate[date]!)),
      ],
    );
  }
}

class _DayCell extends StatelessWidget {
  const _DayCell({required this.day, required this.inMonth, required this.isToday, required this.onTap});
  final EmployeeCalendarDay day;
  final bool inMonth;
  final bool isToday;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final t = EmployeeTokens.of(context);
    final kind = _kindOf(day.kind);
    final colors = kind == null ? null : statusColors(context, kind);
    final isHoliday = day.kind == CalendarDayKind.holiday;
    final number = int.parse(day.date.substring(8, 10));
    final spoken = [formatLongIsoDate(day.date), day.label, if (day.detail != null) day.detail!, for (final l in day.leave) l.label, if (isToday) 'today'].join(', ');
    return Opacity(
      opacity: inMonth ? 1 : 0.45,
      child: Semantics(
        label: spoken,
        button: true,
        excludeSemantics: true,
        child: InkWell(
          borderRadius: BorderRadius.circular(10),
          onTap: onTap,
          child: Container(
            margin: const EdgeInsets.all(2),
            decoration: BoxDecoration(
              color: isHoliday ? t.actionSubtle : colors?.fill,
              borderRadius: BorderRadius.circular(8),
              border: isToday ? Border.all(color: t.action, width: 1.5) : (day.kind == CalendarDayKind.notSetUp ? Border.all(color: t.line) : null),
            ),
            child: Column(mainAxisAlignment: MainAxisAlignment.center, children: [
              Text('$number', style: TextStyle(fontSize: 12, fontWeight: FontWeight.w700, color: t.ink)),
              FittedBox(
                fit: BoxFit.scaleDown,
                child: Row(mainAxisSize: MainAxisSize.min, children: [
                  Icon(_dayIcons[day.kind], size: day.kind == CalendarDayKind.working ? 5 : 12, color: isHoliday ? t.action : (colors?.glyph ?? t.inkSecondary)),
                  for (final l in day.leave) ...[
                    const SizedBox(width: 2),
                    Icon(l.isApproved ? _approvedIcon : _pendingIcon, size: 12, color: l.isApproved ? t.successText : t.warningText),
                  ],
                ]),
              ),
            ]),
          ),
        ),
      ),
    );
  }
}

class _Legend extends StatelessWidget {
  const _Legend();

  @override
  Widget build(BuildContext context) {
    final t = EmployeeTokens.of(context);
    final items = [
      (_dayIcons[CalendarDayKind.working]!, 5.0, 'Working day'),
      (_dayIcons[CalendarDayKind.weeklyOff]!, 12.0, 'Weekly off'),
      (_dayIcons[CalendarDayKind.holiday]!, 12.0, 'Holiday (non-working)'),
      (_dayIcons[CalendarDayKind.specialWorking]!, 12.0, 'Special working day'),
      (_dayIcons[CalendarDayKind.shutdown]!, 12.0, 'Shutdown'),
      (_dayIcons[CalendarDayKind.notSetUp]!, 12.0, 'Not set up'),
      (_approvedIcon, 12.0, 'Approved leave'),
      (_pendingIcon, 12.0, 'Pending leave (awaiting approval)'),
    ];
    return Wrap(spacing: 12, runSpacing: 4, children: [
      for (final (icon, size, label) in items)
        Row(mainAxisSize: MainAxisSize.min, children: [
          Icon(icon, size: size, color: t.inkSecondary),
          const SizedBox(width: 4),
          Flexible(child: Text(label, style: TextStyle(fontSize: 11, color: t.inkSecondary))),
        ]),
    ]);
  }
}
