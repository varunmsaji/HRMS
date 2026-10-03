import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api/api_error.dart';
import '../../../core/auth/permissions.dart';
import '../../../core/forms/choice_sources.dart';
import '../../../core/forms/form_spec.dart';
import '../../../core/forms/spec_form_screen.dart';
import '../../../core/providers.dart';
import '../../auth/state/auth_controller.dart';
import '../../shell/more_action.dart';
import '../data/leave_repository.dart';
import '../domain/leave_application_form.dart';
import 'leave_application_detail_screen.dart';

/// Leave applications — mirrors `apps/web/src/app/app/leave-applications/page.tsx`. "Mine" and
/// "Team" are two filters over the same permission-scoped read: the server only returns what the
/// caller may see. Filter by date range, status and (for the team) employee.
class LeaveApplicationsScreen extends ConsumerStatefulWidget {
  const LeaveApplicationsScreen({super.key});

  @override
  ConsumerState<LeaveApplicationsScreen> createState() => _LeaveApplicationsScreenState();
}

class _LeaveApplicationsScreenState extends ConsumerState<LeaveApplicationsScreen> {
  late bool _team;
  String _status = '';
  String _employee = '';
  String _from = '';
  String _to = '';
  bool _loading = true;
  bool _loadingMore = false;
  ApiError? _error;
  List<LeaveApplication> _rows = const [];
  int _page = 1;
  bool _hasMore = false;
  List<Choice> _employees = const [];
  Map<String, String> _typeNames = const {};

  List<String> get _permissions => ref.read(authControllerProvider).user?.permissions ?? const <String>[];

  @override
  void initState() {
    super.initState();
    _team = _permissions.contains(leaveApplicationApprove);
    _loadLookups();
    _load();
  }

  Future<void> _loadLookups() async {
    try {
      final c = await loadChoices(ref.read(apiClientProvider), [if (_permissions.contains(leaveApplicationApprove) || _permissions.contains(leaveApplicationSubmitOnBehalf)) 'employees', 'leave_types']);
      if (mounted) {
        setState(() {
          _employees = c['employees'] ?? const [];
          _typeNames = {for (final t in c['leave_types'] ?? const <Choice>[]) t.value: t.label};
        });
      }
    } catch (_) {}
  }

  Future<ListEnvelopeLike> _fetch(int page) async {
    final myEmployeeId = ref.read(authControllerProvider).user?.employeeId;
    final env = await ref.read(leaveRepositoryProvider).listLeaveApplicationsPage(
          employeeId: _team ? (_employee.isEmpty ? null : _employee) : myEmployeeId,
          dateFrom: _from.isEmpty ? null : _from,
          dateTo: _to.isEmpty ? null : _to,
          status: _status.isEmpty ? null : _status,
          page: page,
        );
    return (rows: env.data, hasNext: env.pagination?.hasNext ?? false);
  }

