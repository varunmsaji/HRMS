import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api/api_error.dart';
import '../../../core/providers.dart';
import '../../../core/time.dart';
import '../../../core/widgets/ui.dart';
import '../../auth/state/auth_controller.dart';

typedef _Rec = Map<String, dynamic>;

const dayTypeLabels = {'WORKING': 'Working day', 'WEEKLY_OFF': 'Weekly off', 'HOLIDAY': 'Holiday', 'SPECIAL_WORKING': 'Special working day', 'SHUTDOWN': 'Shutdown'};

const _maxRowsShown = 100;
const _maxLeaveShown = 10;

/// "Weekly off (half day) — Founders Day", "Working day", "Not set up". Same text as the web
/// `describeSnapshot`.
String describeDaySnapshot(Map<String, dynamic> snapshot) {
  final type = snapshot['day_type'] as String?;
  if (snapshot['configured'] != true || type == null) return 'Not set up';
  final base = dayTypeLabels[type] ?? type;
  final fraction = double.tryParse('${snapshot['weekly_off_fraction']}');
  final half = type == 'WEEKLY_OFF' && fraction != null && fraction < 1 ? ' (half day)' : '';
  final label = snapshot['label'] as String?;
  return label == null || label.isEmpty ? '$base$half' : '$base$half — $label';
}

/// Previews a calendar change, then applies it once confirmed. Resolves true only when the server
/// applied it; nothing is saved before that.
Future<bool> reviewCalendarChange(BuildContext context, {required String title, required Map<String, dynamic> change}) async {
  final applied = await Navigator.of(context).push<bool>(MaterialPageRoute(fullscreenDialog: true, builder: (_) => ChangeImpactScreen(title: title, change: change)));
  return applied == true;
}

/// Mirrors the web `change-impact-dialog.tsx`: the preview is read-only, and "Confirm change" resends
/// the change with the preview's digest so the server can refuse if anything moved since.
class ChangeImpactScreen extends ConsumerStatefulWidget {
  const ChangeImpactScreen({super.key, required this.title, required this.change});

  final String title;
  final Map<String, dynamic> change;

  @override
  ConsumerState<ChangeImpactScreen> createState() => _ChangeImpactScreenState();
}

class _ChangeImpactScreenState extends ConsumerState<ChangeImpactScreen> {
  late String _from;
  late String _to;
  _Rec? _preview;
  ({String from, String to})? _previewedWindow;
  bool _loading = true;
  bool _applying = false;
  bool _stale = false;
  bool _acknowledged = false;
  String? _error;
  int _request = 0;

  @override
  void initState() {
    super.initState();
    final zone = ref.read(authControllerProvider).user?.companyTimezone ?? 'Asia/Kolkata';
    _from = businessToday(zone);
    _to = _isoDate(DateTime.parse(_from).add(const Duration(days: 179)));
    _load();
  }

  String _isoDate(DateTime d) => '${d.year.toString().padLeft(4, '0')}-${d.month.toString().padLeft(2, '0')}-${d.day.toString().padLeft(2, '0')}';

  bool get _windowValid => _from.compareTo(_to) <= 0;

  String _describe(Object e) {
    if (e is! ApiError) return 'Something went wrong.';
    if (e.status == 403) return "You don't have permission to do that.";
    return e.message;
  }

  Future<void> _load() async {
    if (!_windowValid) return;
    final mine = ++_request;
    setState(() {
      _loading = true;
      _error = null;
      _stale = false;
      _acknowledged = false;
    });
    try {
      final preview = await ref.read(apiClientProvider).post<_Rec>(
            '/work-calendar-changes/preview',
            body: {'change': widget.change, 'window_from': _from, 'window_to': _to},
            parse: (d) => d as _Rec,
          );
      if (!mounted || mine != _request) return;
      setState(() {
        _preview = preview;
        _previewedWindow = (from: _from, to: _to);
      });
    } catch (e) {
      if (!mounted || mine != _request) return;
      setState(() {
        _preview = null;
        _error = e is ApiError && e.code == 'STALE_RESOURCE' ? 'This record was changed by someone else after you opened it. Go back and reopen it to see the latest values.' : _describe(e);
      });
    } finally {
      if (mounted && mine == _request) setState(() => _loading = false);
    }
  }

