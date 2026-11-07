import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../core/api/api_error.dart';
import '../../../core/providers.dart';
import '../../../core/widgets/ui.dart';
import '../domain/calendar_views.dart';

const _weekdayHeaders = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];

/// Cell colours per presentation, from the theme's tones (web: danger / primary / muted / warning).
({Color fg, Color bg})? _tone(BuildContext context, String key) => switch (key) {
      'SHUTDOWN' => toneColors(context, Tone.danger),
      'HOLIDAY' => toneColors(context, Tone.accent),
      'WEEKLY_OFF' => toneColors(context, Tone.neutral),
      'SPECIAL_WORKING' => toneColors(context, Tone.warning),
      _ => null,
    };

/// A work calendar's month of day types — mirrors the Calendar tab of web
/// `work-calendars/[id]/page.tsx` (`GET /work-calendars/{id}/days`, whole weeks, one request).
/// Tapping a day shows its full label and detail, which web prints inside each cell.
class WorkCalendarMonthView extends ConsumerStatefulWidget {
  const WorkCalendarMonthView({super.key, required this.calendar, this.now});
  final Rec calendar;

  /// For tests; defaults to the device's current month, as on web.
  final DateTime? now;

  @override
  ConsumerState<WorkCalendarMonthView> createState() => _WorkCalendarMonthViewState();
}

class _WorkCalendarMonthViewState extends ConsumerState<WorkCalendarMonthView> {
  late DateTime _month = DateTime.utc((widget.now ?? DateTime.now()).year, (widget.now ?? DateTime.now()).month);
  Rec? _data;
  ApiError? _error;
  bool _loading = false;
  int _request = 0;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    final mine = ++_request;
    final range = monthGridRange(_month.year, _month.month);
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final data = await ref.read(apiClientProvider).get<Rec>('/work-calendars/${widget.calendar['id']}/days?from=${range.from}&to=${range.to}', parse: (d) => d as Rec);
      if (mounted && mine == _request) setState(() => _data = data);
    } catch (e) {
      if (mounted && mine == _request) {
        setState(() {
          _data = null;
          _error = e is ApiError ? e : ApiError(status: 0, code: 'UNKNOWN_ERROR', message: 'Something went wrong.');
        });
      }
    } finally {
      if (mounted && mine == _request) setState(() => _loading = false);
    }
  }

  void _shift(int delta) {
    setState(() => _month = DateTime.utc(_month.year, _month.month + delta));
    _load();
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final muted = TextStyle(fontSize: 12, color: theme.colorScheme.onSurfaceVariant);
    final data = _data;
    final restrictedOff = (data ?? widget.calendar)['restricted_holidays_are_off_by_default'] == true;
    return DetailSection(
      title: 'Calendar',
      children: [
        Row(children: [
          IconButton(tooltip: 'Previous month', onPressed: _loading ? null : () => _shift(-1), icon: const Icon(Icons.chevron_left_rounded)),
          Expanded(
            child: Semantics(
              liveRegion: true,
              child: Text('${monthNames[_month.month - 1]} ${_month.year}', textAlign: TextAlign.center, style: theme.textTheme.titleSmall),
            ),
          ),
          IconButton(tooltip: 'Next month', onPressed: _loading ? null : () => _shift(1), icon: const Icon(Icons.chevron_right_rounded)),
        ]),
        if (widget.calendar['is_active'] == false) const Align(alignment: Alignment.centerLeft, child: StatusChip(label: 'Inactive calendar', dot: false)),
        Text(
          'This is how this work calendar classifies each date. A company-wide default only applies once a calendar is assigned and in effect; '
          'check guided setup for the activation status. '
          'Optional and restricted holidays remain working days'
          '${restrictedOff ? ' unless this calendar treats them as off (it currently does).' : ' (this calendar does not treat them as off).'}',
          style: muted,
        ),
        Align(
          alignment: Alignment.centerLeft,
          child: TextButton(onPressed: () => GoRouter.of(context).push('/app/work-calendars/setup'), child: const Text('Guided setup')),
        ),
        const DayLegend(),
        const SizedBox(height: 10),
        if (_loading)
          const Padding(padding: EdgeInsets.all(16), child: Center(child: CircularProgressIndicator(semanticsLabel: 'Loading calendar…')))
        else if (_error != null)
          Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text(_error!.status == 403 ? 'You do not have permission to view this calendar.' : _error!.message, style: TextStyle(color: theme.colorScheme.error)),
            TextButton(onPressed: _load, child: const Text('Try again')),
          ])
        else if (data != null) ...[
          if ((data['days'] as List? ?? const []).isEmpty) const Text('No data for this date range.') else WorkCalendarDayGrid(days: [for (final d in data['days'] as List) d as Rec], highlightMonth: _month.month),
          if ((data['days'] as List? ?? const []).isNotEmpty && (data['holiday_calendar_ids'] as List? ?? const []).isEmpty)
            Padding(padding: const EdgeInsets.only(top: 6), child: Text('No holiday calendar is linked to this work calendar, so no holidays are shown.', style: muted)),
        ],
      ],
    );
  }
}

