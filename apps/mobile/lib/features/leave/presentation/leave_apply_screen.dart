import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api/api_client.dart';
import '../../../core/api/api_error.dart';
import '../../../core/format.dart';
import '../../../core/providers.dart';
import '../../../core/time.dart' show businessToday;
import '../../../core/widgets/employee/interaction.dart';
import '../../../core/widgets/ui.dart';
import '../../attendance/data/schedule_repository.dart';
import '../../attendance/domain/employee_calendar.dart';
import '../../auth/presentation/widgets/auth_form_field.dart';
import '../../auth/state/auth_controller.dart';
import '../data/leave_repository.dart';

/// One leave type as the form needs it: its name, the employee's balance (null when the type keeps
/// no balance row for them), and whether it is maternity leave (which asks for a delivery date).
class LeaveTypeOption {
  const LeaveTypeOption({required this.id, required this.name, this.balance, this.maternity = false});
  final String id;
  final String name;
  final num? balance;
  final bool maternity;
}

/// The employee's own apply-for-leave form (audit MOB-UX-012). Unlike the generic record form it
/// replaces for self-service:
/// * leave types are chips that show what is left of each;
/// * one date-range picker sets both dates (a one-day leave is one tap), and half day is offered
///   only for a single day;
/// * the expected delivery date appears only for maternity leave, and the document reference only
///   on request;
/// * a summary states the days selected and the working days on the employee's own calendar, and
///   says plainly that the leave rules decide the days charged (the server counts, not the app);
/// * the submit button stays on screen, says "Submit request", and leaving with changes asks first.
///
/// The request body is the one the old form sent (`LeaveApplicationCreate`); the server validates.
class LeaveApplyScreen extends ConsumerStatefulWidget {
  const LeaveApplyScreen({super.key});

  @override
  ConsumerState<LeaveApplyScreen> createState() => _LeaveApplyScreenState();
}

const _halfDayLabels = {'': 'Full day', 'FIRST_HALF': 'First half', 'SECOND_HALF': 'Second half'};

class _LeaveApplyScreenState extends ConsumerState<LeaveApplyScreen> {
  List<LeaveTypeOption>? _types;
  String? _loadError;

  String? _typeId;
  String? _start;
  String? _end;
  String _halfDay = '';
  String? _deliveryDate;
  final _reason = TextEditingController();
  final _attachment = TextEditingController();
  bool _showAttachment = false;

  /// Working days on the employee's calendar for the chosen dates; null while unknown.
  int? _workingDays;
  int _calendarRequest = 0;

  Map<String, String> _errors = {};
  String? _banner;
  bool _saving = false;
  bool _dirty = false;

  /// One key per attempt: a retry after "no response" is not booked twice.
  String? _idempotencyKey;

  String get _zone => ref.read(authControllerProvider).user?.companyTimezone ?? 'Asia/Kolkata';

  LeaveTypeOption? get _type => _types?.where((t) => t.id == _typeId).firstOrNull;

  bool get _singleDay => _start != null && _start == _end;

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void dispose() {
    _reason.dispose();
    _attachment.dispose();
    super.dispose();
  }

  Future<void> _load() async {
    setState(() => _loadError = null);
    final employeeId = ref.read(authControllerProvider).user?.employeeId;
    final client = ref.read(apiClientProvider);
    try {
      final typesFuture = client.getList<Map<String, dynamic>>('/leave-types', query: PageQuery(page: 1, perPage: 100), parseItem: (d) => d as Map<String, dynamic>);
      // Balances are a help, not a requirement: without them the chips just show names.
      Future<List<LeaveBalance>> readBalances() async {
        if (employeeId == null) return const [];
        try {
          return await ref.read(leaveRepositoryProvider).listLeaveBalances(employeeId);
        } catch (_) {
          return const [];
        }
      }

      final balancesFuture = readBalances();
      final types = await typesFuture;
      final balances = await balancesFuture;
      final byType = {for (final b in balances) b.leaveTypeId: b.balance};
      if (!mounted) return;
      setState(() {
        _types = [
          for (final t in types.data)
            if (t['is_active'] != false)
              LeaveTypeOption(
                id: t['id'] as String,
                name: (t['name'] as String?) ?? 'Leave',
                balance: byType[t['id']],
                maternity: t['statutory_category'] == 'MATERNITY',
              ),
        ];
      });
    } catch (e) {
      if (mounted) setState(() => _loadError = e is ApiError ? e.message : 'Something went wrong.');
    }
  }

