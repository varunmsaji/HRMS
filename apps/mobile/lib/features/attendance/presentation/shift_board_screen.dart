import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api/api_error.dart';
import '../../../core/auth/permissions.dart';
import '../../../core/time.dart';
import '../../../core/widgets/ui.dart';
import '../../auth/state/auth_controller.dart';
import '../../profile/data/employee_repository.dart';
import '../data/roster_repository.dart';
import '../domain/roster_views.dart';

/// Who is on which shift for one day — mirrors `apps/web/src/app/app/rosters/board/page.tsx`. Web
/// drags cards between columns; here the columns are stacked and tapping a person offers where to
/// move them. A move writes the roster entry and publishes it, so it takes effect immediately.
class ShiftBoardScreen extends ConsumerStatefulWidget {
  const ShiftBoardScreen({super.key, this.now});

  /// The reads the board needs: rosters (ATTENDANCE.VIEW), employees (EMPLOYEE.VIEW_ALL) and the
  /// shift list its columns come from (`GET /shifts` checks ORG.SHIFT.MANAGE).
  static const requiredPermissions = [attendanceView, employeeViewAll, orgShiftManage];

  /// Overrides the clock (tests). Null = now.
  final DateTime? now;

  @override
  ConsumerState<ShiftBoardScreen> createState() => _ShiftBoardScreenState();
}

class _ShiftBoardScreenState extends ConsumerState<ShiftBoardScreen> {
  late String _date;
  List<RosterShift> _shifts = const [];
  List<Employee>? _employees;
  bool _moreEmployees = false;
  Map<String, RosterEntry> _entries = const {};
  bool _loading = true;
  ApiError? _error;
  String _search = '';
  String? _savingId;
  bool _copying = false;
  ({String employeeId, String name, String from})? _lastMove;
  int _request = 0;

  RosterRepository get _repo => ref.read(rosterRepositoryProvider);
  bool get _canManage => (ref.read(authControllerProvider).user?.permissions ?? const []).contains(attendanceRosterManage);
  bool get _allowed => ShiftBoardScreen.requiredPermissions.every((ref.read(authControllerProvider).user?.permissions ?? const <String>[]).contains);

  @override
  void initState() {
    super.initState();
    _date = businessToday(ref.read(authControllerProvider).user?.companyTimezone ?? 'Asia/Kolkata', now: widget.now);
    if (_allowed) _load();
  }

  String _describe(Object e) => e is ApiError ? (e.code == 'STALE_RESOURCE' ? 'This entry was changed by someone else. Try again.' : (e.status == 403 ? "You don't have permission to do that." : e.message)) : 'Something went wrong.';

