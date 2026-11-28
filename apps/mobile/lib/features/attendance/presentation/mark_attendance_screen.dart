import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api/api_client.dart';
import '../../../core/api/api_error.dart';
import '../../../core/forms/choice_sources.dart';
import '../../../core/forms/form_spec.dart';
import '../../../core/format.dart';
import '../../../core/providers.dart';
import '../../../core/time.dart';
import '../../auth/state/auth_controller.dart';
import '../data/attendance_repository.dart';
import '../domain/mark_day.dart';

/// Opens "Mark attendance" and reports whether anything was recorded. Pass [employees] to start
/// with people chosen; [lockEmployees] keeps exactly those (the employee's own Attendance tab).
Future<bool> openMarkAttendance(BuildContext context, {List<Choice> employees = const [], bool lockEmployees = false, String? date, DateTime? now}) async {
  final recorded = await Navigator.of(context).push<bool>(
    MaterialPageRoute(builder: (_) => MarkAttendanceScreen(initialEmployees: employees, lockEmployees: lockEmployees, initialDate: date, now: now)),
  );
  return recorded ?? false;
}

enum _Step { edit, review, done }

/// HR marks a whole day (an IN and an OUT) for one or more employees. Mirrors
/// `apps/web/src/components/attendance/mark-day-dialog.tsx`.
///
/// Two steps, never one: **Review** asks the server what would happen to each employee, and only
/// **Confirm** writes. The confirm sends just the employees the review marked ready, under one
/// idempotency key kept for the whole review, so a retry cannot record anyone twice. Changing any
/// field after a review discards it. Times are wall-clock times in the company zone.
class MarkAttendanceScreen extends ConsumerStatefulWidget {
  const MarkAttendanceScreen({super.key, this.initialEmployees = const [], this.lockEmployees = false, this.initialDate, this.now});
  final List<Choice> initialEmployees;
  final bool lockEmployees;
  final String? initialDate;

  /// The current instant (tests pin it).
  final DateTime? now;

  @override
  ConsumerState<MarkAttendanceScreen> createState() => _MarkAttendanceScreenState();
}

class _MarkAttendanceScreenState extends ConsumerState<MarkAttendanceScreen> {
  late List<Choice> _selected = [...widget.initialEmployees];
  List<Choice> _directory = const [];
  bool _directoryLoading = false;
  bool _directoryFailed = false;
  String _query = '';

  late String _date;
  String _inTime = '09:00';
  String _outTime = '18:00';
  final _reason = TextEditingController();

  _Step _step = _Step.edit;
  ManualDayResponse? _preview;
  ManualDayResponse? _result;
  String? _error;
  bool _busy = false;
  String? _submitKey;
  bool _recorded = false;

  String get _zone => ref.read(authControllerProvider).user?.companyTimezone ?? 'Asia/Kolkata';
  DateTime get _now => widget.now ?? DateTime.now();
  String get _today => businessToday(_zone, now: _now);
  AttendanceRepository get _repo => ref.read(attendanceRepositoryProvider);

  @override
  void initState() {
    super.initState();
    _date = widget.initialDate ?? businessToday(ref.read(authControllerProvider).user?.companyTimezone ?? 'Asia/Kolkata', now: widget.now);
    if (!widget.lockEmployees) _loadDirectory();
  }

  @override
  void dispose() {
    _reason.dispose();
    super.dispose();
  }

  Future<void> _loadDirectory() async {
    setState(() {
      _directoryLoading = true;
      _directoryFailed = false;
    });
    try {
      final c = await loadChoices(ref.read(apiClientProvider), const ['employees']);
      if (mounted) setState(() => _directory = c['employees'] ?? const []);
    } catch (_) {
      if (mounted) setState(() => _directoryFailed = true);
    } finally {
      if (mounted) setState(() => _directoryLoading = false);
    }
  }

  /// Any edit invalidates a review: what was checked is no longer what would be sent.
  void _edited(VoidCallback change) {
    setState(() {
      change();
      if (_step != _Step.edit) {
        _step = _Step.edit;
        _preview = null;
        _submitKey = null;
      }
      _error = null;
    });
  }

