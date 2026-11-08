import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../core/api/api_error.dart';
import '../../../core/forms/choice_sources.dart';
import '../../../core/forms/form_spec.dart';
import '../../../core/providers.dart';
import '../../../core/theme/employee_tokens.dart';
import '../../../core/time.dart';
import '../../../core/widgets/ui.dart';
import '../../auth/state/auth_controller.dart';
import '../../shell/more_action.dart';
import '../data/schedule_repository.dart';
import '../domain/weekly_schedule.dart';

/// Weekly shift coverage — mirrors `apps/web/src/app/app/rosters/schedule/page.tsx`. A phone shows
/// one day at a time: pick a day in the strip, see each shift's headcount against its target.
/// Department and branch narrow the week, as on web; the four figures are web's KPI cards.
class WeeklyScheduleScreen extends ConsumerStatefulWidget {
  const WeeklyScheduleScreen({super.key});

  @override
  ConsumerState<WeeklyScheduleScreen> createState() => _WeeklyScheduleScreenState();
}

class _WeeklyScheduleScreenState extends ConsumerState<WeeklyScheduleScreen> {
  late final String _today;
  late String _weekStart;
  late String _selected;
  WeeklySchedule? _schedule;
  bool _loading = true;
  ApiError? _error;
  int _request = 0;
  String _departmentId = '';
  String _branchId = '';
  List<Choice> _departments = const [];
  List<Choice> _branches = const [];

  @override
  void initState() {
    super.initState();
    final zone = ref.read(authControllerProvider).user?.companyTimezone ?? 'Asia/Kolkata';
    _today = businessToday(zone);
    _weekStart = mondayOf(_today);
    _selected = _today;
    _load();
    _loadFilters();
  }

  /// Best effort, as on web: a viewer who can't list them just gets no filter.
  Future<void> _loadFilters() async {
    try {
      final set = await loadChoicesTolerant(ref.read(apiClientProvider), optional: const ['departments', 'branches']);
      if (!mounted) return;
      setState(() {
        _departments = set.choices['departments'] ?? const [];
        _branches = set.choices['branches'] ?? const [];
      });
    } catch (_) {}
  }

  void _filter({String? department, String? branch}) {
    setState(() {
      if (department != null) _departmentId = department;
      if (branch != null) _branchId = branch;
    });
    _load();
  }

  Future<void> _load() async {
    final mine = ++_request;
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final schedule = await ref.read(scheduleRepositoryProvider).weeklySchedule(weekStart: _weekStart, branchId: _branchId, departmentId: _departmentId);
      if (!mounted || mine != _request) return;
      setState(() => _schedule = schedule);
    } catch (e) {
      if (!mounted || mine != _request) return;
      setState(() {
        _schedule = null;
        _error = e is ApiError ? e : ApiError(status: 0, code: 'UNKNOWN_ERROR', message: 'Something went wrong.');
      });
    } finally {
      if (mounted && mine == _request) setState(() => _loading = false);
    }
  }

  void _goToWeek(String monday) {
    setState(() {
      _weekStart = monday;
      // Keep the same weekday selected, or today when we come back to this week.
      _selected = monday == mondayOf(_today) ? _today : monday;
    });
    _load();
  }

  @override
  Widget build(BuildContext context) {
    final schedule = _schedule;
    final pending = schedule?.totals.pendingSwaps ?? 0;
    return Scaffold(
      appBar: AppBar(
        title: const Text('Schedule coverage'),
        actions: [
          IconButton(
            tooltip: pending > 0 ? 'Shift swaps, $pending pending' : 'Shift swaps',
            icon: Badge(isLabelVisible: pending > 0, label: Text('$pending'), child: const Icon(Icons.swap_horiz_rounded)),
            onPressed: () => context.push('/app/shift-swaps'),
          ),
          const MoreAction(),
        ],
      ),
      body: Column(children: [
        _WeekBar(
          label: weekRangeLabel(_weekStart, addDaysIso(_weekStart, 6)),
          isThisWeek: _weekStart == mondayOf(_today),
          onPrevious: () => _goToWeek(addDaysIso(_weekStart, -7)),
          onNext: () => _goToWeek(addDaysIso(_weekStart, 7)),
          onToday: () => _goToWeek(mondayOf(_today)),
        ),
        if (_departments.isNotEmpty || _branches.isNotEmpty)
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 4, 16, 4),
            child: Row(children: [
              if (_departments.isNotEmpty)
                Expanded(child: _FilterSelect(label: 'Department', allLabel: 'All Departments (${_departments.length})', value: _departmentId, options: _departments, onChanged: (v) => _filter(department: v))),
              if (_departments.isNotEmpty && _branches.isNotEmpty) const SizedBox(width: 8),
              if (_branches.isNotEmpty)
                Expanded(child: _FilterSelect(label: 'Branch', allLabel: 'All Branches (${_branches.length})', value: _branchId, options: _branches, onChanged: (v) => _filter(branch: v))),
            ]),
          ),
        Expanded(
          child: _loading && schedule == null
              ? const ListSkeleton()
              : _error != null
                  ? StateMessage(
                      icon: Icons.error_outline_rounded,
                      tone: Tone.danger,
                      title: _error!.status == 403 ? 'No access' : 'Something went wrong',
                      message: _error!.status == 403 ? 'You do not have permission to view the schedule.' : _error!.message,
                      actionLabel: _error!.status == 403 ? null : 'Retry',
                      onAction: _load,
                    )
                  : schedule == null
                      ? const SizedBox.shrink()
                      : RefreshIndicator(onRefresh: _load, child: _body(schedule)),
        ),
      ]),
    );
  }

  Widget _body(WeeklySchedule schedule) {
    final onDay = schedule.onDay(_selected);
    return ListView(
      padding: const EdgeInsets.fromLTRB(16, 4, 16, 24),
      children: [
        _Totals(totals: schedule.totals),
        const _CoverageExplainer(),
        const SizedBox(height: 4),
        if (schedule.totals.rosteredStaff == 0)
          const SizedBox(height: 240, child: StateMessage(icon: Icons.groups_outlined, tone: Tone.neutral, title: 'No one is rostered for this week.', message: 'Publish roster entries for this week and they will appear here.'))
        else ...[
          _DayStrip(
            schedule: schedule,
            selected: _selected,
            today: _today,
            onSelect: (d) => setState(() => _selected = d),
          ),
          const SizedBox(height: 12),
          Text(_selected == _today ? 'Today · ${longDay(_selected)}' : longDay(_selected), style: Theme.of(context).textTheme.titleMedium?.copyWith(fontWeight: FontWeight.w700)),
          const SizedBox(height: 8),
          if (onDay.isEmpty)
            const SizedBox(height: 240, child: StateMessage(icon: Icons.event_busy_outlined, tone: Tone.neutral, title: 'Nobody rostered', message: 'No one is on a published shift this day.'))
          else
            for (final entry in onDay) _ShiftCard(shift: entry.shift, cell: entry.cell),
        ],
      ],
    );
  }
}

