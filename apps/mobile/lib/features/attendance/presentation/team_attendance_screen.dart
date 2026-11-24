import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../core/api/api_error.dart';
import '../../../core/auth/permissions.dart';
import '../../../core/forms/choice_sources.dart';
import '../../../core/forms/form_spec.dart';
import '../../../core/forms/spec_form_screen.dart';
import '../../../core/providers.dart';
import '../../../core/format.dart';
import '../../../core/time.dart';
import '../../../core/widgets/list_filter.dart';
import '../../auth/state/auth_controller.dart';
import '../../profile/data/employee_repository.dart' show Employee;
import '../../profile/presentation/profile_screen.dart' show employeeRepositoryProvider;
import '../data/attendance_repository.dart';
import '../domain/attendance_mismatch.dart';
import '../domain/not_calculated.dart';
import '../domain/punch_form.dart';
import 'attendance_day_detail_screen.dart';
import 'attendance_summary.dart';
import 'attendance_widgets.dart';
import 'mark_attendance_screen.dart';
import 'mismatch_fixes.dart';
import '../../../core/widgets/ui.dart';

const attendanceStatuses = ['NOT_JOINED', 'EXITED', 'NOT_EXPECTED', 'PRESENT', 'HALF_DAY', 'ABSENT', 'LEAVE', 'ON_DUTY', 'WFH', 'INCOMPLETE', 'CONFIG_ERROR'];

/// The words for [attendanceStatuses], matching the employee surface's (`status_map.dart`).
const attendanceStatusLabels = {
  'NOT_JOINED': 'Not joined yet',
  'EXITED': 'Left the company',
  'NOT_EXPECTED': 'Not expected',
  'PRESENT': 'Present',
  'HALF_DAY': 'Half day',
  'ABSENT': 'Absent',
  'LEAVE': 'On leave',
  'ON_DUTY': 'On duty',
  'WFH': 'Work from home',
  'INCOMPLETE': 'Incomplete',
  'CONFIG_ERROR': 'Needs attention',
};

const _exceptionLabels = [('missing_punch', 'Missing punch'), ('config_error', 'Needs attention'), ('pending_approval', 'Awaiting approval')];

/// Opens the on-behalf punch form. Pass [employeeId] to lock the employee, and [direction] /
/// [punchTime] (wall clock in the company zone, `YYYY-MM-DDTHH:mm`) to open on a known gap such as
/// a missing punch-out.
Future<bool> openPunchOnBehalf(BuildContext context, WidgetRef ref, {String? employeeId, String? direction, String? punchTime}) {
  final zone = ref.read(authControllerProvider).user?.companyTimezone ?? 'Asia/Kolkata';
  final repo = ref.read(attendanceRepositoryProvider);
  return openSpecForm(
    context,
    title: 'Record punch',
    spec: punchOnBehalfSpec(employeeLocked: employeeId != null, zoneLabel: zoneLabel(zone)),
    defaults: {'punch_time': punchTime ?? nowInZoneForInput(zone), if (direction != null) 'direction': direction},
    loadChoices: employeeId == null ? () => loadChoices(ref.read(apiClientProvider), const ['employees']) : null,
    onSubmit: (payload, _) async {
      await repo.createPunchOnBehalf(
        employeeId: employeeId ?? payload['employee_id'] as String,
        direction: payload['direction'] as String,
        punchTimeUtcIso: wallTimeToUtcIso(payload['punch_time'] as String, zone),
        reference: payload['reference'] as String,
      );
    },
  );
}

/// Mirrors `apps/web/src/app/app/attendance/page.tsx`: the day's attendance across the employees
/// the caller can see (the server scopes it), with employee/status/exception filters and, for HR,
/// recording a punch on someone's behalf.
class TeamAttendanceScreen extends ConsumerStatefulWidget {
  /// [date] (`YYYY-MM-DD`), [bucket] (a status bucket such as `PRESENT`) and [flag] (one of
  /// [attendanceDayFlags]) open the list already narrowed, as the Insights summary tiles do.
  /// Unknown values are ignored.
  const TeamAttendanceScreen({super.key, this.date, this.bucket, this.flag, this.missing});

  final String? date;
  final String? bucket;
  final String? flag;

  /// How many employees the figure that sent the user here counted but this list cannot show,
  /// because they have no attendance row for the day yet (the "not checked in" figure counts them).
  final int? missing;