  Future<void> _confirm() async {
    final preview = _preview;
    final window = _previewedWindow;
    if (preview == null || window == null) return;
    setState(() {
      _applying = true;
      _error = null;
    });
    try {
      await ref.read(apiClientProvider).post<Object?>(
            '/work-calendar-changes/confirm',
            body: {
              'change': widget.change,
              'window_from': window.from,
              'window_to': window.to,
              'impact_digest': preview['impact_digest'],
              'acknowledge_protected_impact': _acknowledged,
            },
            parse: (_) => null,
          );
      if (mounted) Navigator.of(context).pop(true);
    } catch (e) {
      if (!mounted) return;
      setState(() {
        if (e is ApiError && e.code == 'CALENDAR_PREVIEW_STALE') {
          _stale = true;
        } else {
          _error = _describe(e);
        }
      });
    } finally {
      if (mounted) setState(() => _applying = false);
    }
  }

  Future<void> _pick({required bool from}) async {
    final current = DateTime.parse(from ? _from : _to);
    final picked = await showDatePicker(context: context, initialDate: current, firstDate: DateTime(current.year - 5), lastDate: DateTime(current.year + 5));
    if (picked == null || !mounted) return;
    setState(() {
      if (from) {
        _from = _isoDate(picked);
      } else {
        _to = _isoDate(picked);
      }
    });
    _load();
  }

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final preview = _preview;
    final canConfirm = preview != null && _windowValid && !_loading && !_applying && !_stale && (preview['requires_acknowledgement'] != true || _acknowledged);
    return Scaffold(
      appBar: AppBar(title: Text('${widget.title}: review impact')),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          Row(children: [
            Expanded(child: OutlinedButton(onPressed: () => _pick(from: true), child: Text('From $_from'))),
            const SizedBox(width: 8),
            Expanded(child: OutlinedButton(onPressed: () => _pick(from: false), child: Text('To $_to'))),
          ]),
          const SizedBox(height: 6),
          Text('Nothing is saved until you confirm. Windows are limited to one year.', style: TextStyle(fontSize: 12, color: scheme.onSurfaceVariant)),
          if (!_windowValid) _Notice('Choose a start date that is not after the end date.', color: scheme.error),
          if (_error != null) _Notice(_error!, color: scheme.error),
          if (_stale) ...[
            _Notice('The configuration, leave or payroll data changed since you previewed it. Nothing was applied. Review a fresh preview before confirming.', color: scheme.error),
            Align(alignment: Alignment.centerLeft, child: OutlinedButton(onPressed: _load, child: const Text('Refresh preview'))),
          ],
          if (_loading)
            const Padding(padding: EdgeInsets.all(24), child: Center(child: CircularProgressIndicator(strokeWidth: 2.5)))
          else if (preview != null) ...[
            const SizedBox(height: 12),
            _PreviewBody(preview: preview),
            if (preview['requires_acknowledgement'] == true)
              CheckboxListTile(
                contentPadding: EdgeInsets.zero,
                controlAffinity: ListTileControlAffinity.leading,
                value: _acknowledged,
                onChanged: (v) => setState(() => _acknowledged = v == true),
                title: const Text('I understand that existing leave days, locked attendance periods and payroll runs listed above will not be changed, and I have reviewed them.'),
              ),
          ],
        ],
      ),
      bottomNavigationBar: SafeArea(
        child: Padding(
          padding: const EdgeInsets.all(12),
          child: Row(children: [
            Expanded(child: OutlinedButton(onPressed: _applying ? null : () => Navigator.of(context).pop(false), child: const Text('Back'))),
            const SizedBox(width: 12),
            Expanded(child: FilledButton(onPressed: canConfirm ? _confirm : null, child: Text(_applying ? 'Applying…' : 'Confirm change'))),
          ]),
        ),
      ),
    );
  }
}

class _Notice extends StatelessWidget {
  const _Notice(this.text, {required this.color});
  final String text;
  final Color color;

  @override
  Widget build(BuildContext context) => Padding(padding: const EdgeInsets.only(top: 10), child: Text(text, style: TextStyle(color: color)));
}

class _PreviewBody extends StatelessWidget {
  const _PreviewBody({required this.preview});
  final _Rec preview;

  List<_Rec> _list(_Rec m, String key) => [for (final e in (m[key] as List? ?? const [])) e as _Rec];