class _WeekBar extends StatelessWidget {
  const _WeekBar({required this.label, required this.isThisWeek, required this.onPrevious, required this.onNext, required this.onToday});
  final String label;
  final bool isThisWeek;
  final VoidCallback onPrevious;
  final VoidCallback onNext;
  final VoidCallback onToday;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Padding(
      padding: const EdgeInsets.fromLTRB(8, 4, 8, 0),
      child: Row(children: [
        IconButton(tooltip: 'Previous week', icon: const Icon(Icons.chevron_left_rounded), onPressed: onPrevious),
        Expanded(
          child: Column(mainAxisSize: MainAxisSize.min, children: [
            Text(label, style: theme.textTheme.titleMedium?.copyWith(fontWeight: FontWeight.w700), textAlign: TextAlign.center),
            if (isThisWeek) Text('This week', style: theme.textTheme.bodySmall?.copyWith(color: theme.colorScheme.primary)) else TextButton(onPressed: onToday, child: const Text('Back to this week')),
          ]),
        ),
        IconButton(tooltip: 'Next week', icon: const Icon(Icons.chevron_right_rounded), onPressed: onNext),
      ]),
    );
  }
}

/// Web's four KPI cards, same figures and wording, two to a row.
class _Totals extends StatelessWidget {
  const _Totals({required this.totals});
  final ScheduleTotals totals;

