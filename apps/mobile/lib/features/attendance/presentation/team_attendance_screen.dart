import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../core/api/api_error.dart';
import '../../../core/auth/permissions.dart';
import '../../../core/forms/choice_sources.dart';
import '../../../core/forms/form_spec.dart';
import '../../../core/forms/spec_form_screen.dart';
import '../../../core/providers.dart';
import '../../../core/time.dart';
import '../../auth/state/auth_controller.dart';
import '../data/attendance_repository.dart';
import '../domain/punch_form.dart';
import 'attendance_day_detail_screen.dart';
import 'attendance_summary.dart';
import 'attendance_widgets.dart';
import '../../../core/widgets/ui.dart';

const attendanceStatuses = ['NOT_JOINED', 'EXITED', 'NOT_EXPECTED', 'PRESENT', 'HALF_DAY', 'ABSENT', 'LEAVE', 'ON_DUTY', 'WFH', 'INCOMPLETE', 'CONFIG_ERROR'];

/// Opens the on-behalf punch form. Pass [employeeId] to lock the employee.
Future<bool> openPunchOnBehalf(BuildContext context, WidgetRef ref, {String? employeeId}) {
  final zone = ref.read(authControllerProvider).user?.companyTimezone ?? 'Asia/Kolkata';
  final repo = ref.read(attendanceRepositoryProvider);
  return openSpecForm(
    context,
    title: 'Record punch',
    spec: punchOnBehalfSpec(employeeLocked: employeeId != null, zoneLabel: zoneLabel(zone)),
    defaults: {'punch_time': nowInZoneForInput(zone)},
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
  const TeamAttendanceScreen({super.key});

  @override
  ConsumerState<TeamAttendanceScreen> createState() => _TeamAttendanceScreenState();
}

class _TeamAttendanceScreenState extends ConsumerState<TeamAttendanceScreen> {
  late String _date;
  String _employeeId = '';
  String _status = '';
  String? _bucket;
  final _exceptions = <String>{};
  bool _loading = true;
  ApiError? _error;
  List<AttendanceDay> _days = const [];
  List<Choice> _employees = const [];

  String get _zone => ref.read(authControllerProvider).user?.companyTimezone ?? 'Asia/Kolkata';

  @override
  void initState() {
    super.initState();
    _date = businessToday(_zone);
    _loadEmployees();
    _load();
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
    } catch (e) {
      if (mounted) setState(() => _error = e is ApiError ? e : ApiError(status: 0, code: 'UNKNOWN_ERROR', message: 'Something went wrong.'));
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _pickDate() async {
    final current = DateTime.tryParse(_date) ?? DateTime.now();
    final picked = await showDatePicker(context: context, initialDate: current, firstDate: DateTime(2020), lastDate: DateTime(2100));
    if (picked == null) return;
    setState(() => _date = '${picked.year.toString().padLeft(4, '0')}-${picked.month.toString().padLeft(2, '0')}-${picked.day.toString().padLeft(2, '0')}');
    _load();
  }

  bool _matches(AttendanceDay d, String key) => switch (key) {
        'missing_punch' => d.raw['missing_punch'] == true,
        'config_error' => d.attendanceStatus == 'CONFIG_ERROR',
        _ => d.raw['is_pending_approval'] == true,
      };

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
    final visible = _days
        .where((d) => (_status.isEmpty || d.attendanceStatus == _status) && (_bucket == null || attendanceBucketOf(d) == _bucket) && _exceptions.every((k) => _matches(d, k)))
        .toList();
    final summary = AttendanceSummary.compute(_days);
    return Scaffold(
      appBar: AppBar(
        title: const Text('Team attendance'),
        actions: [
          IconButton(tooltip: 'Insights', icon: const Icon(Icons.insights_outlined), onPressed: () => context.push('/app/attendance-insights')),
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
            Row(children: [
              Expanded(
                child: OutlinedButton.icon(onPressed: _pickDate, icon: const Icon(Icons.calendar_today_outlined, size: 18), label: Text(_date)),
              ),
              const SizedBox(width: 8),
              Expanded(
                child: DropdownButtonFormField<String>(
                  value: _status,
                  isExpanded: true,
                  decoration: const InputDecoration(labelText: 'Status', contentPadding: EdgeInsets.symmetric(horizontal: 12, vertical: 8)),
                  items: [const DropdownMenuItem(value: '', child: Text('All')), for (final s in attendanceStatuses) DropdownMenuItem(value: s, child: Text(s.replaceAll('_', ' ')))],
                  onChanged: (v) => setState(() => _status = v ?? ''),
                ),
              ),
            ]),
            const SizedBox(height: 8),
            DropdownButtonFormField<String>(
              value: _employeeId,
              isExpanded: true,
              decoration: const InputDecoration(labelText: 'Employee', contentPadding: EdgeInsets.symmetric(horizontal: 12, vertical: 8)),
              items: [const DropdownMenuItem(value: '', child: Text('All employees')), for (final e in _employees) DropdownMenuItem(value: e.value, child: Text(e.label))],
              onChanged: (v) {
                setState(() => _employeeId = v ?? '');
                _load();
              },
            ),
            const SizedBox(height: 8),
            Align(
              alignment: Alignment.centerLeft,
              child: Wrap(spacing: 6, children: [
                for (final (key, label) in const [('missing_punch', 'Missing punch'), ('config_error', 'Config error'), ('pending_approval', 'Pending approval')])
                  FilterChip(label: Text(label), selected: _exceptions.contains(key), onSelected: (v) => setState(() => v ? _exceptions.add(key) : _exceptions.remove(key))),
              ]),
            ),
          ]),
        ),
        Expanded(
          child: _loading
              ? const ListSkeleton()
              : _error != null
                  ? StateMessage(icon: Icons.error_outline_rounded, tone: Tone.danger, title: 'Something went wrong', message: _error!.message, actionLabel: 'Retry', onAction: _load)
                  : RefreshIndicator(
                      onRefresh: _load,
                      child: ListView(
                        padding: const EdgeInsets.all(16),
                        children: [
                          if (_days.isNotEmpty) AttendanceSummaryCard(summary: summary, selectedBucket: _bucket, onBucketTap: (b) => setState(() => _bucket = b)),
                          const SizedBox(height: 8),
                          if (visible.isEmpty) const SizedBox(height: 300, child: StateMessage(icon: Icons.groups_outlined, title: 'Nothing to show', message: 'No attendance days match these filters.')),
                          for (final d in visible)
                            AttendanceDayTile(
                              day: d,
                              employeeLabel: _name(d.employeeId),
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