  void _changed(VoidCallback change) => setState(() {
        change();
        _dirty = true;
      });

  Future<void> _pickDates() async {
    final today = DateTime.parse(businessToday(_zone));
    final initial = _start == null ? null : DateTimeRange(start: DateTime.parse(_start!), end: DateTime.parse(_end ?? _start!));
    final picked = await showDateRangePicker(
      context: context,
      firstDate: today.subtract(const Duration(days: 365)),
      lastDate: today.add(const Duration(days: 365 * 2)),
      initialDateRange: initial,
      helpText: 'Leave dates',
      saveText: 'Done',
    );
    if (picked == null) return;
    String iso(DateTime d) => '${d.year.toString().padLeft(4, '0')}-${d.month.toString().padLeft(2, '0')}-${d.day.toString().padLeft(2, '0')}';
    _changed(() {
      _start = iso(picked.start);
      _end = iso(picked.end);
      if (!_singleDay) _halfDay = '';
      _errors = {..._errors}..remove('dates');
    });
    _countWorkingDays();
  }

  /// Working days between the chosen dates on the employee's own calendar. A failure, or a
  /// calendar that is not fully set up, leaves the figure out rather than guessing.
  Future<void> _countWorkingDays() async {
    final start = _start, end = _end;
    if (start == null || end == null) return;
    final mine = ++_calendarRequest;
    setState(() => _workingDays = null);
    try {
      final calendar = await ref.read(scheduleRepositoryProvider).getMyCalendar(from: start, to: end);
      if (!mounted || mine != _calendarRequest || calendar.configuration != 'COMPLETE') return;
      final working = calendar.days.where((d) => d.kind == CalendarDayKind.working || d.kind == CalendarDayKind.specialWorking).length;
      setState(() => _workingDays = working);
    } catch (_) {}
  }

  Future<void> _pickDeliveryDate() async {
    final today = DateTime.parse(businessToday(_zone));
    final picked = await showDatePicker(
      context: context,
      initialDate: _deliveryDate == null ? today : DateTime.parse(_deliveryDate!),
      firstDate: today.subtract(const Duration(days: 365)),
      lastDate: today.add(const Duration(days: 365)),
      helpText: 'Expected delivery date',
    );
    if (picked == null) return;
    _changed(() => _deliveryDate = '${picked.year.toString().padLeft(4, '0')}-${picked.month.toString().padLeft(2, '0')}-${picked.day.toString().padLeft(2, '0')}');
  }

  Map<String, String> _validate() => {
        if (_typeId == null) 'leave_type_id': 'Choose a leave type.',
        if (_start == null) 'dates': 'Choose the dates of your leave.',
      };

