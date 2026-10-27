import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../core/api/api_client.dart';
import '../../../core/api/api_error.dart';
import '../../../core/auth/permissions.dart';
import '../../../core/forms/choice_sources.dart';
import '../../../core/forms/form_spec.dart';
import '../../../core/forms/spec_form_screen.dart';
import '../../../core/providers.dart';
import '../../../core/time.dart';
import '../../auth/state/auth_controller.dart';
import '../../shell/more_action.dart';
import '../domain/roster_form.dart';
import '../../../core/widgets/ui.dart';

typedef Rec = Map<String, dynamic>;

/// Opens the roster entry form to create (or, with [roster], edit) an entry. [employeeId] / [date]
/// pre-fill and lock the employee/date for a "create for this cell" flow (the roster calendar).
Future<bool> openRosterForm(BuildContext context, WidgetRef ref, {Rec? roster, String? employeeId, String? date}) {
  final client = ref.read(apiClientProvider);
  final editing = roster != null;
  final locked = employeeId != null || editing;
  return openSpecForm(
    context,
    title: editing ? 'Edit roster entry' : 'New roster entry',
    spec: rosterSpec(employeeLocked: locked),
    initial: editing ? rosterToFormWire(roster) : null,
    defaults: {if (date != null) 'roster_date': date},
    loadChoices: () => loadChoices(client, [if (!locked) 'employees', 'shifts']),
    onSubmit: (payload, changed) async {
      if (editing) {
        await client.patch<Object?>('/rosters/${roster['id']}', body: rosterPatchBody(payload), ifMatch: roster['version'].toString(), parse: (_) => null);
      } else {
        await client.post<Object?>('/rosters', body: rosterCreateBody(payload, employeeId: employeeId), parse: (_) => null);
      }
    },
  );
}

/// Shift roster entries — mirrors `apps/web/src/app/app/rosters/page.tsx`: filter by date range,
/// employee and status; add, edit, publish (DRAFT → PUBLISHED) and remove entries.
class RostersScreen extends ConsumerStatefulWidget {
  const RostersScreen({super.key});

  @override
  ConsumerState<RostersScreen> createState() => _RostersScreenState();
}

class _RostersScreenState extends ConsumerState<RostersScreen> {
  late String _from;
  late String _to;
  String _employee = '';
  String _status = '';
  bool _loading = true;
  ApiError? _error;
  List<Rec> _rows = const [];
  List<Choice> _employees = const [];
  Map<String, String> _shifts = const {};

  ApiClient get _client => ref.read(apiClientProvider);

  @override
  void initState() {
    super.initState();
    final zone = ref.read(authControllerProvider).user?.companyTimezone ?? 'Asia/Kolkata';
    _from = businessToday(zone);
    _to = businessDayOffset(zone, 13);
    _loadLookups();
    _load();
  }

  Future<void> _loadLookups() async {
    try {
      final c = await loadChoices(_client, const ['employees', 'shifts']);
      if (mounted) {
        setState(() {
          _employees = c['employees'] ?? const [];
          _shifts = {for (final s in c['shifts'] ?? const <Choice>[]) s.value: s.label};
        });
      }
    } catch (_) {}
  }