  @override
  Widget build(BuildContext context) {
    final muted = TextStyle(fontSize: 12, color: Theme.of(context).colorScheme.onSurfaceVariant);
    final population = preview['population'] as _Rec;
    final exact = population['complete'] == true;
    final employees = preview['affected_employee_count'] as int;
    final dates = preview['changed_date_count'] as int;
    final leave = preview['leave_impact'] as _Rec;
    final leaveItems = _list(leave, 'items');
    final incomplete = preview['incomplete_configuration'] as _Rec;
    final rows = _list(preview, 'rows');
    final periods = _list(preview, 'protected_periods');
    final excluded = preview['excluded_not_employed_employee_dates'] as int;
    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      AppCard(
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text('${exact ? '' : 'At least '}$employees ${employees == 1 ? 'employee' : 'employees'} affected on $dates ${dates == 1 ? 'date' : 'dates'} between ${preview['window_from']} and ${preview['window_to']}.', style: const TextStyle(fontWeight: FontWeight.w600)),
          const SizedBox(height: 4),
          Text('${population['employees_analysed']} of ${population['employees_in_scope']} employees in scope were analysed${exact ? '.' : ' — the population is larger than the preview limit, so these counts are a lower bound.'}', style: muted),
        ]),
      ),
      for (final w in _list(preview, 'warnings')) Padding(padding: const EdgeInsets.only(top: 10), child: Text('Notice: ${w['message']}')),
      if ((incomplete['employees'] as int) > 0)
        Padding(
          padding: const EdgeInsets.only(top: 10),
          child: Text('Incomplete configuration: ${incomplete['employees']} employee(s) have ${incomplete['dates']} date(s) with no work calendar, so their impact cannot be fully calculated.'),
        ),
      const SizedBox(height: 16),
      if (rows.isEmpty)
        const Text("No employee's day classification changes in this window.")
      else ...[
        const SectionHeader('Changed dates'),
        for (final row in rows.take(_maxRowsShown))
          ListTile(
            contentPadding: EdgeInsets.zero,
            dense: true,
            title: Text('${row['date']} · ${describeDaySnapshot(row['previous'] as _Rec)} → ${describeDaySnapshot(row['proposed'] as _Rec)}'),
            trailing: Text('${row['affected_employee_count']}', style: const TextStyle(fontWeight: FontWeight.w700)),
          ),
        if (preview['rows_truncated'] == true || rows.length > _maxRowsShown) Text('Showing the first ${rows.length < _maxRowsShown ? rows.length : _maxRowsShown} changes only.', style: muted),
      ],
      const SizedBox(height: 16),
      const SectionHeader('Leave'),
      Text('${leave['approved_day_records']} approved and ${leave['pending_day_records']} pending leave day record(s) fall on changed dates. Existing leave is never recalculated or approved or rejected by this change.'),
      for (final item in leaveItems.take(_maxLeaveShown))
        Padding(
          padding: const EdgeInsets.only(top: 4),
          child: Text('${item['employee_code']}, ${item['date']}: ${item['status'] == 'APPROVED' ? 'Approved' : 'Pending'} leave, day becomes ${item['proposed_day_type'] ?? 'unresolved'}', style: muted),
        ),
      if (leave['items_truncated'] == true || leaveItems.length > _maxLeaveShown) Padding(padding: const EdgeInsets.only(top: 4), child: Text('More leave records are affected than shown.', style: muted)),
      if (periods.isNotEmpty) ...[
        const SizedBox(height: 16),
        const SectionHeader('Locked attendance and payroll'),
        for (final p in periods)
          Padding(
            padding: const EdgeInsets.only(bottom: 4),
            child: Text('${p['kind'] == 'ATTENDANCE_PERIOD' ? 'Attendance period' : 'Pay run'} ${p['period_start']} to ${p['period_end']} (${(p['status'] as String).toLowerCase().replaceFirst('_', ' ')}): ${p['changed_dates_in_period']} changed date(s). Not recalculated.'),
          ),
      ],
      if (excluded > 0) Padding(padding: const EdgeInsets.only(top: 10), child: Text('$excluded employee-date(s) were left out because the employee was not employed on that date.', style: muted)),
      const SizedBox(height: 8),
    ]);
  }
}
