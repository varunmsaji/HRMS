import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api/api_client.dart';
import '../../../core/api/api_error.dart';
import '../../../core/forms/choice_sources.dart';
import '../../../core/forms/form_spec.dart';
import '../../../core/forms/spec_form_screen.dart';
import '../../../core/providers.dart';
import '../../shell/more_action.dart';
import '../domain/policy_assignment_form.dart';
import '../../../core/widgets/ui.dart';

typedef Rec = Map<String, dynamic>;

/// Policy assignments — mirrors `apps/web/src/app/app/policy-assignments/page.tsx`: which
/// calendar, weekly-off pattern or policy applies to which scope, and from when. There is no edit:
/// assigning a new one for the same kind and scope closes the open one the day before (the open
/// assignment's version is sent as `If-Match`, which the server requires in that case).
class PolicyAssignmentsScreen extends ConsumerStatefulWidget {
  const PolicyAssignmentsScreen({super.key});

  @override
  ConsumerState<PolicyAssignmentsScreen> createState() => _PolicyAssignmentsScreenState();
}

class _PolicyAssignmentsScreenState extends ConsumerState<PolicyAssignmentsScreen> {
  bool _loading = true;
  bool _loadingMore = false;
  ApiError? _error;
  List<Rec> _rows = const [];
  int _page = 1;
  bool _hasMore = false;
  String _kind = '';
  Map<String, Map<String, String>> _names = const {};

  ApiClient get _client => ref.read(apiClientProvider);

  List<String> get _sources => choiceSourcesOf(policyAssignmentSpec)..add('leave_types');

  @override
  void initState() {
    super.initState();
    _loadNames();
    _load();
  }

  Future<void> _loadNames() async {
    try {
      final c = await loadChoices(_client, _sources);
      if (mounted) setState(() => _names = {for (final e in c.entries) e.key: {for (final x in e.value) x.value: x.label}});
    } catch (_) {}
  }

  Future<({List<Rec> rows, bool more})> _fetch(int page) async {
    final env = await _client.getList<Rec>('/policy-assignments', query: PageQuery(page: page), filters: {if (_kind.isNotEmpty) 'policy_kind': _kind}, parseItem: (d) => d as Rec);
    return (rows: env.data, more: env.pagination?.hasNext ?? false);
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
          _hasMore = r.more;
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
          _hasMore = r.more;
        });
      }
    } catch (_) {
    } finally {
      if (mounted) setState(() => _loadingMore = false);
    }
  }

  Future<void> _create() async {
    final saved = await openSpecForm(
      context,
      title: 'New policy assignment',
      spec: policyAssignmentSpec,
      loadChoices: () => loadChoices(_client, _sources),
      onSubmit: (payload, _) async {
        // Replacing: an open assignment for the same kind and scope has to be closed first.
        Rec? open;
        for (final r in _rows) {
          if (r['effective_to'] == null && r['policy_kind'] == payload['policy_kind'] && r['scope_type'] == payload['scope_type'] && r['scope_id'] == payload['scope_id']) open = r;
        }
        await _client.post<Object?>('/policy-assignments', body: payload, ifMatch: open?['version']?.toString(), parse: (_) => null);
      },
    );
    if (saved && mounted) {
      ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Assignment created.')));
      _load();
    }
  }

  String _name(String source, String? id) => id == null ? '' : (_names[source]?[id] ?? id);

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Policy Assignments'), actions: const [MoreAction()]),
      floatingActionButton: FloatingActionButton.extended(onPressed: _create, icon: const Icon(Icons.add), label: const Text('New assignment')),
      body: Column(children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(16, 12, 16, 0),
          child: DropdownButtonFormField<String>(
            value: _kind,
            isExpanded: true,
            decoration: const InputDecoration(labelText: 'Filter by policy kind'),
            items: [const DropdownMenuItem(value: '', child: Text('All kinds')), for (final e in policyKindLabels.entries) DropdownMenuItem(value: e.key, child: Text(e.value))],
            onChanged: (v) {
              setState(() => _kind = v ?? '');
              _load();
            },
          ),
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
                          if (_rows.isEmpty) const SizedBox(height: 300, child: StateMessage(icon: Icons.rule_folder_outlined, title: 'No policy assignments yet')),
                          for (final a in _rows)
                            Padding(
                              padding: const EdgeInsets.fromLTRB(16, 0, 16, 10),
                              child: ListRowCard(
                                leading: const IconBadge(icon: Icons.rule_folder_outlined),
                                title: '${policyKindLabels[a['policy_kind']] ?? a['policy_kind']} → ${scopeTypeLabels[a['scope_type']] ?? a['scope_type']}${a['scope_id'] != null ? ': ${_name(scopeSources[a['scope_type']] ?? '', a['scope_id'] as String?)}' : ''}',
                                subtitle: [
                                  _name(policySources[a['policy_kind']] ?? '', a['policy_id'] as String?),
                                  if (a['leave_type_id'] != null) _name('leave_types', a['leave_type_id'] as String?),
                                  '${a['effective_from']} – ${a['effective_to'] ?? 'open'}',
                                  if (a['reason'] != null) '${a['reason']}',
                                ].join(' · '),
                                showChevron: false,
                                trailing: StatusChip(label: a['effective_to'] == null ? 'Current' : 'Ended ${a['effective_to']}', tone: a['effective_to'] == null ? Tone.success : Tone.neutral),
                              ),
                            ),
                          if (_hasMore) Center(child: TextButton(onPressed: _loadingMore ? null : _more, child: Text(_loadingMore ? 'Loading…' : 'Load more'))),
                        ],
                      ),
                    ),
        ),
      ]),
    );
  }
}