  @override
  ConsumerState<TeamAttendanceScreen> createState() => _TeamAttendanceScreenState();
}

class _TeamAttendanceScreenState extends ConsumerState<TeamAttendanceScreen> {
  late String _date;
  ListFilter _filter = const ListFilter();
  String get _employeeId => _filter.employee;

  /// The type-to-find box (web's replaces its employee dropdown): narrows the day's rows by name or
  /// employee code as the user types. The labels hold both ("Asha Rao (E-104)").
  final _find = TextEditingController();
  String _query = '';
  String get _status => _filter.group('status');
  Set<String> get _exceptions => _filter.multi('exceptions');
  String? _bucket;
  String? _flag;
  bool _loading = true;
  ApiError? _error;
  List<AttendanceDay> _days = const [];
  List<Choice> _employees = const [];
  /// R-D06: employed people with no calculated day on a past [_date]; empty when unknown.
  List<String> _notCalculated = const [];
  bool _queuing = false;
  Map<String, String> _pending = const {};
  bool _onlyMismatches = false;

  String get _zone => ref.read(authControllerProvider).user?.companyTimezone ?? 'Asia/Kolkata';

  @override
  void initState() {
    super.initState();
    final given = widget.date;
    _date = given != null && RegExp(r'^\d{4}-\d{2}-\d{2}$').hasMatch(given) ? given : businessToday(_zone);
    if (widget.bucket != null && (attendanceBucketLabels.containsKey(widget.bucket) || widget.bucket == attendingBucketKey)) _bucket = widget.bucket;
    if (widget.flag != null && attendanceDayFlags.containsKey(widget.flag)) _flag = widget.flag;
    _loadEmployees();
    _loadPending();
    _load();
  }

  Future<void> _loadPending() async {
    final pending = await loadPendingCorrections(ref);
    if (mounted) setState(() => _pending = pending);
  }

  @override
  void dispose() {
    _find.dispose();
    super.dispose();
  }

  Future<void> _loadEmployees() async {
    try {
      final c = await loadChoices(ref.read(apiClientProvider), const ['employees']);
      if (mounted) setState(() => _employees = c['employees'] ?? const []);
    } catch (_) {}
  }