  @override
  Widget build(BuildContext context) {
    final t = totals;
    final pct = t.coveragePct;
    final below = t.cellsBelowTarget;
    final cards = [
      _Kpi(
        label: 'Rostered staff',
        value: '${t.rosteredStaff}',
        badge: '${t.scheduledPct}% scheduled',
        hint: '${t.rosteredStaff} of ${t.activeHeadcount} active headcount assigned',
        tone: t.scheduledPct >= 100 ? Tone.success : Tone.warning,
      ),
      _Kpi(
        label: 'Coverage efficiency',
        value: pct == null ? '—' : '${pct.round()}%',
        badge: pct == null ? null : (below == 0 ? 'Optimal' : 'Needs attention'),
        hint: pct == null
            ? 'No shift has a minimum staffing target'
            : below == 0
                ? 'All minimum staffing thresholds met across ${t.shiftsWithTarget} shifts'
                : '$below shift ${below == 1 ? 'day is' : 'days are'} below its minimum',
        tone: pct == null ? Tone.neutral : (below == 0 ? Tone.success : Tone.warning),
      ),
      _Kpi(
        label: 'Night shift coverage',
        value: '${t.nightStaff} Staff',
        badge: t.nightShiftCount > 0 ? 'Active' : null,
        hint: t.nightShiftCount > 0 ? 'Rostered across ${t.nightShiftCount} night ${t.nightShiftCount == 1 ? 'shift' : 'shifts'} this week' : 'No night shift is configured',
        tone: t.nightShiftCount > 0 ? Tone.info : Tone.neutral,
      ),
      _Kpi(
        label: 'Shift swap requests',
        value: '${t.pendingSwaps}',
        badge: t.pendingSwaps > 0 ? 'Pending' : null,
        hint: t.pendingSwaps > 0 ? 'Peer swaps awaiting a supervisor decision' : 'Nothing is waiting for a decision',
        tone: t.pendingSwaps > 0 ? Tone.warning : Tone.neutral,
      ),
    ];
    return Column(children: [
      for (var i = 0; i < cards.length; i += 2)
        Padding(
          padding: const EdgeInsets.only(bottom: 8),
          child: IntrinsicHeight(
            child: Row(crossAxisAlignment: CrossAxisAlignment.stretch, children: [Expanded(child: cards[i]), const SizedBox(width: 8), Expanded(child: cards[i + 1])]),
          ),
        ),
    ]);
  }
}

/// Web's "What is schedule coverage?" panel, folded away on a phone.
class _CoverageExplainer extends StatelessWidget {
  const _CoverageExplainer();

  @override
  Widget build(BuildContext context) {
    final style = Theme.of(context).textTheme.bodySmall;
    Widget line(String term, String text) => Padding(
          padding: const EdgeInsets.only(top: 6),
          child: Text.rich(TextSpan(children: [TextSpan(text: term, style: const TextStyle(fontWeight: FontWeight.w700)), TextSpan(text: ' – $text')]), style: style),
        );
    return ExpansionTile(
      tilePadding: EdgeInsets.zero,
      childrenPadding: const EdgeInsets.only(bottom: 8),
      expandedCrossAxisAlignment: CrossAxisAlignment.start,
      title: const Text('What is schedule coverage?'),
      children: [
        Text(
          'Coverage tells you whether enough people are scheduled to work each shift. Every shift can have a minimum number of staff it needs. '
          'If fewer people are rostered than that minimum on a given day, that day is short-staffed.',
          style: style,
        ),
        line('Rostered staff', 'how many of your active employees have a shift assigned this week.'),
        line('Coverage efficiency', 'the share of shift days that have at least their minimum number of people. 100% means nobody is short.'),
        line('Night shift coverage', 'how many people are scheduled on night shifts this week.'),
        line('Shift swap requests', "employees who asked to swap shifts and are waiting for a manager's decision."),
      ],
    );
  }
}

class _FilterSelect extends StatelessWidget {
  const _FilterSelect({required this.label, required this.allLabel, required this.value, required this.options, required this.onChanged});
  final String label;
  final String allLabel;
  final String value;
  final List<Choice> options;
  final ValueChanged<String> onChanged;

  @override
  Widget build(BuildContext context) => DropdownButtonFormField<String>(
        value: value,
        isExpanded: true,
        decoration: InputDecoration(labelText: label, isDense: true, border: const OutlineInputBorder()),
        items: [
          DropdownMenuItem(value: '', child: Text(allLabel, overflow: TextOverflow.ellipsis)),
          for (final o in options) DropdownMenuItem(value: o.value, child: Text(o.label, overflow: TextOverflow.ellipsis)),
        ],
        onChanged: (v) => onChanged(v ?? ''),
      );
}

class _Kpi extends StatelessWidget {
  const _Kpi({required this.label, required this.value, required this.hint, required this.tone, this.badge});
  final String label;
  final String value;
  final String hint;
  final Tone tone;
  final String? badge;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final colors = toneColors(context, tone);
    return Semantics(
      label: '$label $value${badge == null ? '' : ', $badge'}. $hint',
      excludeSemantics: true,
      child: Container(
        padding: const EdgeInsets.all(12),
        decoration: BoxDecoration(color: colors.bg, borderRadius: BorderRadius.circular(EmployeeTokens.radiusSurface)),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(label, style: theme.textTheme.labelMedium?.copyWith(color: theme.colorScheme.onSurfaceVariant)),
          if (badge != null) Text(badge!, style: theme.textTheme.labelSmall?.copyWith(color: colors.fg, fontWeight: FontWeight.w700)),
          const SizedBox(height: 4),
          Text(value, style: theme.textTheme.headlineSmall?.copyWith(fontWeight: FontWeight.w800, color: colors.fg)),
          Text(hint, style: theme.textTheme.bodySmall?.copyWith(color: theme.colorScheme.onSurfaceVariant)),
        ]),
      ),
    );
  }
}