  Future<void> _load() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final env = await _client.getList<Rec>(
        '/rosters',
        query: PageQuery(perPage: 100),
        filters: {'date_from': _from, 'date_to': _to, if (_employee.isNotEmpty) 'employee_id': _employee, if (_status.isNotEmpty) 'status': _status},
        parseItem: (d) => d as Rec,
      );
      final rows = [...env.data]..sort((a, b) => (a['roster_date'] as String).compareTo(b['roster_date'] as String));
      if (mounted) setState(() => _rows = rows);
    } catch (e) {
      if (mounted) setState(() => _error = e is ApiError ? e : ApiError(status: 0, code: 'UNKNOWN_ERROR', message: 'Something went wrong.'));
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  void _toast(String m) => ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(m)));

  String _employeeName(String id) {
    for (final c in _employees) {
      if (c.value == id) return c.label;
    }
    return 'Employee';
  }

  Future<void> _pick(bool from) async {
    final picked = await showDatePicker(context: context, initialDate: DateTime.tryParse(from ? _from : _to) ?? DateTime.now(), firstDate: DateTime(2020), lastDate: DateTime(2100));
    if (picked == null) return;
    final iso = '${picked.year.toString().padLeft(4, '0')}-${picked.month.toString().padLeft(2, '0')}-${picked.day.toString().padLeft(2, '0')}';
    setState(() => from ? _from = iso : _to = iso);
    _load();
  }

  Future<void> _publish(Rec r) async {
    try {
      await _client.post<Object?>('/rosters/${r['id']}/publish', body: const {}, ifMatch: r['version'].toString(), parse: (_) => null);
      _toast('Roster entry published.');
    } catch (e) {
      _toast(e is ApiError ? e.message : 'Something went wrong.');
    }
    _load();
  }

  Future<void> _delete(Rec r) async {
    final yes = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Remove this roster entry?'),
        content: Text('${_employeeName(r['employee_id'] as String)} · ${r['roster_date']}'),
        actions: [
          TextButton(onPressed: () => Navigator.of(ctx).pop(false), child: const Text('Cancel')),
          FilledButton(style: FilledButton.styleFrom(backgroundColor: Theme.of(ctx).colorScheme.error), onPressed: () => Navigator.of(ctx).pop(true), child: const Text('Remove')),
        ],
      ),
    );
    if (yes != true) return;
    try {
      await _client.delete<Object?>('/rosters/${r['id']}', ifMatch: r['version'].toString(), parse: (_) => null);
      _toast('Roster entry removed.');
    } catch (e) {
      _toast(e is ApiError ? e.message : 'Something went wrong.');
    }
    _load();
  }

  @override
  Widget build(BuildContext context) {
    final canManage = (ref.watch(authControllerProvider).user?.permissions ?? const <String>[]).contains(attendanceRosterManage);
    return Scaffold(
      appBar: AppBar(
        title: const Text('Shift Rosters'),
        actions: [IconButton(tooltip: 'Roster calendar', icon: const Icon(Icons.calendar_view_month_outlined), onPressed: () => context.push('/app/roster-calendar')), const MoreAction()],
      ),
      floatingActionButton: canManage
          ? FloatingActionButton.extended(
              onPressed: () async {
                if (await openRosterForm(context, ref) && mounted) _load();
              },
              icon: const Icon(Icons.add),
              label: const Text('Add roster entry'),
            )
          : null,
      body: Column(children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(16, 12, 16, 0),
          child: Column(children: [
            Row(children: [
              Expanded(child: OutlinedButton(onPressed: () => _pick(true), child: Text('From $_from'))),
              const SizedBox(width: 8),
              Expanded(child: OutlinedButton(onPressed: () => _pick(false), child: Text('To $_to'))),
            ]),
            const SizedBox(height: 8),
            Row(children: [
              Expanded(
                child: DropdownButtonFormField<String>(
                  value: _employee,
                  isExpanded: true,
                  decoration: const InputDecoration(labelText: 'Employee', contentPadding: EdgeInsets.symmetric(horizontal: 12, vertical: 8)),
                  items: [const DropdownMenuItem(value: '', child: Text('All')), for (final e in _employees) DropdownMenuItem(value: e.value, child: Text(e.label))],
                  onChanged: (v) {
                    setState(() => _employee = v ?? '');
                    _load();
                  },
                ),
              ),
              const SizedBox(width: 8),
              Expanded(
                child: DropdownButtonFormField<String>(
                  value: _status,
                  isExpanded: true,
                  decoration: const InputDecoration(labelText: 'Status', contentPadding: EdgeInsets.symmetric(horizontal: 12, vertical: 8)),
                  items: const [DropdownMenuItem(value: '', child: Text('All')), DropdownMenuItem(value: 'DRAFT', child: Text('Draft')), DropdownMenuItem(value: 'PUBLISHED', child: Text('Published'))],
                  onChanged: (v) {
                    setState(() => _status = v ?? '');
                    _load();
                  },
                ),
              ),
            ]),
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
                        padding: const EdgeInsets.only(top: 8, bottom: 88),
                        children: [
                          if (_rows.isEmpty) const SizedBox(height: 320, child: StateMessage(icon: Icons.calendar_month_outlined, title: 'No roster entries', message: 'No roster entries in this range.')),
                          for (final r in _rows)
                            Padding(
                              padding: const EdgeInsets.fromLTRB(16, 0, 16, 10),
                              child: ListRowCard(
                                leading: InitialsAvatar(name: _employeeName(r['employee_id'] as String)),
                                title: '${_employeeName(r['employee_id'] as String)} · ${r['roster_date']}',
                                subtitle: rosterDayLabel(r, _shifts),
                                showChevron: false,
                                trailing: Row(mainAxisSize: MainAxisSize.min, children: [
                                  StatusChip(label: r['status'] == 'PUBLISHED' ? 'Published' : 'Draft', tone: r['status'] == 'PUBLISHED' ? Tone.success : Tone.neutral),
                                  if (canManage)
                                    PopupMenuButton<String>(
                                      onSelected: (v) async {
                                        if (v == 'edit') {
                                          if (await openRosterForm(context, ref, roster: r) && mounted) _load();
                                        } else if (v == 'publish') {
                                          _publish(r);
                                        } else {
                                          _delete(r);
                                        }
                                      },
                                      itemBuilder: (_) => [
                                        if (r['status'] == 'DRAFT') const PopupMenuItem(value: 'publish', child: Text('Publish')),
                                        const PopupMenuItem(value: 'edit', child: Text('Edit')),
                                        const PopupMenuItem(value: 'delete', child: Text('Remove')),
                                      ],
                                    ),
                                ]),
                              ),
                            ),
                        ],
                      ),
                    ),
        ),
      ]),
    );
  }
}
