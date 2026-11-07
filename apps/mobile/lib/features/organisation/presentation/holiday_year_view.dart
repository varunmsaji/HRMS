import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api/api_client.dart';
import '../../../core/api/api_error.dart';
import '../../../core/auth/permissions.dart';
import '../../../core/forms/spec_form_screen.dart';
import '../../../core/providers.dart';
import '../../../core/widgets/ui.dart';
import '../../auth/state/auth_controller.dart';
import '../domain/calendar_views.dart';
import '../domain/org_resources.dart' show holidaySpec, holidayReview, holidayTypeLabels;

const _weekdayLetters = ['M', 'T', 'W', 'T', 'F', 'S', 'S'];

/// A holiday calendar's year view above its holiday list, kept in step: a holiday added from either
/// one refreshes the other.
class HolidaysPanel extends StatefulWidget {
  const HolidaysPanel({super.key, required this.calendarId, required this.section, this.now});
  final String calendarId;

  /// Builds the holiday list section; it receives the callback to call after a change.
  final Widget Function(VoidCallback onChanged, Key key) section;
  final DateTime? now;

  @override
  State<HolidaysPanel> createState() => _HolidaysPanelState();
}

class _HolidaysPanelState extends State<HolidaysPanel> {
  int _yearRefresh = 0;
  int _sectionRefresh = 0;

  @override
  Widget build(BuildContext context) => Column(children: [
        HolidayYearView(
          calendarId: widget.calendarId,
          refresh: _yearRefresh,
          now: widget.now,
          onAdded: () => setState(() => _sectionRefresh++),
        ),
        widget.section(() => setState(() => _yearRefresh++), ValueKey('holidays-$_sectionRefresh')),
      ]);
}

/// Twelve months of one year with holidays highlighted — mirrors web
/// `components/holiday-calendar/holiday-year-calendar.tsx` and its year switcher
/// (`GET /holiday-calendars/{id}/holidays?year=`). Past days are dimmed and today is ringed. A
/// holiday manager can tap an empty day to add a holiday on it (reviewed like any holiday change);
/// tapping a holiday shows its name and type.
class HolidayYearView extends ConsumerStatefulWidget {
  const HolidayYearView({super.key, required this.calendarId, this.refresh = 0, this.onAdded, this.now});
  final String calendarId;

  /// Bumped by the parent to reload (the holiday list changed).
  final int refresh;
  final VoidCallback? onAdded;
  final DateTime? now;

  @override
  ConsumerState<HolidayYearView> createState() => _HolidayYearViewState();
}

class _HolidayYearViewState extends ConsumerState<HolidayYearView> {
  late final DateTime _now = widget.now ?? DateTime.now();
  late int _year = _now.year;
  List<Rec>? _holidays;
  ApiError? _error;
  int _request = 0;

  ApiClient get _client => ref.read(apiClientProvider);

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void didUpdateWidget(HolidayYearView old) {
    super.didUpdateWidget(old);
    if (old.refresh != widget.refresh) _load();
  }

  Future<void> _load() async {
    final mine = ++_request;
    setState(() => _error = null);
    try {
      final out = <Rec>[];
      for (var page = 1; page <= 10; page++) {
        final env = await _client.getList<Rec>('/holiday-calendars/${widget.calendarId}/holidays', query: PageQuery(page: page, perPage: 100), filters: {'year': _year}, parseItem: (d) => d as Rec);
        out.addAll(env.data);
        if (env.pagination == null || !env.pagination!.hasNext) break;
      }
      if (mounted && mine == _request) setState(() => _holidays = out);
    } catch (e) {
      if (mounted && mine == _request) setState(() => _error = e is ApiError ? e : ApiError(status: 0, code: 'UNKNOWN_ERROR', message: 'Something went wrong.'));
    }
  }

  void _shift(int delta) {
    setState(() {
      _year += delta;
      _holidays = null;
    });
    _load();
  }

  Future<void> _add(String iso) async {
    final saved = await openSpecForm(
      context,
      title: 'Add holiday',
      spec: holidaySpec,
      defaults: {...holidaySpec.defaults, 'date': iso},
      onSubmit: (payload, _) async {
        if (!await holidayReview(widget.calendarId).create(context, payload)) throw const SubmitCancelled();
      },
    );
    if (saved && mounted) {
      ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Holiday added.')));
      _load();
      widget.onAdded?.call();
    }
  }