/// Web's legend for the day grid.
class DayLegend extends StatelessWidget {
  const DayLegend({super.key});

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    return Wrap(spacing: 12, runSpacing: 6, children: [
      for (final (glyph, label, key) in dayLegend)
        Row(mainAxisSize: MainAxisSize.min, children: [
          Container(
            width: 20,
            height: 20,
            alignment: Alignment.center,
            decoration: BoxDecoration(
              color: _tone(context, key)?.bg ?? scheme.surface,
              border: Border.all(color: _tone(context, key)?.fg.withValues(alpha: 0.4) ?? scheme.outlineVariant),
              borderRadius: BorderRadius.circular(4),
            ),
            child: Text(glyph, style: TextStyle(fontSize: 11, fontWeight: FontWeight.w700, color: _tone(context, key)?.fg)),
          ),
          const SizedBox(width: 4),
          Text(label, style: const TextStyle(fontSize: 12)),
        ]),
    ]);
  }
}

/// Monday-first weeks covering the given days (web `DayGrid`); dates outside the data show as not
/// loaded, and days outside [highlightMonth] (1–12) are dimmed. Tapping a day shows its full
/// label and detail.
class WorkCalendarDayGrid extends StatelessWidget {
  const WorkCalendarDayGrid({super.key, required this.days, this.highlightMonth});
  final List<Rec> days;
  final int? highlightMonth;

  void _showDay(BuildContext context, String iso, Rec? day) {
    final view = day == null ? null : presentDay(day);
    showModalBottomSheet<void>(
      context: context,
      showDragHandle: true,
      builder: (ctx) => SafeArea(
        child: Padding(
          padding: const EdgeInsets.fromLTRB(20, 0, 20, 20),
          child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text(iso, style: Theme.of(ctx).textTheme.titleMedium),
            const SizedBox(height: 6),
            Text(view == null ? 'Not loaded' : view.label, style: const TextStyle(fontWeight: FontWeight.w600)),
            if (view?.detail != null) Padding(padding: const EdgeInsets.only(top: 4), child: Text(view!.detail!)),
          ]),
        ),
      ),
    );
  }

  Widget _cell(BuildContext context, String iso, Rec? day) {
    final scheme = Theme.of(context).colorScheme;
    final view = day == null ? null : presentDay(day);
    final tone = view == null ? null : _tone(context, view.key);
    final dimmed = highlightMonth != null && int.parse(iso.substring(5, 7)) != highlightMonth;
    return Semantics(
      button: true,
      label: view == null ? '$iso: not loaded' : '$iso: ${view.label}${view.detail != null ? ', ${view.detail}' : ''}',
      excludeSemantics: true,
      child: InkWell(
        onTap: () => _showDay(context, iso, day),
        borderRadius: BorderRadius.circular(8),
        child: Opacity(
          opacity: dimmed ? 0.45 : 1,
          child: Container(
            height: 48,
            padding: const EdgeInsets.all(4),
            decoration: BoxDecoration(
              color: tone?.bg ?? (view == null ? scheme.surfaceContainerHighest.withValues(alpha: 0.4) : scheme.surface),
              border: Border.all(color: tone?.fg.withValues(alpha: 0.4) ?? scheme.outlineVariant),
              borderRadius: BorderRadius.circular(8),
            ),
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text('${int.parse(iso.substring(8, 10))}', style: TextStyle(fontSize: 12, fontWeight: FontWeight.w600, color: view == null ? scheme.outline : scheme.onSurface)),
              const Spacer(),
              if (view != null) Align(alignment: Alignment.bottomRight, child: Text(view.glyph, style: TextStyle(fontSize: 12, fontWeight: FontWeight.w800, color: tone?.fg ?? scheme.onSurfaceVariant))),
            ]),
          ),
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    if (days.isEmpty) return const SizedBox.shrink();
    final byDate = {for (final d in days) '${d['date']}': d};
    final range = weekRange('${days.first['date']}', '${days.last['date']}');
    final dates = gridDates(range.from, range.to);
    final muted = TextStyle(fontSize: 11, fontWeight: FontWeight.w600, color: Theme.of(context).colorScheme.onSurfaceVariant);
    return Column(children: [
      Row(children: [for (final h in _weekdayHeaders) Expanded(child: Center(child: Text(h.toUpperCase(), style: muted)))]),
      const SizedBox(height: 4),
      for (var w = 0; w < dates.length; w += 7)
        Padding(
          padding: const EdgeInsets.only(bottom: 4),
          child: Row(children: [
            for (final iso in dates.sublist(w, w + 7)) Expanded(child: Padding(padding: const EdgeInsets.symmetric(horizontal: 2), child: _cell(context, iso, byDate[iso]))),
          ]),
        ),
    ]);
  }
}