  MarkDayInstants? get _instants => markDayInstants(date: _date, inTime: _inTime, outTime: _outTime, zone: _zone);

  String _errorText(Object e) {
    if (e is ApiError) return e.status == 403 ? "You don't have permission to mark attendance for other employees." : describeApiError(e);
    return 'Something went wrong.';
  }

  Future<void> _review() async {
    final problem = markDayProblem(selectedCount: _selected.length, instants: _instants, date: _date, today: _today, reason: _reason.text, now: _now);
    if (problem != null) return setState(() => _error = problem);
    final instants = _instants!;
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      final data = await _repo.previewDayEntries(employeeIds: [for (final e in _selected) e.value], punchInAt: instants.punchIn, punchOutAt: instants.punchOut, reason: _reason.text.trim());
      if (!mounted) return;
      setState(() {
        _preview = data;
        _submitKey = ApiClient.newIdempotencyKey();
        _step = _Step.review;
      });
    } catch (e) {
      if (mounted) setState(() => _error = _errorText(e));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _confirm() async {
    final preview = _preview;
    final instants = _instants;
    if (preview == null || instants == null) return;
    final ready = [for (final r in preview.results) if (r.isReady) r.employeeId];
    if (ready.isEmpty) return;
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      _submitKey ??= ApiClient.newIdempotencyKey();
      final data = await _repo.recordDayEntries(employeeIds: ready, punchInAt: instants.punchIn, punchOutAt: instants.punchOut, reason: _reason.text.trim(), idempotencyKey: _submitKey!);
      if (!mounted) return;
      setState(() {
        _result = data;
        _step = _Step.done;
        _recorded = data.recordedCount > 0 || _recorded;
      });
      if (data.recordedCount > 0) {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('Attendance marked for ${data.recordedCount} employee${data.recordedCount == 1 ? '' : 's'}.')));
      }
    } catch (e) {
      // The key is kept: pressing Confirm again resends the same submission, and the server
      // returns what it already stored instead of storing it twice.
      if (mounted) setState(() => _error = _errorText(e));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  String _name(String employeeId) {
    for (final c in [..._selected, ..._directory]) {
      if (c.value == employeeId) return c.label;
    }
    return 'Employee';
  }

  Future<void> _pickDate() async {
    final current = DateTime.tryParse(_date) ?? _now;
    final today = DateTime.parse(_today);
    final picked = await showDatePicker(context: context, initialDate: current.isAfter(today) ? today : current, firstDate: DateTime(2020), lastDate: today);
    if (picked == null) return;
    _edited(() => _date = '${picked.year.toString().padLeft(4, '0')}-${picked.month.toString().padLeft(2, '0')}-${picked.day.toString().padLeft(2, '0')}');
  }

  Future<void> _pickTime(bool isIn) async {
    final raw = (isIn ? _inTime : _outTime).split(':');
    final picked = await showTimePicker(context: context, initialTime: TimeOfDay(hour: int.tryParse(raw[0]) ?? 9, minute: int.tryParse(raw[1]) ?? 0));
    if (picked == null) return;
    final text = '${picked.hour.toString().padLeft(2, '0')}:${picked.minute.toString().padLeft(2, '0')}';
    _edited(() => isIn ? _inTime = text : _outTime = text);
  }

  Widget _employees(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    if (widget.lockEmployees) {
      return InputDecorator(
        decoration: const InputDecoration(labelText: 'Employee', border: OutlineInputBorder(), isDense: true),
        child: Text(_selected.map((e) => e.label).join(', ')),
      );
    }
    final ownId = ref.read(authControllerProvider).user?.employeeId;
    final q = _query.trim().toLowerCase();
    final selectedIds = {for (final e in _selected) e.value};
    final atCap = _selected.length >= markDayMaxEmployees;
    final visible = [
      for (final c in _directory)
        if (c.value != ownId && (q.isEmpty || c.label.toLowerCase().contains(q))) c,
    ];
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      const Text('Employees', style: TextStyle(fontWeight: FontWeight.w700)),
      const SizedBox(height: 8),
      if (_selected.isNotEmpty)
        Wrap(spacing: 6, runSpacing: 6, children: [
          for (final e in _selected) InputChip(label: Text(e.label), onDeleted: () => _edited(() => _selected = [for (final s in _selected) if (s.value != e.value) s])),
        ]),
      if (_selected.isNotEmpty) const SizedBox(height: 8),
      TextField(
        decoration: const InputDecoration(isDense: true, border: OutlineInputBorder(), prefixIcon: Icon(Icons.search), hintText: 'Filter employees'),
        onChanged: (v) => setState(() => _query = v),
      ),
      const SizedBox(height: 8),
      Container(
        height: 220,
        decoration: BoxDecoration(border: Border.all(color: scheme.outlineVariant), borderRadius: BorderRadius.circular(8)),
        child: _directoryLoading && _directory.isEmpty
            ? const Center(child: CircularProgressIndicator(strokeWidth: 2))
            : visible.isEmpty
                ? Center(child: Text('No employee matches.', style: TextStyle(color: scheme.onSurfaceVariant)))
                : ListView(children: [
                    for (final c in visible)
                      CheckboxListTile(
                        dense: true,
                        value: selectedIds.contains(c.value),
                        title: Text(c.label),
                        onChanged: (!selectedIds.contains(c.value) && atCap)
                            ? null
                            : (on) => _edited(() => _selected = on == true ? [..._selected, c] : [for (final s in _selected) if (s.value != c.value) s]),
                      ),
                  ]),
      ),
      const SizedBox(height: 4),
      Row(children: [
        Expanded(child: Text('${_selected.length} selected${atCap ? ' (the limit is $markDayMaxEmployees at a time)' : ''}.', style: TextStyle(fontSize: 12, color: scheme.onSurfaceVariant))),
        if (_directoryFailed) TextButton(onPressed: _loadDirectory, child: const Text('Retry loading')),
      ]),
    ]);
  }

  Widget _reviewList(BuildContext context, ManualDayResponse preview) {
    final scheme = Theme.of(context).colorScheme;
    return Container(
      key: const Key('mark-day-review'),
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(border: Border.all(color: scheme.outlineVariant), borderRadius: BorderRadius.circular(12)),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text('${preview.readyCount} ready${preview.blockedCount > 0 ? ' · ${preview.blockedCount} will be skipped' : ''}', style: const TextStyle(fontWeight: FontWeight.w700)),
        const SizedBox(height: 8),
        for (final r in preview.results)
          Padding(
            padding: const EdgeInsets.only(bottom: 8),
            child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Icon(r.isReady ? Icons.check_circle_rounded : Icons.block_rounded, size: 18, color: r.isReady ? scheme.primary : scheme.error, semanticLabel: r.isReady ? 'Ready' : 'Skipped'),
              const SizedBox(width: 8),
              Expanded(
                child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Text(_name(r.employeeId)),
                  if (r.isBlocked)
                    Text(
                      '${r.blockReason}${r.existingPunches.isEmpty ? '' : ' Existing: ${r.existingPunches.map((p) => '${p.direction} ${formatClockTime(p.punchTime, _zone)}').join(', ')}.'}',
                      style: TextStyle(fontSize: 12, color: scheme.onSurfaceVariant),
                    ),
                ]),
              ),
            ]),
          ),
      ]),
    );
  }

  Widget _done(BuildContext context, ManualDayResponse result) {
    final scheme = Theme.of(context).colorScheme;
    final blocked = [for (final r in result.results) if (r.isBlocked) r];
    return Column(key: const Key('mark-day-done'), crossAxisAlignment: CrossAxisAlignment.start, children: [
      Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Icon(Icons.check_circle_rounded, color: scheme.primary),
        const SizedBox(width: 8),
        Expanded(child: Text('Marked for ${result.recordedCount} employee${result.recordedCount == 1 ? '' : 's'}. Their attendance has been recalculated.')),
      ]),
      if (blocked.isNotEmpty) ...[
        const SizedBox(height: 12),
        Text('Not recorded (${blocked.length}). Something changed since the review:', style: const TextStyle(fontWeight: FontWeight.w700)),
        const SizedBox(height: 6),
        for (final r in blocked) Padding(padding: const EdgeInsets.only(bottom: 4), child: Text('${_name(r.employeeId)}: ${r.blockReason}', style: TextStyle(color: scheme.onSurfaceVariant))),
      ],
    ]);
  }

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final instants = _instants;
    final zone = zoneLabel(_zone);
    final readyCount = _preview?.readyCount ?? 0;
    final done = _step == _Step.done && _result != null;
    return PopScope(
      canPop: !_busy,
      onPopInvokedWithResult: (didPop, _) {},
      child: Scaffold(
        appBar: AppBar(
          title: const Text('Mark attendance'),
          leading: BackButton(onPressed: _busy ? null : () => Navigator.of(context).pop(_recorded)),
        ),
        body: ListView(
          padding: const EdgeInsets.fromLTRB(16, 8, 16, 32),
          children: [
            Text('Records an IN and an OUT punch for each employee. Each punch is marked as entered by HR and saved to the audit log with your reason.', style: TextStyle(color: scheme.onSurfaceVariant)),
            const SizedBox(height: 16),
            if (done)
              _done(context, _result!)
            else ...[
              _employees(context),
              const SizedBox(height: 16),
              Wrap(spacing: 8, runSpacing: 8, children: [
                OutlinedButton.icon(key: const Key('mark-day-date'), onPressed: _pickDate, icon: const Icon(Icons.calendar_today_outlined, size: 16), label: Text(formatFullDate(_date))),
                OutlinedButton(key: const Key('mark-day-in'), onPressed: () => _pickTime(true), child: Text('IN $_inTime ($zone)')),
                OutlinedButton(key: const Key('mark-day-out'), onPressed: () => _pickTime(false), child: Text('OUT $_outTime ($zone)')),
              ]),
              if (instants != null) ...[
                const SizedBox(height: 8),
                Text(
                  '${formatFullDate(_date)} $_inTime → ${instants.overnight ? '${formatFullDate(instants.outDate)} ' : ''}$_outTime · ${formatMarkDaySpan(instants.spanMinutes)}${instants.overnight ? ' · OUT is next day' : ''}',
                  key: const Key('mark-day-summary'),
                  style: TextStyle(color: scheme.onSurfaceVariant),
                ),
              ],
              const SizedBox(height: 16),
              TextField(
                controller: _reason,
                maxLength: 200,
                decoration: const InputDecoration(labelText: 'Reason', helperText: 'Saved on every punch and in the audit log.', border: OutlineInputBorder(), isDense: true),
                onChanged: (_) => _edited(() {}),
              ),
              Wrap(spacing: 6, runSpacing: 6, children: [
                for (final preset in markDayReasonPresets)
                  ChoiceChip(label: Text(preset), selected: _reason.text == preset, onSelected: (_) => _edited(() => _reason.text = preset)),
              ]),
              if (_step == _Step.review && _preview != null) ...[const SizedBox(height: 16), _reviewList(context, _preview!)],
              if (_error != null) Padding(padding: const EdgeInsets.only(top: 12), child: Text(_error!, key: const Key('mark-day-error'), style: TextStyle(color: scheme.error))),
            ],
            const SizedBox(height: 20),
            if (done)
              FilledButton(onPressed: () => Navigator.of(context).pop(_recorded), child: const Text('Close'))
            else if (_step == _Step.edit)
              FilledButton(key: const Key('mark-day-review-button'), onPressed: _busy ? null : _review, child: Text(_busy ? 'Checking…' : 'Review'))
            else
              FilledButton(
                key: const Key('mark-day-confirm'),
                onPressed: (_busy || readyCount == 0) ? null : _confirm,
                child: Text(_busy ? 'Recording…' : readyCount == 0 ? 'Nothing to record' : 'Confirm for $readyCount employee${readyCount == 1 ? '' : 's'}'),
              ),
          ],
        ),
      ),
    );
  }
}