  Future<void> _load() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final days = await ref.read(attendanceRepositoryProvider).listAttendanceDays(
            employeeId: _employeeId.isEmpty ? null : _employeeId,
            dateFrom: _date,
            dateTo: _date,
          );
      if (mounted) setState(() => _days = days);
      _findNotCalculated(days);
    } catch (e) {
      if (mounted) setState(() => _error = e is ApiError ? e : ApiError(status: 0, code: 'UNKNOWN_ERROR', message: 'Something went wrong.'));
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  /// Who is employed on a past [_date] yet has no row, read from the employee list the way the web
  /// does. Quiet on any failure: the notice is an extra, and the list may not be readable here.
  /// Shown only to someone who reads company-wide attendance (the employee list can be broader than
  /// the attendance they may see), and only when the whole roster was read - a partial roster would
  /// report a wrong count.
  Future<void> _findNotCalculated(List<AttendanceDay> days) async {
    final date = _date;
    final permissions = ref.read(authControllerProvider).user?.permissions ?? const <String>[];
    if (date.compareTo(businessToday(_zone)) >= 0 || _employeeId.isNotEmpty || !permissions.contains(attendanceViewAll)) {
      if (mounted && _notCalculated.isNotEmpty) setState(() => _notCalculated = const []);
      return;
    }
    try {
      final repo = ref.read(employeeRepositoryProvider);
      final all = <Employee>[];
      var complete = false;
      for (var page = 1; page <= 50; page++) {
        final r = await repo.listEmployeesPage(page: page, perPage: 100);
        all.addAll(r.rows);
        if (!r.hasNext) {
          complete = true;
          break;
        }
      }
      if (!mounted || date != _date) return;
      final ids = complete ? [for (final e in employeesWithoutRecord(all, {for (final d in days) d.employeeId}, date)) e.id] : const <String>[];
      setState(() => _notCalculated = ids);
    } catch (_) {
      if (mounted && date == _date) setState(() => _notCalculated = const []);
    }
  }

  Future<void> _recalculate() async {
    final ids = _notCalculated;
    setState(() => _queuing = true);
    try {
      await ref.read(apiClientProvider).post<Object?>('/attendance/days/calculate-range', body: {'date_from': _date, 'date_to': _date, 'employee_ids': ids}, parse: (_) => null);
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('Calculation queued for ${ids.length} ${ids.length == 1 ? 'day' : 'days'}. Refresh in a minute to see them counted.')));
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(e is ApiError ? 'Could not queue the calculation: ${e.message}' : 'Could not queue the calculation.')));
    } finally {
      if (mounted) setState(() => _queuing = false);
    }
  }

  Widget _notCalculatedNotice(BuildContext context, bool canRecalculate) {
    final n = _notCalculated.length;
    final scheme = Theme.of(context).colorScheme;
    return Container(
      margin: const EdgeInsets.only(bottom: 8),
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(color: toneColors(context, Tone.warning).bg, borderRadius: BorderRadius.circular(12)),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text('Not calculated: $n.', style: const TextStyle(fontWeight: FontWeight.w700)),
        const SizedBox(height: 2),
        Text('${n == 1 ? 'One employed person has' : '$n employed people have'} no calculated day for ${formatDayDate(_date)}, so they are missing from the figures here.', style: TextStyle(color: scheme.onSurfaceVariant)),
        if (canRecalculate && n <= recalculateMaxEmployees)
          Align(
            alignment: Alignment.centerLeft,
            child: Padding(
              padding: const EdgeInsets.only(top: 6),
              child: OutlinedButton(onPressed: _queuing ? null : _recalculate, child: Text(_queuing ? 'Queuing…' : 'Recalculate')),
            ),
          ),
      ]),
    );
  }

  Future<void> _pickDate() async {
    final current = DateTime.tryParse(_date) ?? DateTime.now();
    final picked = await showDatePicker(context: context, initialDate: current, firstDate: DateTime(2020), lastDate: DateTime(2100));
    if (picked == null) return;
    setState(() => _date = '${picked.year.toString().padLeft(4, '0')}-${picked.month.toString().padLeft(2, '0')}-${picked.day.toString().padLeft(2, '0')}');
    _load();
  }

  Future<void> _openFilter() async {
    final next = await showListFilterSheet(
      context,
      initial: _filter,
      defaults: const ListFilter(),
      dates: false,
      employees: _employees,
      groups: [
        FilterGroup(key: 'status', label: 'Status', options: [for (final st in attendanceStatuses) (st, attendanceStatusLabels[st] ?? st)]),
        const FilterGroup(key: 'exceptions', label: 'Only days with', options: _exceptionLabels, multi: true),
      ],
    );
    if (next == null || next == _filter || !mounted) return;
    final reload = next.employee != _filter.employee;
    setState(() => _filter = next);
    if (reload) _load();
  }

  String _filterSummary() => [
        _status.isEmpty ? 'Everyone' : (attendanceStatusLabels[_status] ?? _status),
        for (final (key, label) in _exceptionLabels)
          if (_exceptions.contains(key)) label,
        if (_employeeId.isNotEmpty) _name(_employeeId),
      ].join(' · ');

  bool _matches(AttendanceDay d, String key) => switch (key) {
        'missing_punch' => d.raw['missing_punch'] == true,
        'config_error' => d.attendanceStatus == 'CONFIG_ERROR',
        _ => d.raw['is_pending_approval'] == true,
      };

  /// The chips for the day being looked at. "Not in yet" only means something for today (a past
  /// day's gaps are absences), so it is offered only then. Each is a one-tap version of a filter
  /// the sheet already has.
  List<({String key, String label, int count, bool selected, VoidCallback onTap})> _quickChips(AttendanceSummary summary) {
    final today = _date == businessToday(_zone);
    void flag(String f) => setState(() {
          _flag = _flag == f ? null : f;
          _bucket = null;
        });
    final missing = _days.where((d) => _matches(d, 'missing_punch')).length;
    final missingOn = _exceptions.contains('missing_punch');
    return [
      if (today) (key: 'not_checked_in', label: 'Not in yet', count: summary.notCheckedIn, selected: _flag == 'not_checked_in', onTap: () => flag('not_checked_in')),
      (key: 'late', label: 'Late', count: summary.late, selected: _flag == 'late', onTap: () => flag('late')),
      (
        key: 'missing_punch',
        label: 'Missing punch',
        count: missing,
        selected: missingOn,
        onTap: () => setState(() {
              final next = {..._exceptions};
              missingOn ? next.remove('missing_punch') : next.add('missing_punch');
              _filter = _filter.withGroup('exceptions', next.join(','));
            }),
      ),
    ];
  }

  Widget _quickChipRow(List<({String key, String label, int count, bool selected, VoidCallback onTap})> chips) {
    return SizedBox(
      height: 44,
      child: ListView.separated(
        scrollDirection: Axis.horizontal,
        padding: const EdgeInsets.fromLTRB(16, 8, 16, 0),
        itemCount: chips.length,
        separatorBuilder: (_, __) => const SizedBox(width: 8),
        itemBuilder: (_, i) {
          final c = chips[i];
          return FilterChip(
            key: ValueKey('quick_${c.key}'),
            label: Text('${c.label} ${c.count}'),
            selected: c.selected,
            onSelected: (_) => c.onTap(),
          );
        },
      ),
    );
  }

  String _name(String employeeId) {
    for (final c in _employees) {
      if (c.value == employeeId) return c.label;
    }
    return 'Employee';
  }

  @override
  Widget build(BuildContext context) {
    final permissions = ref.watch(authControllerProvider).user?.permissions ?? const <String>[];
    final canPunch = permissions.contains(attendancePunchOnBehalf);
    final matching = _days
        .where((d) => (_status.isEmpty || d.attendanceStatus == _status) && (_bucket == null || matchesBucket(d, _bucket!)) && (_flag == null || matchesDayFlag(d, _flag!)) && _exceptions.every((k) => _matches(d, k)) && (_query.isEmpty || _employees.isEmpty || _name(d.employeeId).toLowerCase().contains(_query)))
        .toList();
    final fixer = MismatchFixer(
      context: context,
      ref: ref,
      nameOf: _name,
      pending: _pending,
      openPunch: ({required employeeId, required direction, required time}) => openPunchOnBehalf(context, ref, employeeId: employeeId, direction: direction, punchTime: time),
      openDay: (d) => Navigator.of(context).push(MaterialPageRoute(builder: (_) => AttendanceDayDetailScreen(dayId: d.id, initial: d))),
      onChanged: () {
        _load();
        _loadPending();
      },
    );
    final mismatchCount = matching.where((d) => mismatchOf(d) != null).length;
    final narrow = _onlyMismatches && mismatchCount > 0;
    // What HR has to fix or chase first; the server's order otherwise (List.sort is not stable).
    final ranked = [for (var i = 0; i < matching.length; i++) (i, matching[i])]..sort((a, b) {
        final c = attentionRank(a.$2).compareTo(attentionRank(b.$2));
        return c != 0 ? c : a.$1.compareTo(b.$1);
      });
    final visible = [for (final (_, d) in ranked) if (!narrow || mismatchOf(d) != null) d];
    final summary = AttendanceSummary.compute(_days);
    final chips = _quickChips(summary);
    // A flag with its own chip is cleared by that chip; the "Showing" tag is for the others.
    final flagHasChip = _flag != null && chips.any((c) => c.key == _flag);
    return Scaffold(
      appBar: AppBar(
        title: const Text('Team attendance'),
        actions: [
          if ((ref.watch(authControllerProvider).user?.permissions ?? const <String>[]).contains(attendanceViewAll))
            IconButton(tooltip: 'Attendance calendar', icon: const Icon(Icons.calendar_view_month_outlined), onPressed: () => context.push('/app/attendance/calendar')),
          IconButton(tooltip: 'Insights', icon: const Icon(Icons.insights_outlined), onPressed: () => context.push('/app/attendance-insights')),
          if (canPunch)
            IconButton(
              tooltip: 'Mark attendance',
              icon: const Icon(Icons.fact_check_outlined),
              onPressed: () async {
                if (await openMarkAttendance(context, date: _date) && mounted) _load();
              },
            ),
          if (canPunch)
            IconButton(
              tooltip: 'Record punch',
              icon: const Icon(Icons.more_time),
              onPressed: () async {
                if (await openPunchOnBehalf(context, ref) && mounted) _load();
              },
            ),
        ],
      ),
      body: Column(children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(16, 12, 16, 0),
          child: Column(children: [
            ListFilterBar(
              leading: OutlinedButton.icon(
                onPressed: _pickDate,
                icon: const Icon(Icons.calendar_today_outlined, size: 18),
                label: Text(_date == businessToday(_zone) ? 'Today' : formatDayDate(_date)),
              ),
              summary: _filterSummary(),
              activeCount: _filter.countAgainst(const ListFilter()),
              onTap: _openFilter,
            ),
          ]),
        ),
        // Names and codes come from the employee directory; without that grant the rows carry only
        // ids, so a typed query could match nobody. Offer the box only when the lookup worked.
        if (_employees.isNotEmpty)
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 8, 16, 0),
            child: AppSearchField(
              key: const ValueKey('team_find'),
              controller: _find,
              hint: 'Find an employee by name or code',
              onChanged: (v) => setState(() => _query = v.trim().toLowerCase()),
            ),
          ),
        // One-tap versions of the filters managers use every morning (MOB-UX-047).
        if (!_loading && _error == null && _days.isNotEmpty) _quickChipRow(chips),
        Expanded(
          child: _loading
              ? const ListSkeleton()
              : _error != null
                  ? StateMessage(icon: Icons.error_outline_rounded, tone: Tone.danger, title: "Couldn't load attendance", message: _error!.message, actionLabel: 'Try again', onAction: _load)
                  : RefreshIndicator(
                      onRefresh: _load,
                      child: ListView(
                        padding: const EdgeInsets.all(16),
                        children: [
                          if (_bucket != null || (_flag != null && !flagHasChip))
                            Padding(
                              padding: const EdgeInsets.only(bottom: 8),
                              child: Align(
                                alignment: Alignment.centerLeft,
                                child: InputChip(
                                  label: Text('Showing: ${_flag != null ? attendanceDayFlags[_flag] : (_bucket == attendingBucketKey ? attendingBucketLabel : attendanceBucketLabels[_bucket])}'),
                                  onDeleted: () => setState(() {
                                    _bucket = null;
                                    _flag = null;
                                  }),
                                ),
                              ),
                            ),
                          if (_notCalculated.isNotEmpty) _notCalculatedNotice(context, permissions.contains(attendanceRecompute)),
                          if (_flag == 'not_checked_in' && (widget.missing ?? 0) > 0)
                            Padding(
                              padding: const EdgeInsets.only(bottom: 8),
                              child: Text(
                                '${widget.missing} more ${widget.missing == 1 ? 'employee has' : 'employees have'} no attendance record for this day yet. They are counted on Insights but cannot be listed here until the day is worked out.',
                                style: TextStyle(fontSize: 12, color: Theme.of(context).colorScheme.onSurfaceVariant),
                              ),
                            ),
                          if (_days.isNotEmpty) AttendanceSummaryCard(summary: summary, selectedBucket: _bucket, onBucketTap: (b) => setState(() {
                                _bucket = b;
                                _flag = null;
                              })),
                          if (mismatchCount > 0)
                            MismatchBanner(count: mismatchCount, narrowed: narrow, onToggle: () => setState(() => _onlyMismatches = !narrow)),
                          const SizedBox(height: 8),
                          if (visible.isEmpty)
                            SizedBox(
                              height: 300,
                              child: StateMessage(
                                icon: Icons.groups_outlined,
                                title: _days.isEmpty ? 'No attendance for this day' : 'Nobody matches these filters',
                                message: _days.isEmpty ? 'Attendance appears here once people punch in, or once the day is worked out. Pick another day above.' : 'Change them with Filter, or tap a figure above to clear it.',
                              ),
                            ),
                          for (final d in visible)
                            AttendanceDayTile(
                              day: d,
                              employeeLabel: _name(d.employeeId),
                              mismatch: fixer.forDay(d),
                              onMarkPresent: canPunch && d.employeeId != ref.read(authControllerProvider).user?.employeeId
                                  ? () async {
                                      if (await openMarkAttendance(context, employees: [(value: d.employeeId, label: _name(d.employeeId))], date: d.attendanceDate) && mounted) _load();
                                    }
                                  : null,
                              onTap: () => Navigator.of(context).push(MaterialPageRoute(builder: (_) => AttendanceDayDetailScreen(dayId: d.id, initial: d))),
                            ),
                        ],
                      ),
                    ),
        ),
      ]),
    );
  }
}
