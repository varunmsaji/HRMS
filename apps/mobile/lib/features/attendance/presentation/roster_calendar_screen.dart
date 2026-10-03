import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api/api_client.dart';
import '../../../core/api/api_error.dart';
import '../../../core/auth/permissions.dart';
import '../../../core/forms/choice_sources.dart';
import '../../../core/forms/form_spec.dart';
import '../../../core/providers.dart';
import '../../../core/time.dart';
import '../../auth/state/auth_controller.dart';
import '../domain/roster_form.dart';
import 'rosters_screen.dart' show openRosterForm;

typedef Rec = Map<String, dynamic>;

String _iso(int y, int m, int d) => '${y.toString().padLeft(4, '0')}-${m.toString().padLeft(2, '0')}-${d.toString().padLeft(2, '0')}';

/// Month grid of roster entries for one employee — mirrors `apps/web/src/app/app/rosters/calendar/page.tsx`.
/// One cell per day; with `ATTENDANCE.ROSTER_MANAGE`, tapping a cell creates (or edits) that day's entry.
class RosterCalendarScreen extends ConsumerStatefulWidget {
  const RosterCalendarScreen({super.key});

  @override
  ConsumerState<RosterCalendarScreen> createState() => _RosterCalendarScreenState();
}

class _RosterCalendarScreenState extends ConsumerState<RosterCalendarScreen> {
  late int _year;
  late int _month;
  String _employeeId = '';
  bool _loading = false;
  ApiError? _error;
  List<Choice> _employees = const [];
  Map<String, String> _shifts = const {};
  Map<String, Rec> _byDate = const {};

  ApiClient get _client => ref.read(apiClientProvider);

  @override
  void initState() {
    super.initState();
    final zone = ref.read(authControllerProvider).user?.companyTimezone ?? 'Asia/Kolkata';
    final today = businessToday(zone);
    _year = int.parse(today.substring(0, 4));
    _month = int.parse(today.substring(5, 7));
    _employeeId = ref.read(authControllerProvider).user?.employeeId ?? '';
    _init();
  }

  Future<void> _init() async {
    try {
      final c = await loadChoices(_client, const ['employees', 'shifts']);
      if (mounted) {
        setState(() {
          _employees = c['employees'] ?? const [];
          _shifts = {for (final s in c['shifts'] ?? const <Choice>[]) s.value: s.label};
          if (_employeeId.isEmpty && _employees.isNotEmpty) _employeeId = _employees.first.value;
        });
      }
    } catch (_) {}
    _load();
  }

  Future<void> _load() async {
    if (_employeeId.isEmpty) return;
    setState(() {
      _loading = true;
      _error = null;
    });
    final last = DateTime(_year, _month + 1, 0).day;
    try {
      final env = await _client.getList<Rec>(
        '/rosters',
        query: PageQuery(perPage: 100),
        filters: {'employee_id': _employeeId, 'date_from': _iso(_year, _month, 1), 'date_to': _iso(_year, _month, last)},
        parseItem: (d) => d as Rec,
      );
      if (mounted) setState(() => _byDate = {for (final r in env.data) r['roster_date'] as String: r});
    } catch (e) {
      if (mounted) setState(() => _error = e is ApiError ? e : ApiError(status: 0, code: 'UNKNOWN_ERROR', message: 'Something went wrong.'));
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  void _shift(int delta) {
    final d = DateTime(_year, _month + delta);
    setState(() {
      _year = d.year;
      _month = d.month;
    });
    _load();
  }

  Future<void> _tapCell(String iso, Rec? roster) async {
    final canManage = (ref.read(authControllerProvider).user?.permissions ?? const <String>[]).contains(attendanceRosterManage);
    if (!canManage || _employeeId.isEmpty) return;
    final saved = await openRosterForm(context, ref, roster: roster, employeeId: _employeeId, date: iso);
    if (saved && mounted) _load();
  }

  static const _monthNames = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'];

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final daysInMonth = DateTime(_year, _month + 1, 0).day;
    final leadingBlanks = (DateTime(_year, _month, 1).weekday - 1) % 7;
    return Scaffold(
      appBar: AppBar(title: const Text('Roster Calendar')),
      body: Column(children: [
        Padding(
          padding: const EdgeInsets.all(12),
          child: DropdownButtonFormField<String>(
            value: _employeeId.isEmpty ? null : _employeeId,
            isExpanded: true,
            decoration: const InputDecoration(labelText: 'Employee'),
            items: [for (final e in _employees) DropdownMenuItem(value: e.value, child: Text(e.label))],
            onChanged: (v) {
              setState(() => _employeeId = v ?? '');
              _load();
            },
          ),
        ),
        Row(mainAxisAlignment: MainAxisAlignment.spaceBetween, children: [
          IconButton(tooltip: 'Previous month', icon: const Icon(Icons.chevron_left), onPressed: () => _shift(-1)),
          Text('${_monthNames[_month - 1]} $_year', style: Theme.of(context).textTheme.titleMedium),
          IconButton(tooltip: 'Next month', icon: const Icon(Icons.chevron_right), onPressed: () => _shift(1)),
        ]),
        if (_loading) const LinearProgressIndicator(),
        if (_error != null) Padding(padding: const EdgeInsets.all(16), child: Text(_error!.message)),
        Row(children: [for (final d in const ['M', 'T', 'W', 'T', 'F', 'S', 'S']) Expanded(child: Center(child: Text(d, style: TextStyle(fontSize: 12, color: scheme.onSurfaceVariant))))]),
        Expanded(
          child: GridView.builder(
            padding: const EdgeInsets.all(8),
            gridDelegate: const SliverGridDelegateWithFixedCrossAxisCount(crossAxisCount: 7, childAspectRatio: 0.78),
            itemCount: daysInMonth + leadingBlanks,
            itemBuilder: (context, index) {
              if (index < leadingBlanks) return const SizedBox.shrink();
              final day = index - leadingBlanks + 1;
              final iso = _iso(_year, _month, day);
              final roster = _byDate[iso];
              final label = roster == null ? '' : rosterDayLabel(roster, _shifts);
              return InkWell(
                onTap: () => _tapCell(iso, roster),
                child: Container(
                  margin: const EdgeInsets.all(2),
                  padding: const EdgeInsets.all(4),
                  decoration: BoxDecoration(
                    border: Border.all(color: scheme.outlineVariant),
                    borderRadius: BorderRadius.circular(6),
                    color: roster?['status'] == 'PUBLISHED' ? scheme.primaryContainer.withValues(alpha: 0.18) : (roster != null ? Colors.orange.withValues(alpha: 0.12) : null),
                  ),
                  child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                    Text('$day', style: const TextStyle(fontSize: 12, fontWeight: FontWeight.w600)),
                    if (label.isNotEmpty) Expanded(child: Text(label, style: TextStyle(fontSize: 9, color: scheme.onSurfaceVariant), overflow: TextOverflow.fade)),
                  ]),
                ),
              );
            },
          ),
        ),
        Padding(
          padding: const EdgeInsets.fromLTRB(16, 4, 16, 12),
          child: Row(children: [
            Container(width: 12, height: 12, color: scheme.primaryContainer.withValues(alpha: 0.4)),
            const SizedBox(width: 6),
            const Text('Published', style: TextStyle(fontSize: 12)),
            const SizedBox(width: 16),
            Container(width: 12, height: 12, color: Colors.orange.withValues(alpha: 0.3)),
            const SizedBox(width: 6),
            const Text('Draft', style: TextStyle(fontSize: 12)),
          ]),
        ),
      ]),
    );
  }
}