class _DayStrip extends StatelessWidget {
  const _DayStrip({required this.schedule, required this.selected, required this.today, required this.onSelect});
  final WeeklySchedule schedule;
  final String selected;
  final String today;
  final ValueChanged<String> onSelect;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Row(children: [
      for (final d in schedule.days)
        Expanded(
          child: Builder(builder: (context) {
            final cells = [for (final s in schedule.shifts) s.cellOn(d)].whereType<ScheduleCell>();
            final below = cells.any((c) => c.met == false);
            final swap = cells.any((c) => c.hasPendingSwap);
            final isSel = d == selected;
            final fg = isSel ? theme.colorScheme.onPrimary : theme.colorScheme.onSurface;
            return Semantics(
              button: true,
              selected: isSel,
              label: '${longDay(d)}${d == today ? ', today' : ''}${below ? ', below target' : ''}',
              excludeSemantics: true,
              child: InkWell(
                borderRadius: BorderRadius.circular(EmployeeTokens.radiusControl),
                onTap: () => onSelect(d),
                child: Container(
                  margin: const EdgeInsets.symmetric(horizontal: 2),
                  padding: const EdgeInsets.symmetric(vertical: 8),
                  decoration: BoxDecoration(
                    color: isSel ? theme.colorScheme.primary : theme.colorScheme.surfaceContainerLowest,
                    borderRadius: BorderRadius.circular(EmployeeTokens.radiusControl),
                    border: Border.all(color: d == today && !isSel ? theme.colorScheme.primary : theme.colorScheme.outlineVariant),
                  ),
                  child: Column(mainAxisSize: MainAxisSize.min, children: [
                    Text(weekdayShort(d), style: theme.textTheme.labelSmall?.copyWith(color: fg)),
                    const SizedBox(height: 2),
                    Text('${DateTime.parse(d).day}', style: theme.textTheme.titleSmall?.copyWith(color: fg, fontWeight: FontWeight.w700)),
                    const SizedBox(height: 4),
                    SizedBox(
                      height: 6,
                      child: Row(mainAxisSize: MainAxisSize.min, children: [
                        if (below) _dot(below && isSel ? theme.colorScheme.onPrimary : toneColors(context, Tone.warning).fg),
                        if (swap) _dot(isSel ? theme.colorScheme.onPrimary : toneColors(context, Tone.info).fg),
                      ]),
                    ),
                  ]),
                ),
              ),
            );
          }),
        ),
    ]);
  }

  Widget _dot(Color c) => Container(width: 6, height: 6, margin: const EdgeInsets.symmetric(horizontal: 1), decoration: BoxDecoration(color: c, shape: BoxShape.circle));
}

class _ShiftCard extends StatelessWidget {
  const _ShiftCard({required this.shift, required this.cell});
  final ScheduleShift shift;
  final ScheduleCell cell;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final min = shift.minStaff;
    final below = cell.met == false;
    final tone = min == null ? Tone.neutral : (below ? Tone.warning : Tone.success);
    return Padding(
      padding: const EdgeInsets.only(bottom: 10),
      child: AppCard(
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Row(children: [
            if (shift.isNight) Padding(padding: const EdgeInsets.only(right: 6), child: Icon(Icons.nights_stay_outlined, size: 18, color: theme.colorScheme.onSurfaceVariant)),
            Expanded(child: Text(shift.name, style: theme.textTheme.titleMedium?.copyWith(fontWeight: FontWeight.w700))),
            StatusChip(label: min == null ? '${cell.count} staff' : '${cell.count} of $min', tone: tone),
          ]),
          if (shift.timeRange.isNotEmpty) Padding(padding: const EdgeInsets.only(top: 2), child: Text(shift.timeRange, style: theme.textTheme.bodyMedium?.copyWith(color: theme.colorScheme.onSurfaceVariant))),
          if (below) Padding(padding: const EdgeInsets.only(top: 8), child: Text('Below the minimum of $min for this shift.', style: theme.textTheme.bodySmall?.copyWith(color: toneColors(context, Tone.warning).fg))),
          if (cell.hasPendingSwap) Padding(padding: const EdgeInsets.only(top: 6), child: Text('A swap request is pending.', style: theme.textTheme.bodySmall?.copyWith(color: toneColors(context, Tone.info).fg))),
          const SizedBox(height: 10),
          Wrap(spacing: 8, runSpacing: 6, children: [
            for (final p in cell.people)
              Chip(
                visualDensity: VisualDensity.compact,
                avatar: CircleAvatar(radius: 11, child: Text(p.initials, style: const TextStyle(fontSize: 10))),
                label: Text(p.name),
              ),
            if (cell.hidden > 0) Chip(visualDensity: VisualDensity.compact, label: Text('+${cell.hidden} more')),
          ]),
        ]),
      ),
    );
  }
}