  void _toast(String m) => ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(m)));

  /// A slower answer for a day the user has left never overwrites the current one.
  Future<void> _load() async {
    final mine = ++_request;
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final results = await Future.wait([_repo.listShifts(), _repo.listBoardEmployees(), _repo.listEntries(_date, _date)]);
      if (!mounted || mine != _request) return;
      final people = results[1] as ({List<Employee> rows, bool more});
      final range = results[2] as ({List<RosterEntry> entries, int total});
      setState(() {
        _shifts = results[0] as List<RosterShift>;
        _employees = people.rows;
        _moreEmployees = people.more;
        _entries = {for (final r in range.entries) r.employeeId: r};
      });
    } catch (e) {
      if (mounted && mine == _request) setState(() => _error = e is ApiError ? e : ApiError(status: 0, code: 'UNKNOWN_ERROR', message: 'Something went wrong.'));
    } finally {
      if (mounted && mine == _request) setState(() => _loading = false);
    }
  }

  void _goTo(String date) {
    setState(() {
      _date = date;
      _lastMove = null;
    });
    _load();
  }

  Future<void> _pickDate() async {
    final current = DateTime.parse(_date);
    final picked = await showDatePicker(context: context, initialDate: current, firstDate: DateTime(current.year - 5), lastDate: DateTime(current.year + 5));
    if (picked == null || !mounted) return;
    _goTo('${picked.year.toString().padLeft(4, '0')}-${picked.month.toString().padLeft(2, '0')}-${picked.day.toString().padLeft(2, '0')}');
  }

  /// No times under a shift: those on `GET /shifts` are frozen legacy values, so they can be wrong.
  List<({String key, String title, String? sub})> get _columns => [
        (key: unassignedColumn, title: 'Unassigned', sub: 'Default shift applies'),
        for (final s in _shifts) (key: s.id, title: s.name, sub: null),
        (key: weekOffColumn, title: 'Week off', sub: 'Not working'),
      ];

  String _name(Employee e) => e.fullName.isEmpty ? e.employeeCode : e.fullName;

  Future<void> _move(Employee e, String target, {bool recordUndo = true}) async {
    final existing = _entries[e.id];
    final from = boardColumnOf(existing);
    if (from == target) return;
    setState(() => _savingId = e.id);
    try {
      final saved = await _repo.moveEmployee(employeeId: e.id, date: _date, existing: existing, target: target);
      if (!mounted) return;
      setState(() {
        _entries = {..._entries}..remove(e.id);
        if (saved != null) _entries[e.id] = saved;
        _lastMove = recordUndo ? (employeeId: e.id, name: _name(e), from: from) : null;
      });
    } catch (err) {
      if (!mounted) return;
      _toast('Could not change shift: ${_describe(err)}');
      _load();
    } finally {
      if (mounted) setState(() => _savingId = null);
    }
  }

  Future<void> _offerMove(Employee e) async {
    final current = boardColumnOf(_entries[e.id]);
    final target = await showModalBottomSheet<String>(
      context: context,
      isScrollControlled: true,
      showDragHandle: true,
      builder: (ctx) => SafeArea(
        child: ConstrainedBox(
          constraints: BoxConstraints(maxHeight: MediaQuery.of(ctx).size.height * 0.7),
          child: ListView(shrinkWrap: true, children: [
            Padding(padding: const EdgeInsets.fromLTRB(20, 0, 20, 8), child: Text('Move ${_name(e)} to', style: Theme.of(ctx).textTheme.titleMedium)),
            for (final c in _columns)
              ListTile(
                enabled: c.key != current,
                title: Text(c.title),
                subtitle: c.sub == null ? null : Text(c.sub!),
                trailing: c.key == current ? const Text('Current') : null,
                onTap: () => Navigator.of(ctx).pop(c.key),
              ),
          ]),
        ),
      ),
    );
    if (target != null && mounted) await _move(e, target);
  }

  Future<void> _undo() async {
    final last = _lastMove;
    if (last == null) return;
    final employee = (_employees ?? const <Employee>[]).where((e) => e.id == last.employeeId).firstOrNull;
    if (employee == null) return;
    await _move(employee, last.from, recordUndo: false);
    if (mounted) setState(() => _lastMove = null);
  }

  Future<void> _copyToNextDay() async {
    final next = addDaysIso(_date, 1);
    final count = _entries.length;
    final yes = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Copy to next day?'),
        content: Text('Copy $count roster ${count == 1 ? 'entry' : 'entries'} from ${formatShortDate(_date)} to ${formatShortDate(next)}? They take effect immediately. Employees who already have an entry that day are skipped.'),
        actions: [
          TextButton(onPressed: () => Navigator.of(ctx).pop(false), child: const Text('Cancel')),
          FilledButton(onPressed: () => Navigator.of(ctx).pop(true), child: const Text('Copy')),
        ],
      ),
    );
    if (yes != true || !mounted) return;
    setState(() => _copying = true);
    try {
      final copied = await _repo.copyEntries(_entries.values.toList(), next);
      if (mounted) _toast('Copied $copied to ${formatShortDate(next)}${copied < count ? ' (${count - copied} skipped, already rostered)' : ''}.');
    } catch (e) {
      if (mounted) _toast('Copy stopped part-way: ${_describe(e)}');
    } finally {
      if (mounted) setState(() => _copying = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    if (!_allowed) {
      return Scaffold(
        appBar: AppBar(title: const Text('Shift board')),
        body: const StateMessage(icon: Icons.lock_outline_rounded, title: 'No access', message: 'The shift board needs access to rosters, the employee directory and the shift list.'),
      );
    }
    final canManage = _canManage;
    final scheme = Theme.of(context).colorScheme;
    final muted = TextStyle(fontSize: 12, color: scheme.onSurfaceVariant);
    final query = _search.trim().toLowerCase();
    final columns = _columns;
    final known = columns.map((c) => c.key).toSet();
    final byColumn = {for (final c in columns) c.key: <Employee>[]};
    for (final e in _employees ?? const <Employee>[]) {
      if (query.isNotEmpty && !'${e.nameSearchText} ${e.employeeCode}'.toLowerCase().contains(query)) continue;
      final key = boardColumnOf(_entries[e.id]);
      byColumn[known.contains(key) ? key : unassignedColumn]!.add(e);
    }
    final last = _lastMove;
    return Scaffold(
      appBar: AppBar(title: const Text('Shift board')),
      body: RefreshIndicator(
        onRefresh: _load,
        child: ListView(padding: const EdgeInsets.fromLTRB(16, 12, 16, 32), children: [
          Row(children: [
            IconButton(tooltip: 'Previous day', onPressed: () => _goTo(addDaysIso(_date, -1)), icon: const Icon(Icons.chevron_left)),
            Expanded(child: OutlinedButton(onPressed: _pickDate, child: Text(formatShortDate(_date)))),
            IconButton(tooltip: 'Next day', onPressed: () => _goTo(addDaysIso(_date, 1)), icon: const Icon(Icons.chevron_right)),
          ]),
          const SizedBox(height: 8),
          AppSearchField(hint: 'Search name or code', onChanged: (v) => setState(() => _search = v)),
          if (canManage) ...[
            const SizedBox(height: 8),
            Wrap(spacing: 8, runSpacing: 4, children: [
              OutlinedButton(onPressed: last == null || _savingId != null ? null : _undo, child: Text(last == null ? 'Undo' : 'Undo: ${last.name}')),
              OutlinedButton(onPressed: _copying || _entries.isEmpty ? null : _copyToNextDay, child: Text(_copying ? 'Copying…' : 'Copy to next day')),
            ]),
            const SizedBox(height: 4),
            Text('Tap someone to move them. A move takes effect immediately.', style: muted),
          ],
          const SizedBox(height: 12),
          if (_error != null)
            StateMessage(icon: Icons.error_outline_rounded, tone: Tone.danger, title: "Couldn't load the board", message: _error!.status == 403 ? "You don't have permission to see this." : _error!.message, actionLabel: 'Retry', onAction: _load)
          else if (_loading && _employees == null)
            const Padding(padding: EdgeInsets.all(32), child: Center(child: CircularProgressIndicator(strokeWidth: 2.5)))
          else ...[
            if (_loading) const LinearProgressIndicator(),
            for (final c in columns) ...[
              Padding(
                padding: const EdgeInsets.only(top: 8, bottom: 6),
                child: Row(children: [
                  Expanded(
                    child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                      Text(c.title, style: const TextStyle(fontWeight: FontWeight.w700)),
                      if (c.sub != null) Text(c.sub!, style: muted),
                    ]),
                  ),
                  Text('${byColumn[c.key]!.length}', style: const TextStyle(fontWeight: FontWeight.w700)),
                ]),
              ),
              if (byColumn[c.key]!.isEmpty)
                Padding(padding: const EdgeInsets.only(bottom: 8), child: Text('No one', style: muted))
              else
                for (final e in byColumn[c.key]!)
                  Padding(
                    padding: const EdgeInsets.only(bottom: 6),
                    child: ListRowCard(
                      title: _name(e),
                      subtitle: e.fullName.isEmpty ? null : e.employeeCode,
                      trailing: _savingId == e.id
                          ? const SizedBox(width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2))
                          : (_entries[e.id]?.isDraft ?? false)
                              ? const StatusChip(label: 'Draft', tone: Tone.warning)
                              : null,
                      onTap: canManage && _savingId == null ? () => _offerMove(e) : null,
                    ),
                  ),
            ],
            if (_moreEmployees) Padding(padding: const EdgeInsets.only(top: 8), child: Text('Showing the first 1,000 employees. Use the Workforce roster for the rest.', style: muted)),
          ],
        ]),
      ),
    );
  }
}