  void _show(String iso, List<Rec> holidays) {
    showModalBottomSheet<void>(
      context: context,
      showDragHandle: true,
      builder: (ctx) => SafeArea(
        child: Padding(
          padding: const EdgeInsets.fromLTRB(20, 0, 20, 20),
          child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text(iso, style: Theme.of(ctx).textTheme.titleMedium),
            for (final h in holidays)
              ListTile(
                contentPadding: EdgeInsets.zero,
                title: Text('${h['name']}'),
                subtitle: Text(holidayTypeLabels[h['holiday_type']] ?? '${h['holiday_type'] ?? ''}'),
              ),
          ]),
        ),
      ),
    );
  }

  Widget _month(int month, Map<String, List<Rec>> byDate, bool canAdd) {
    final theme = Theme.of(context);
    final scheme = theme.colorScheme;
    final today = isoOf(DateTime.utc(_now.year, _now.month, _now.day));
    final cells = yearMonthCells(_year, month);
    return Container(
      padding: const EdgeInsets.all(8),
      decoration: BoxDecoration(border: Border.all(color: scheme.outlineVariant), borderRadius: BorderRadius.circular(10)),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text(monthNames[month - 1], style: theme.textTheme.labelLarge),
        const SizedBox(height: 4),
        GridView.count(
          crossAxisCount: 7,
          shrinkWrap: true,
          physics: const NeverScrollableScrollPhysics(),
          mainAxisSpacing: 2,
          crossAxisSpacing: 2,
          children: [
            for (final l in _weekdayLetters) Center(child: Text(l, style: TextStyle(fontSize: 10, color: scheme.onSurfaceVariant))),
            for (final day in cells)
              if (day == null)
                const SizedBox.shrink()
              else
                Builder(builder: (context) {
                  final iso = isoOf(DateTime.utc(_year, month, day));
                  final hs = byDate[iso];
                  final past = iso.compareTo(today) < 0;
                  final label = hs != null ? '$iso: ${hs.map((h) => h['name']).join(', ')}' : (canAdd ? 'Add holiday on $iso' : iso);
                  return Semantics(
                    label: label,
                    button: hs != null || canAdd,
                    excludeSemantics: true,
                    child: InkWell(
                      onTap: hs != null ? () => _show(iso, hs) : (canAdd ? () => _add(iso) : null),
                      borderRadius: BorderRadius.circular(4),
                      child: Container(
                        alignment: Alignment.center,
                        decoration: BoxDecoration(
                          color: hs != null ? scheme.primary : null,
                          borderRadius: BorderRadius.circular(4),
                          border: iso == today ? Border.all(color: scheme.primary) : null,
                        ),
                        child: Text(
                          '$day',
                          style: TextStyle(
                            fontSize: 11,
                            fontWeight: hs != null ? FontWeight.w700 : null,
                            color: hs != null ? scheme.onPrimary : (past ? scheme.outline : scheme.onSurface),
                          ),
                        ),
                      ),
                    ),
                  );
                }),
          ],
        ),
      ]),
    );
  }

  @override
  Widget build(BuildContext context) {
    final permissions = ref.watch(authControllerProvider).user?.permissions ?? const <String>[];
    final canAdd = permissions.contains(orgHolidayManage);
    final holidays = _holidays;
    final byDate = holidaysByDate(holidays ?? const []);
    return DetailSection(
      title: 'Year view',
      children: [
        Row(children: [
          IconButton(tooltip: 'Previous year', onPressed: () => _shift(-1), icon: const Icon(Icons.chevron_left_rounded)),
          Expanded(child: Semantics(liveRegion: true, child: Text('$_year', textAlign: TextAlign.center, style: Theme.of(context).textTheme.titleSmall))),
          IconButton(tooltip: 'Next year', onPressed: () => _shift(1), icon: const Icon(Icons.chevron_right_rounded)),
        ]),
        if (_error != null)
          Column(crossAxisAlignment: CrossAxisAlignment.start, children: [Text(_error!.message), TextButton(onPressed: _load, child: const Text('Try again'))])
        else if (holidays == null)
          const Padding(padding: EdgeInsets.all(16), child: Center(child: CircularProgressIndicator(semanticsLabel: 'Loading holidays…')))
        else ...[
          Text(
            holidays.where((h) => h['is_active'] != false).isEmpty ? 'No holidays in this calendar for $_year.' : '${byDate.values.fold<int>(0, (a, l) => a + l.length)} holidays in $_year.',
            style: TextStyle(fontSize: 12, color: Theme.of(context).colorScheme.onSurfaceVariant),
          ),
          const SizedBox(height: 8),
          LayoutBuilder(builder: (context, box) {
            final columns = box.maxWidth >= 600 ? 3 : 2;
            final width = (box.maxWidth - 8 * (columns - 1)) / columns;
            return Wrap(spacing: 8, runSpacing: 8, children: [for (var m = 1; m <= 12; m++) SizedBox(width: width, child: _month(m, byDate, canAdd))]);
          }),
        ],
      ],
    );
  }
}