  Future<void> _submit() async {
    final errors = _validate();
    setState(() {
      _errors = errors;
      _banner = errors.isEmpty ? null : 'Please fix the highlighted fields.';
    });
    if (errors.isNotEmpty) return;
    final body = <String, dynamic>{
      'leave_type_id': _typeId,
      'start_date': _start,
      'end_date': _end,
      if (_singleDay && _halfDay.isNotEmpty) 'half_day': _halfDay,
      if (_reason.text.trim().isNotEmpty) 'reason': _reason.text.trim(),
      if (_attachment.text.trim().isNotEmpty) 'attachment_reference': _attachment.text.trim(),
      if ((_type?.maternity ?? false) && _deliveryDate != null) 'expected_delivery_date': _deliveryDate,
    };
    _idempotencyKey ??= ApiClient.newIdempotencyKey();
    setState(() => _saving = true);
    try {
      await ref.read(leaveRepositoryProvider).submitLeaveApplication(body, idempotencyKey: _idempotencyKey);
      if (!mounted) return;
      setState(() => _dirty = false);
      Navigator.of(context).pop(true);
    } on ApiError catch (e) {
      if (!mounted) return;
      // A real answer settles this attempt; only "no response" keeps the key for a retry.
      if (e.status != 0) _idempotencyKey = null;
      final fieldErrors = <String, String>{};
      for (final d in e.details) {
        final key = d.field?.split('.').last;
        if (key == 'start_date' || key == 'end_date') {
          fieldErrors['dates'] = d.message;
        } else if (key != null) {
          fieldErrors[key] = d.message;
        }
      }
      setState(() {
        _errors = fieldErrors;
        _banner = e.status == 403 ? "You don't have permission to do that." : (fieldErrors.isEmpty ? describeApiError(e) : 'Please fix the highlighted fields.');
      });
    } catch (_) {
      if (mounted) setState(() => _banner = 'Something went wrong. Please try again.');
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  Future<void> _confirmLeave() async {
    final discard = await confirmDestructive(
      context,
      title: 'Discard this request?',
      body: 'Your leave request has not been submitted.',
      confirmLabel: 'Discard',
      cancelLabel: 'Keep editing',
    );
    if (!discard || !mounted) return;
    setState(() => _dirty = false);
    Navigator.of(context).pop();
  }

  String _datesLabel() {
    if (_start == null) return 'Choose dates';
    if (_singleDay) return formatDayDate(_start!);
    return '${formatDayDate(_start!)} – ${formatDayDate(_end!)}';
  }

  String? _summary() {
    if (_start == null) return null;
    final days = DateTime.parse(_end!).difference(DateTime.parse(_start!)).inDays + 1;
    final selected = _singleDay && _halfDay.isNotEmpty ? 'Half a day selected' : '$days ${days == 1 ? 'day' : 'days'} selected';
    final working = _workingDays == null || _singleDay ? '' : ' · $_workingDays working ${_workingDays == 1 ? 'day' : 'days'} on your calendar';
    return '$selected$working';
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final muted = theme.colorScheme.onSurfaceVariant;
    final types = _types;
    Widget body;
    if (_loadError != null) {
      body = StateMessage(icon: Icons.cloud_off_rounded, tone: Tone.danger, title: 'Couldn\'t load leave types', message: _loadError, actionLabel: 'Try again', onAction: _load);
    } else if (types == null) {
      body = const ListSkeleton(count: 4);
    } else if (types.isEmpty) {
      body = const StateMessage(icon: Icons.event_busy_outlined, tone: Tone.warning, title: 'No leave types yet', message: 'Your company has not set up any leave types. Ask HR.');
    } else {
      final type = _type;
      final summary = _summary();
      body = WithStickyBar(
        body: ListView(
          padding: const EdgeInsets.all(16),
          children: [
            if (_banner != null) ...[InlineAlert(message: _banner!), const SizedBox(height: 16)],
            AuthFormField(
              label: 'Leave type',
              required: true,
              errorText: _errors['leave_type_id'],
              child: Wrap(spacing: 8, runSpacing: 8, children: [
                for (final t in types)
                  ChoiceChip(
                    label: Text(t.balance == null ? t.name : '${t.name} · ${formatLeaveDays(t.balance!)} left'),
                    selected: _typeId == t.id,
                    onSelected: _saving
                        ? null
                        : (_) => _changed(() {
                              _typeId = t.id;
                              _errors = {..._errors}..remove('leave_type_id');
                            }),
                  ),
              ]),
            ),
            const SizedBox(height: 18),
            AuthFormField(
              label: 'Dates',
              required: true,
              errorText: _errors['dates'],
              child: OutlinedButton.icon(
                onPressed: _saving ? null : _pickDates,
                icon: const Icon(Icons.date_range_outlined),
                label: Align(alignment: Alignment.centerLeft, child: Text(_datesLabel())),
                style: OutlinedButton.styleFrom(minimumSize: const Size.fromHeight(52), alignment: Alignment.centerLeft),
              ),
            ),
            if (_singleDay) ...[
              const SizedBox(height: 12),
              SegmentedButton<String>(
                showSelectedIcon: false,
                segments: [for (final e in _halfDayLabels.entries) ButtonSegment(value: e.key, label: Text(e.value))],
                selected: {_halfDay},
                onSelectionChanged: _saving ? null : (s) => _changed(() => _halfDay = s.first),
              ),
            ],
            if (summary != null || type?.balance != null) ...[
              const SizedBox(height: 14),
              Semantics(
                liveRegion: true,
                child: AppCard(
                  child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                    if (summary != null) Text(summary, style: const TextStyle(fontWeight: FontWeight.w600)),
                    if (type?.balance != null) ...[
                      if (summary != null) const SizedBox(height: 4),
                      Text('${type!.name}: ${formatLeaveDays(type.balance!)} available', style: TextStyle(color: muted)),
                    ],
                    const SizedBox(height: 4),
                    Text('Your company\'s leave rules decide the days charged.', style: theme.textTheme.bodySmall?.copyWith(color: muted)),
                  ]),
                ),
              ),
            ],
            if (type?.maternity ?? false) ...[
              const SizedBox(height: 18),
              AuthFormField(
                label: 'Expected delivery date',
                errorText: _errors['expected_delivery_date'],
                child: OutlinedButton.icon(
                  onPressed: _saving ? null : _pickDeliveryDate,
                  icon: const Icon(Icons.event_outlined),
                  label: Align(alignment: Alignment.centerLeft, child: Text(_deliveryDate == null ? 'Choose a date' : formatDayDate(_deliveryDate!))),
                  style: OutlinedButton.styleFrom(minimumSize: const Size.fromHeight(52), alignment: Alignment.centerLeft),
                ),
              ),
            ],
            const SizedBox(height: 18),
            AuthFormField(
              label: 'Reason',
              errorText: _errors['reason'],
              child: TextField(
                controller: _reason,
                enabled: !_saving,
                minLines: 3,
                maxLines: 6,
                keyboardType: TextInputType.multiline,
                textCapitalization: TextCapitalization.sentences,
                onChanged: (_) => _changed(() {}),
                decoration: const InputDecoration(hintText: 'Optional. Shown to your approver.'),
              ),
            ),
            const SizedBox(height: 12),
            if (_showAttachment || _attachment.text.isNotEmpty)
              AuthFormField(
                label: 'Document reference',
                description: 'For leave that needs a supporting document, such as a medical certificate number.',
                errorText: _errors['attachment_reference'],
                child: TextField(controller: _attachment, enabled: !_saving, onChanged: (_) => _changed(() {})),
              )
            else
              Align(
                alignment: Alignment.centerLeft,
                child: TextButton.icon(
                  onPressed: _saving ? null : () => setState(() => _showAttachment = true),
                  icon: const Icon(Icons.attach_file_rounded, size: 18),
                  label: const Text('Add a document reference'),
                ),
              ),
          ],
        ),
        bar: FilledButton(
          style: FilledButton.styleFrom(minimumSize: const Size.fromHeight(48)),
          onPressed: _saving ? null : _submit,
          child: Text(_saving ? 'Submitting…' : 'Submit request'),
        ),
      );
    }
    return PopScope(
      canPop: !_dirty,
      onPopInvokedWithResult: (didPop, _) {
        if (!didPop) _confirmLeave();
      },
      child: Scaffold(appBar: AppBar(title: const Text('Apply for leave')), body: body),
    );
  }
}
