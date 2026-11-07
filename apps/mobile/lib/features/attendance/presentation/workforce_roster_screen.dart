import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api/api_error.dart';
import '../../../core/auth/permissions.dart';
import '../../../core/time.dart';
import '../../../core/widgets/ui.dart';
import '../../auth/state/auth_controller.dart';
import '../../profile/data/employee_repository.dart';
import '../../profile/presentation/profile_screen.dart' show employeeRepositoryProvider;
import '../data/roster_repository.dart';
import '../domain/roster_views.dart';
import 'rosters_screen.dart' show openRosterForm;

/// Who is on which shift, by date — mirrors `apps/web/src/app/app/rosters/grid/page.tsx`: employees
/// as rows, dates as columns, each cell the rostered shift. The names stay put while the dates
/// scroll sideways. A blank cell means no entry, so the employee's default shift applies.
class WorkforceRosterScreen extends ConsumerStatefulWidget {
  const WorkforceRosterScreen({super.key, this.now});

  /// Overrides the clock (tests). Null = now.
  final DateTime? now;

  @override
  ConsumerState<WorkforceRosterScreen> createState() => _WorkforceRosterScreenState();
}

const _dayOptions = [7, 14, 31];
const _nameWidth = 120.0;
const _cellWidth = 58.0;
const _cellHeight = 44.0;
const _toneCount = 5;

class _WorkforceRosterScreenState extends ConsumerState<WorkforceRosterScreen> {
  late final String _today;
  late String _start;
  int _days = 14;
  final _searchController = TextEditingController();
  Timer? _debounce;
  bool _onlyRostered = false;

  List<Employee>? _employees;
  bool _hasNext = false;
  int _page = 1;
  bool _loadingEmployees = true;
  bool _loadingMore = false;
  ApiError? _employeesError;
  int _employeesRequest = 0;

  ({List<RosterEntry> entries, int total})? _range;
  bool _loadingRange = true;
  ApiError? _rangeError;
  int _rangeRequest = 0;

  Map<String, RosterShift> _shifts = const {};

  bool get _canManage => (ref.read(authControllerProvider).user?.permissions ?? const []).contains(attendanceRosterManage);
  List<String> get _dates => [for (var i = 0; i < _days; i++) addDaysIso(_start, i)];
  ApiError _wrap(Object e) => e is ApiError ? e : ApiError(status: 0, code: 'UNKNOWN_ERROR', message: 'Something went wrong.');

  @override
  void initState() {
    super.initState();
    _today = businessToday(ref.read(authControllerProvider).user?.companyTimezone ?? 'Asia/Kolkata', now: widget.now);
    _start = mondayOfIso(_today);
    _loadShifts();
    _loadEmployees();
    _loadRange();
  }

  @override
  void dispose() {
    _debounce?.cancel();
    _searchController.dispose();
    super.dispose();
  }

  /// The grid still works from ids without them. `GET /shifts` checks ORG.SHIFT.MANAGE, so a role
  /// without it skips the call rather than collect a 403.
  Future<void> _loadShifts() async {
    if (!(ref.read(authControllerProvider).user?.permissions ?? const <String>[]).contains(orgShiftManage)) return;
    try {
      final shifts = await ref.read(rosterRepositoryProvider).listShifts();
      if (mounted) setState(() => _shifts = {for (final s in shifts) s.id: s});
    } catch (_) {}
  }

  Future<void> _loadEmployees() async {
    final mine = ++_employeesRequest;
    setState(() {
      _loadingEmployees = true;
      _employeesError = null;
    });
    try {
      final page = await ref.read(employeeRepositoryProvider).listEmployeesPage(search: _searchController.text);
      if (!mounted || mine != _employeesRequest) return;
      setState(() {
        _employees = page.rows;
        _hasNext = page.hasNext;
        _page = 1;
      });
    } catch (e) {
      if (mounted && mine == _employeesRequest) setState(() => _employeesError = _wrap(e));
    } finally {
      if (mounted && mine == _employeesRequest) setState(() => _loadingEmployees = false);
    }
  }