  Future<void> _load() async {
    setState(() {
      _loading = true;
      _error = null;
      _page = 1;
    });
    try {
      final r = await _fetch(1);
      if (mounted) {
        setState(() {
          _rows = r.rows;
          _hasMore = r.hasNext;
        });
      }
    } catch (e) {
      if (mounted) setState(() => _error = e is ApiError ? e : ApiError(status: 0, code: 'UNKNOWN_ERROR', message: 'Something went wrong.'));
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _more() async {
    setState(() => _loadingMore = true);
    try {
      final r = await _fetch(_page + 1);
      if (mounted) {
        setState(() {
          _rows = [..._rows, ...r.rows];
          _page += 1;
          _hasMore = r.hasNext;
        });
      }
    } catch (_) {
    } finally {
      if (mounted) setState(() => _loadingMore = false);
    }
  }

  Future<void> _apply() async {
    final onBehalf = _team;
    final client = ref.read(apiClientProvider);
    final saved = await openSpecForm(
      context,
      title: onBehalf ? 'Apply on behalf' : 'Apply for leave',
      spec: leaveApplicationSpec(onBehalf: onBehalf),
      loadChoices: () => loadChoices(client, [if (onBehalf) 'employees', 'leave_types']),
      onSubmit: (payload, _) async => ref.read(leaveRepositoryProvider).submitLeaveApplication(payload),
    );
    if (saved && mounted) {
      ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Leave application submitted.')));
      _load();
    }
  }

  Future<void> _pick(bool from) async {
    final current = DateTime.tryParse(from ? _from : _to) ?? DateTime.now();
    final picked = await showDatePicker(context: context, initialDate: current, firstDate: DateTime(2020), lastDate: DateTime(2100));
    if (picked == null) return;
    final iso = '${picked.year.toString().padLeft(4, '0')}-${picked.month.toString().padLeft(2, '0')}-${picked.day.toString().padLeft(2, '0')}';
    setState(() => from ? _from = iso : _to = iso);
    _load();
  }

  String _title(LeaveApplication a) {
    final type = _typeNames[a.leaveTypeId] ?? 'Leave';
    final who = _team ? _employeeName(a.employeeId) : '';
    return who.isEmpty ? type : '$who · $type';
  }

  String _employeeName(String id) {
    for (final c in _employees) {
      if (c.value == id) return c.label;
    }
    return '';
  }

  @override
  Widget build(BuildContext context) {
    final permissions = ref.watch(authControllerProvider).user?.permissions ?? const <String>[];
    final canApprove = permissions.contains(leaveApplicationApprove);
    final canCreate = _team ? permissions.contains(leaveApplicationSubmitOnBehalf) : permissions.contains(leaveApplicationSubmit);
    final scheme = Theme.of(context).colorScheme;
    return Scaffold(
      appBar: AppBar(title: const Text('Leave'), automaticallyImplyLeading: false, actions: const [MoreAction()]),
      floatingActionButton: canCreate ? FloatingActionButton.extended(onPressed: _apply, icon: const Icon(Icons.add), label: Text(_team ? 'Apply on behalf' : 'Apply for leave')) : null,
      body: Column(children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(16, 12, 16, 0),
          child: Column(children: [
            if (canApprove || permissions.contains(leaveApplicationSubmitOnBehalf))
              SegmentedButton<bool>(
                segments: const [ButtonSegment(value: false, label: Text('Mine')), ButtonSegment(value: true, label: Text('Team'))],
                selected: {_team},
                onSelectionChanged: (s) {
                  setState(() => _team = s.first);
                  _load();
                },
              ),
            const SizedBox(height: 8),
            Row(children: [
              Expanded(child: OutlinedButton(onPressed: () => _pick(true), child: Text(_from.isEmpty ? 'From' : _from))),
              const SizedBox(width: 8),
              Expanded(child: OutlinedButton(onPressed: () => _pick(false), child: Text(_to.isEmpty ? 'To' : _to))),
              if (_from.isNotEmpty || _to.isNotEmpty) IconButton(tooltip: 'Clear dates', icon: const Icon(Icons.clear), onPressed: () {
                setState(() {
                  _from = '';
                  _to = '';
                });
                _load();
              }),
            ]),
            const SizedBox(height: 8),
            DropdownButtonFormField<String>(
              value: _status,
              isExpanded: true,
              decoration: const InputDecoration(labelText: 'Status', contentPadding: EdgeInsets.symmetric(horizontal: 12, vertical: 8)),
              items: [const DropdownMenuItem(value: '', child: Text('All statuses')), for (final s in leaveApplicationStatuses) DropdownMenuItem(value: s, child: Text(leaveApplicationStatusLabels[s]!))],
              onChanged: (v) {
                setState(() => _status = v ?? '');
                _load();
              },
            ),
            if (_team && _employees.isNotEmpty) ...[
              const SizedBox(height: 8),
              DropdownButtonFormField<String>(
                value: _employee,
                isExpanded: true,
                decoration: const InputDecoration(labelText: 'Employee', contentPadding: EdgeInsets.symmetric(horizontal: 12, vertical: 8)),
                items: [const DropdownMenuItem(value: '', child: Text('All employees')), for (final e in _employees) DropdownMenuItem(value: e.value, child: Text(e.label))],
                onChanged: (v) {
                  setState(() => _employee = v ?? '');
                  _load();
                },
              ),
            ],
          ]),
        ),
        Expanded(
          child: _loading
              ? const Center(child: CircularProgressIndicator())
              : _error != null
                  ? Center(
                      child: Padding(
                        padding: const EdgeInsets.all(24),
                        child: Column(mainAxisSize: MainAxisSize.min, children: [
                          Text(_error!.message, textAlign: TextAlign.center),
                          const SizedBox(height: 16),
                          FilledButton(onPressed: _load, child: const Text('Retry')),
                        ]),
                      ),
                    )
                  : RefreshIndicator(
                      onRefresh: _load,
                      child: ListView(
                        padding: const EdgeInsets.only(top: 8, bottom: 88),
                        children: [
                          if (_rows.isEmpty) const Padding(padding: EdgeInsets.all(32), child: Center(child: Text('No leave applications match these filters.'))),
                          for (final a in _rows)
                            ListTile(
                              title: Text(_title(a)),
                              subtitle: Text('${a.startDate} → ${a.endDate}${a.totalDays != null ? ' · ${a.totalDays} day(s)' : ''}'),
                              trailing: _StatusChip(status: a.status),
                              onTap: () async {
                                await Navigator.of(context).push(MaterialPageRoute(builder: (_) => LeaveApplicationDetailScreen(applicationId: a.id, initial: a)));
                                _load();
                              },
                            ),
                          if (_hasMore) Center(child: TextButton(onPressed: _loadingMore ? null : _more, child: Text(_loadingMore ? 'Loading…' : 'Load more'))),
                        ],
                      ),
                    ),
        ),
      ]),
      backgroundColor: scheme.surface,
    );
  }
}

typedef ListEnvelopeLike = ({List<LeaveApplication> rows, bool hasNext});

class _StatusChip extends StatelessWidget {
  const _StatusChip({required this.status});
  final String status;

  @override
  Widget build(BuildContext context) {
    final color = switch (status) {
      'APPROVED' => Colors.green,
      'REJECTED' => Colors.red,
      'CANCELLED' => Theme.of(context).colorScheme.onSurfaceVariant,
      _ => Colors.orange,
    };
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
      decoration: BoxDecoration(color: color.withValues(alpha: 0.15), borderRadius: BorderRadius.circular(4)),
      child: Text(leaveApplicationStatusLabels[status] ?? status, style: TextStyle(color: color, fontSize: 11, fontWeight: FontWeight.w600)),
    );
  }
}

/// Shared with the detail screen.
class LeaveStatusChip extends StatelessWidget {
  const LeaveStatusChip({super.key, required this.status});
  final String status;

  @override
  Widget build(BuildContext context) => _StatusChip(status: status);
}