  Future<void> _moreEmployees() async {
    final mine = _employeesRequest;
    setState(() => _loadingMore = true);
    try {
      final page = await ref.read(employeeRepositoryProvider).listEmployeesPage(search: _searchController.text, page: _page + 1);
      if (!mounted || mine != _employeesRequest) return;
      setState(() {
        _employees = [...?_employees, ...page.rows];
        _hasNext = page.hasNext;
        _page += 1;
      });
    } catch (e) {
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(_wrap(e).message)));
    } finally {
      if (mounted) setState(() => _loadingMore = false);
    }
  }

  Future<void> _loadRange() async {
    final mine = ++_rangeRequest;
    final dates = _dates;
    setState(() {
      _loadingRange = true;
      _rangeError = null;
    });
    try {
      final range = await ref.read(rosterRepositoryProvider).listEntries(dates.first, dates.last);
      if (mounted && mine == _rangeRequest) setState(() => _range = range);
    } catch (e) {
      if (mounted && mine == _rangeRequest) setState(() => _rangeError = _wrap(e));
    } finally {
      if (mounted && mine == _rangeRequest) setState(() => _loadingRange = false);
    }
  }

  void _setRange({String? start, int? days}) {
    setState(() {
      if (start != null) _start = start;
      if (days != null) _days = days;
    });
    _loadRange();
  }

  Future<void> _openCell(Employee e, String date, RosterEntry? entry) async {
    final saved = await openRosterForm(context, ref, roster: entry?.raw, employeeId: entry == null ? e.id : null, date: entry == null ? date : null);
    if (saved && mounted) _loadRange();
  }

  Color _toneFg(BuildContext context, RosterShift? shift) => shift == null ? Theme.of(context).colorScheme.onSurface : (shift.isNight ? Theme.of(context).colorScheme.onInverseSurface : toneColors(context, _tones[shift.toneIndex(_toneCount)]).fg);
  Color _toneBg(BuildContext context, RosterShift? shift) => shift == null ? Theme.of(context).colorScheme.surfaceContainerHighest : (shift.isNight ? Theme.of(context).colorScheme.inverseSurface : toneColors(context, _tones[shift.toneIndex(_toneCount)]).bg);
  static const _tones = [Tone.accent, Tone.success, Tone.warning, Tone.info, Tone.danger];

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final muted = TextStyle(fontSize: 12, color: scheme.onSurfaceVariant);
    final dates = _dates;
    final range = _range;
    final canManage = _canManage;
    final error = _employeesError ?? _rangeError;
    final rosteredIds = (range?.entries ?? const <RosterEntry>[]).map((r) => r.employeeId).toSet();
    final rows = [for (final e in _employees ?? const <Employee>[]) if (!_onlyRostered || rosteredIds.contains(e.id)) e];
    final thisWeek = _start == mondayOfIso(_today);
    final truncated = range != null && range.total > range.entries.length;
    final used = (range?.entries ?? const <RosterEntry>[]).map((r) => r.shiftId).whereType<String>().toSet();
    return Scaffold(
      appBar: AppBar(title: const Text('Workforce roster')),
      body: RefreshIndicator(
        onRefresh: () => Future.wait([_loadEmployees(), _loadRange()]),
        child: ListView(padding: const EdgeInsets.fromLTRB(16, 12, 16, 32), children: [
          Row(children: [
            IconButton(tooltip: 'Previous', onPressed: () => _setRange(start: addDaysIso(_start, -_days)), icon: const Icon(Icons.chevron_left)),
            Expanded(child: Text('${formatShortDate(dates.first)} – ${formatShortDate(dates.last)}', textAlign: TextAlign.center, style: const TextStyle(fontWeight: FontWeight.w600))),
            IconButton(tooltip: 'Next', onPressed: () => _setRange(start: addDaysIso(_start, _days)), icon: const Icon(Icons.chevron_right)),
          ]),
          Wrap(spacing: 8, crossAxisAlignment: WrapCrossAlignment.center, children: [
            for (final d in _dayOptions) ChoiceChip(label: Text('$d days'), selected: _days == d, onSelected: (_) => _setRange(days: d)),
            TextButton(onPressed: thisWeek ? null : () => _setRange(start: mondayOfIso(_today)), child: const Text('Today')),
          ]),
          const SizedBox(height: 8),
          AppSearchField(
            controller: _searchController,
            hint: 'Search name or code',
            onChanged: (_) {
              _debounce?.cancel();
              _debounce = Timer(const Duration(milliseconds: 300), _loadEmployees);
            },
          ),
          SwitchListTile(
            contentPadding: EdgeInsets.zero,
            dense: true,
            title: const Text('Only employees with an entry in this range'),
            value: _onlyRostered,
            onChanged: (v) => setState(() => _onlyRostered = v),
          ),
          if (truncated)
            Padding(
              padding: const EdgeInsets.only(bottom: 8),
              child: Text('Showing the first ${range.entries.length} of ${range.total} roster entries in this range. Some cells may be blank even though an entry exists. Choose a shorter range to see everything.', style: TextStyle(color: scheme.error)),
            ),
          if (error != null)
            StateMessage(
              icon: Icons.error_outline_rounded,
              tone: Tone.danger,
              title: "Couldn't load the roster",
              message: error.status == 403 ? "You don't have permission to see this." : error.message,
              actionLabel: 'Retry',
              onAction: () {
                if (_employeesError != null) _loadEmployees();
                if (_rangeError != null) _loadRange();
              },
            )
          else if (_employees == null || range == null)
            const Padding(padding: EdgeInsets.all(32), child: Center(child: CircularProgressIndicator(strokeWidth: 2.5)))
          else if (rows.isEmpty)
            StateMessage(icon: Icons.people_outline, title: 'No employees to show.', message: _onlyRostered || _searchController.text.isNotEmpty ? 'No one matches. Clear the filter or load more.' : null)
          else ...[
            if (_loadingEmployees || _loadingRange) const LinearProgressIndicator(),
            _grid(context, rows, dates, range.entries, canManage),
          ],
          if (_hasNext && error == null) Center(child: TextButton(onPressed: _loadingMore ? null : _moreEmployees, child: Text(_loadingMore ? 'Loading…' : 'Load more employees'))),
          const SizedBox(height: 8),
          Wrap(spacing: 6, runSpacing: 6, children: [
            for (final s in _shifts.values)
              if (used.contains(s.id))
                Container(
                  padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
                  decoration: BoxDecoration(color: _toneBg(context, s), borderRadius: BorderRadius.circular(6)),
                  child: Text(s.code == null ? s.name : '${s.code} ${s.name}', style: TextStyle(fontSize: 12, fontWeight: FontWeight.w600, color: _toneFg(context, s))),
                ),
          ]),
          const SizedBox(height: 8),
          Text('${canManage ? 'Tap a cell to edit it, or the + on a blank cell to add an entry. ' : ''}OFF = week off. * = working holiday. An outlined cell is a draft, not yet live. A blank cell means the default shift applies.', style: muted),
        ]),
      ),
    );
  }

  Widget _grid(BuildContext context, List<Employee> rows, List<String> dates, List<RosterEntry> entries, bool canManage) {
    final scheme = Theme.of(context).colorScheme;
    final scale = MediaQuery.textScalerOf(context).scale(1);
    final height = _cellHeight * scale;
    final cells = {for (final r in entries) '${r.employeeId}|${r.date}': r};
    final coverage = buildRosterCoverage(entries, dates, _shifts);
    Widget nameCell(Widget child, {Color? color}) => Container(
          width: _nameWidth,
          height: height,
          alignment: Alignment.centerLeft,
          padding: const EdgeInsets.only(right: 6),
          decoration: BoxDecoration(color: color, border: Border(bottom: BorderSide(color: scheme.outlineVariant))),
          child: child,
        );
    Widget dayCell(String date, Widget? child) {
      final weekend = gridDayHeading(date).weekend;
      return Container(
        width: _cellWidth * scale,
        height: height,
        alignment: Alignment.center,
        decoration: BoxDecoration(
          color: date == _today ? scheme.primary.withValues(alpha: 0.08) : (weekend ? scheme.surfaceContainerHighest.withValues(alpha: 0.4) : null),
          border: Border(bottom: BorderSide(color: scheme.outlineVariant)),
        ),
        child: child,
      );
    }

    Widget entryCell(Employee e, String date) {
      final entry = cells['${e.id}|$date'];
      final name = e.fullName.isEmpty ? e.employeeCode : e.fullName;
      if (entry == null) {
        if (!canManage) return dayCell(date, null);
        return dayCell(
          date,
          Semantics(
            label: 'Add roster entry for $name on $date',
            button: true,
            excludeSemantics: true,
            child: InkWell(onTap: () => _openCell(e, date, null), child: SizedBox.expand(child: Center(child: Text('+', style: TextStyle(color: scheme.onSurfaceVariant))))),
          ),
        );
      }
      final shift = entry.shiftId == null || entry.isWeekOff ? null : _shifts[entry.shiftId];
      final label = rosterCellLabel(entry, _shifts);
      final chip = Container(
        margin: const EdgeInsets.all(3),
        padding: const EdgeInsets.symmetric(horizontal: 3),
        alignment: Alignment.center,
        decoration: BoxDecoration(
          color: _toneBg(context, shift),
          borderRadius: BorderRadius.circular(6),
          border: entry.isDraft ? Border.all(color: scheme.primary, width: 2, strokeAlign: BorderSide.strokeAlignInside) : null,
        ),
        child: Text(label, maxLines: 1, overflow: TextOverflow.ellipsis, style: TextStyle(fontSize: 11, fontWeight: FontWeight.w600, color: _toneFg(context, shift))),
      );
      return dayCell(
        date,
        Semantics(
          label: '$name · $date · $label${entry.isDraft ? ' (draft, not live)' : ' (published)'}',
          button: canManage,
          excludeSemantics: true,
          child: canManage ? InkWell(onTap: () => _openCell(e, date, entry), child: SizedBox.expand(child: chip)) : SizedBox.expand(child: chip),
        ),
      );
    }

    final names = <Widget>[
      nameCell(Text('Employee', style: TextStyle(fontSize: 12, fontWeight: FontWeight.w600, color: scheme.onSurfaceVariant))),
      for (final e in rows)
        nameCell(Text(e.fullName.isEmpty ? e.employeeCode : e.fullName, maxLines: 2, overflow: TextOverflow.ellipsis, style: const TextStyle(fontSize: 12))),
      if (coverage.isNotEmpty) nameCell(Text('Rostered per day (all employees)', maxLines: 2, overflow: TextOverflow.ellipsis, style: TextStyle(fontSize: 11, fontWeight: FontWeight.w600, color: scheme.onSurfaceVariant))),
      for (final row in coverage) nameCell(Text('${row.label} (${row.people})', maxLines: 2, overflow: TextOverflow.ellipsis, style: const TextStyle(fontSize: 12, fontWeight: FontWeight.w500))),
    ];
    final table = <Widget>[
      Row(children: [
        for (final d in dates)
          dayCell(
            d,
            Column(mainAxisAlignment: MainAxisAlignment.center, children: [
              Text(gridDayHeading(d).weekday, style: TextStyle(fontSize: 11, fontWeight: FontWeight.w600, color: d == _today ? scheme.primary : scheme.onSurfaceVariant)),
              Text(gridDayHeading(d).date, style: TextStyle(fontSize: 11, color: d == _today ? scheme.primary : scheme.onSurfaceVariant)),
            ]),
          ),
      ]),
      for (final e in rows) Row(children: [for (final d in dates) entryCell(e, d)]),
      if (coverage.isNotEmpty) Row(children: [for (final d in dates) dayCell(d, null)]),
      for (final row in coverage)
        Row(children: [
          for (final d in dates)
            dayCell(
              d,
              Text((row.byDate[d] ?? 0) == 0 ? '–' : '${row.byDate[d]}', style: TextStyle(fontSize: 12, fontWeight: (row.byDate[d] ?? 0) == 0 ? FontWeight.w400 : FontWeight.w700, color: (row.byDate[d] ?? 0) == 0 ? scheme.onSurfaceVariant : null)),
            ),
        ]),
    ];
    return Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Column(children: names),
      Expanded(child: SingleChildScrollView(scrollDirection: Axis.horizontal, child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: table))),
    ]);
  }
}
