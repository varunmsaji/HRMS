import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api/api_client.dart';
import '../../../core/api/api_error.dart';
import '../../../core/providers.dart';
import '../../../core/time.dart';
import '../../../core/widgets/ui.dart';
import '../../auth/state/auth_controller.dart';
import '../../employees/domain/employee_directory.dart' show employeeDisplayName;
import '../../employees/presentation/employee_picker_sheet.dart';
import '../../organisation/presentation/change_impact_screen.dart';
import '../domain/policy_assignment_form.dart';
import '../domain/policy_coverage.dart';

String _iso(DateTime d) => '${d.year.toString().padLeft(4, '0')}-${d.month.toString().padLeft(2, '0')}-${d.day.toString().padLeft(2, '0')}';

/// Ends an open group-level assignment: from the day after the chosen last day, the group follows
/// the next wider assignment again. The server needs the open row's version as `If-Match`.
/// Resolves true once ended. Shared by "Set policies" and the assignments list.
Future<bool> endPolicyAssignment(BuildContext context, ApiClient client, {required String id, required Object? version, required String effectiveFrom}) async {
  final start = DateTime.tryParse(effectiveFrom) ?? DateTime.now();
  final now = DateTime.now();
  final picked = await showDatePicker(
    context: context,
    helpText: 'Last day of this assignment',
    initialDate: now.isAfter(start) ? now : start,
    firstDate: start,
    lastDate: DateTime(2100),
  );
  if (picked == null || !context.mounted) return false;
  final confirmed = await showDialog<bool>(
    context: context,
    builder: (ctx) => AlertDialog(
      title: const Text('End this assignment?'),
      content: Text('After ${_iso(picked)}, this group follows the next wider assignment, ending at the company-wide one.'),
      actions: [
        TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('Cancel')),
        FilledButton(onPressed: () => Navigator.pop(ctx, true), child: const Text('End assignment')),
      ],
    ),
  );
  if (confirmed != true || !context.mounted) return false;
  try {
    await client.post<Object?>('/policy-assignments/$id/end', body: {'effective_to': _iso(picked)}, ifMatch: version?.toString(), parse: (_) => null);
    if (context.mounted) ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Assignment ended.')));
    return true;
  } catch (e) {
    if (context.mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(e is ApiError ? e.message : 'Could not end the assignment.')));
    return false;
  }
}

/// "Set policies" — mirrors web `set-policies-panel.tsx`: choose a group, see for every policy type
/// what applies today and where it comes from, pick new policies, then review and save them all at
/// once from one date. Attendance, overtime, regularization and leave changes are saved together
/// (`POST /policy-assignments/batch`, all or nothing); work calendar and weekly-off changes then go
/// through the impact preview one at a time, as on web.
class SetPoliciesPanel extends ConsumerStatefulWidget {
  const SetPoliciesPanel({super.key});

  @override
  ConsumerState<SetPoliciesPanel> createState() => _SetPoliciesPanelState();
}

class _SetPoliciesPanelState extends ConsumerState<SetPoliciesPanel> {
  String _scopeType = 'COMPANY';
  String? _scopeId;
  String? _employeeName;

  Rec? _coverage;
  ApiError? _error;
  bool _loading = false;
  int _request = 0;

  Map<String, List<PolicyOption>> _optionsByKind = const {};
  Map<String, List<PolicyOption>> _scopeOptions = const {};

  Map<String, String> _picks = {};
  late String _effectiveFrom = _today;
  final _reason = TextEditingController();
  String? _formError;
  bool _saving = false;

  ApiClient get _client => ref.read(apiClientProvider);
  String get _today => businessToday(ref.read(authControllerProvider).user?.companyTimezone ?? 'Asia/Kolkata');
  bool get _ready => _scopeType == 'COMPANY' || _scopeId != null;
  String? get _scopeRef => _scopeType == 'COMPANY' ? null : _scopeId;

  @override
  void initState() {
    super.initState();
    _loadOptions();
    _loadCoverage();
  }

  @override
  void dispose() {
    _reason.dispose();
    super.dispose();
  }

  Future<List<Rec>> _all(String path, Map<String, String> query) async {
    final out = <Rec>[];
    for (var page = 1; page <= 20; page++) {
      final env = await _client.getList<Rec>(path, query: PageQuery(page: page, perPage: 100), filters: query, parseItem: (d) => d as Rec);
      out.addAll(env.data);
      if (env.pagination == null || !env.pagination!.hasNext) break;
    }
    return out;
  }

  /// Policies per kind and the groups per scope type; a list that fails is simply empty, as on web.
  Future<void> _loadOptions() async {
    Future<List<PolicyOption>> load(String path, Map<String, String> query) => _all(path, query).then(activeOptions).catchError((_) => <PolicyOption>[]);
    final kinds = policyKindListPaths.keys.toList();
    final scopes = scopeListPaths.keys.toList();
    final results = await Future.wait([
      for (final k in kinds) load(policyKindListPaths[k]!, assignableQuery(k)),
      for (final s in scopes) load(scopeListPaths[s]!, const {}),
    ]);
    if (!mounted) return;
    setState(() {
      _optionsByKind = {for (var i = 0; i < kinds.length; i++) kinds[i]: results[i]};
      _scopeOptions = {for (var i = 0; i < scopes.length; i++) scopes[i]: results[kinds.length + i]};
    });
  }

  Future<void> _loadCoverage() async {
    if (!_ready) return;
    final mine = ++_request;
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final coverage = await _client.get<Rec>(
        '/policy-assignments/coverage?${Uri(queryParameters: coverageQuery(_scopeType, _scopeRef, _today)).query}',
        parse: (d) => d as Rec,
      );
      if (mounted && mine == _request) setState(() => _coverage = coverage);
    } catch (e) {
      if (mounted && mine == _request) {
        setState(() {
          _coverage = null;
          _error = e is ApiError ? e : ApiError(status: 0, code: 'UNKNOWN_ERROR', message: 'Something went wrong.');
        });
      }
    } finally {
      if (mounted && mine == _request) setState(() => _loading = false);
    }
  }

  void _changeScope(String type, String? id, {String? employeeName}) {
    setState(() {
      _scopeType = type;
      _scopeId = id;
      _employeeName = employeeName;
      _coverage = null;
      _error = null;
      _picks = {};
      _formError = null;
    });
    _loadCoverage();
  }

  List<CoverageRow> get _rows => _coverage == null ? const [] : coverageRows(_coverage!);
  List<CoverageChange> get _changes => pendingChanges(_rows, _picks, _optionsByKind);

  Future<void> _pickDate() async {
    final current = DateTime.parse(_effectiveFrom);
    final picked = await showDatePicker(context: context, helpText: 'Effective from', initialDate: current, firstDate: DateTime(current.year - 5), lastDate: DateTime(current.year + 5));
    if (picked != null) setState(() => _effectiveFrom = _iso(picked));
  }

  Future<void> _review() async {
    final changes = _changes;
    final problem = effectiveFromError(_effectiveFrom, changes);
    setState(() => _formError = problem);
    if (problem != null) return;
    final previewed = changes.where((c) => needsImpactPreview(c.row.kind)).length;
    final confirmed = await showModalBottomSheet<bool>(
      context: context,
      isScrollControlled: true,
      showDragHandle: true,
      builder: (ctx) => _ReviewSheet(
        changes: changes,
        scopeLabel: scopeTypeLabels[_scopeType] ?? _scopeType,
        effectiveFrom: _effectiveFrom,
        inPast: _effectiveFrom.compareTo(_today) < 0,
        previewed: previewed,
        save: _saveDirect,
      ),
    );
    if (confirmed == true && mounted) await _previewCalendars(changes);
  }

  /// Saves the non-calendar changes together. Returns null on success, else the message to show
  /// in the review sheet (which stays open). Nothing is saved when it fails.
  Future<String?> _saveDirect(List<CoverageChange> changes) async {
    final direct = changes.where((c) => !needsImpactPreview(c.row.kind)).toList();
    if (direct.isEmpty) return null;
    setState(() => _saving = true);
    try {
      await _client.post<Object?>(
        '/policy-assignments/batch',
        body: batchBody(scopeType: _scopeType, scopeId: _scopeRef, effectiveFrom: _effectiveFrom, reason: _reason.text, changes: direct),
        parse: (_) => null,
      );
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(direct.length == 1 ? 'Assignment saved' : '${direct.length} assignments saved')));
        setState(() {
          for (final c in direct) {
            _picks.remove(c.row.key);
          }
        });
      }
      return null;
    } catch (e) {
      final context = e is ApiError && e.details.isNotEmpty ? e.details.first.context : null;
      final failed = failedChange(direct, context);
      return 'Nothing was saved. ${failed != null ? '${failed.row.label}: ' : ''}${describeApiError(e)}';
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  /// Work calendar and weekly-off changes, one impact preview at a time. Cancelling one stops the
  /// rest; what was already saved stays saved.
  Future<void> _previewCalendars(List<CoverageChange> changes) async {
    for (final c in changes.where((c) => needsImpactPreview(c.row.kind))) {
      final applied = await reviewCalendarChange(
        context,
        title: 'Change ${c.row.label}',
        change: impactChange(change: c, scopeType: _scopeType, scopeId: _scopeRef, effectiveFrom: _effectiveFrom, reason: _reason.text),
      );
      if (!mounted) return;
      if (!applied) break;
      setState(() => _picks.remove(c.row.key));
    }
    if (!mounted) return;
    if (_picks.isEmpty) _reason.clear();
    _loadCoverage();
  }

  Future<void> _returnToInherited(CoverageRow row) async {
    final own = row.own!;
    final ended = await endPolicyAssignment(context, _client, id: '${own['assignment_id']}', version: own['version'], effectiveFrom: '${own['effective_from']}');
    if (ended && mounted) _loadCoverage();
  }

  Widget _scopePicker() {
    final options = _scopeOptions[_scopeType] ?? const <PolicyOption>[];
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      DropdownButtonFormField<String>(
        value: _scopeType,
        isExpanded: true,
        decoration: const InputDecoration(labelText: 'Who does this apply to?'),
        items: [for (final s in coverageScopeTypes) DropdownMenuItem(value: s, child: Text(scopeTypeLabels[s] ?? s))],
        onChanged: (v) => _changeScope(v ?? 'COMPANY', null),
      ),
      if (_scopeType == 'EMPLOYEE') ...[
        const SizedBox(height: 8),
        OutlinedButton.icon(
          icon: const Icon(Icons.person_search_outlined),
          label: Text(_employeeName ?? 'Choose employee'),
          onPressed: () async {
            final picked = await pickEmployee(context);
            if (picked != null) _changeScope('EMPLOYEE', picked.id, employeeName: employeeDisplayName(picked));
          },
        ),
      ] else if (_scopeType != 'COMPANY') ...[
        const SizedBox(height: 8),
        DropdownButtonFormField<String>(
          key: ValueKey('scope-$_scopeType'),
          value: _scopeId,
          isExpanded: true,
          decoration: InputDecoration(labelText: scopeTypeLabels[_scopeType]),
          hint: const Text('Choose…'),
          items: [for (final o in options) DropdownMenuItem(value: o.id, child: Text(o.name, overflow: TextOverflow.ellipsis))],
          onChanged: (v) => _changeScope(_scopeType, v),
        ),
      ],
    ]);
  }

  Widget _rowCard(CoverageRow row) {
    final theme = Theme.of(context);
    final muted = TextStyle(fontSize: 12, color: theme.colorScheme.onSurfaceVariant);
    final applied = row.applied;
    final own = row.own;
    final startsLater = own != null && '${own['effective_from']}'.compareTo(_today) > 0;
    final options = rowOptions(row, _optionsByKind[row.kind] ?? const []);
    final value = _picks[row.key] ?? own?['policy_id'] as String? ?? '';
    return AppCard(
      padding: const EdgeInsets.all(14),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text(row.label, style: theme.textTheme.titleSmall?.copyWith(fontWeight: FontWeight.w700)),
        const SizedBox(height: 6),
        Text('APPLIES TODAY', style: theme.textTheme.labelSmall?.copyWith(color: theme.colorScheme.onSurfaceVariant, letterSpacing: 0.6)),
        if (applied == null)
          const Padding(padding: EdgeInsets.only(top: 4), child: StatusChip(label: 'Not set', dot: false))
        else ...[
          Text((applied['policy_name'] as String?) ?? 'Name unavailable'),
          Text(appliedNote(applied, _scopeType), style: muted),
          if (applied['has_rules'] == false) Text('This policy has no published rules for today.', style: TextStyle(fontSize: 12, color: theme.colorScheme.error)),
        ],
        if (startsLater) Text('Changes to ${(own['policy_name'] as String?) ?? 'another policy'} from ${coverageDate('${own['effective_from']}')}', style: muted),
        const SizedBox(height: 8),
        DropdownButtonFormField<String>(
          value: value,
          isExpanded: true,
          decoration: InputDecoration(labelText: 'Change to', isDense: true, helperText: _picks[row.key] != null && _picks[row.key] != own?['policy_id'] ? 'Changed' : null),
          items: [
            if (own == null) DropdownMenuItem(value: '', child: Text(applied != null ? 'Keep inherited' : 'Not set')),
            for (final o in options) DropdownMenuItem(value: o.id, child: Text(o.name, overflow: TextOverflow.ellipsis)),
          ],
          onChanged: (v) => setState(() => _picks[row.key] = v ?? ''),
        ),
        if (canReturnToInherited(row, _scopeType))
          Align(alignment: Alignment.centerLeft, child: TextButton(onPressed: () => _returnToInherited(row), child: const Text('Return to inherited'))),
      ]),
    );
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final changes = _changes;
    final children = <Widget>[_scopePicker(), const SizedBox(height: 12)];
    if (!_ready) {
      children.add(const Padding(padding: EdgeInsets.symmetric(vertical: 40), child: Text('Choose who to see what they follow.', textAlign: TextAlign.center)));
    } else if (_error != null) {
      children.add(StateMessage(
        icon: Icons.error_outline_rounded,
        tone: Tone.danger,
        title: 'Something went wrong',
        message: _error!.status == 403 ? 'You do not have permission to manage policy assignments.' : _error!.message,
        actionLabel: 'Try again',
        onAction: _loadCoverage,
      ));
    } else if (_coverage == null) {
      children.add(const Padding(padding: EdgeInsets.all(24), child: Center(child: CircularProgressIndicator(semanticsLabel: 'Loading policies'))));
    } else {
      if (_loading) children.add(const LinearProgressIndicator());
      for (final row in _rows) {
        children.add(Padding(padding: const EdgeInsets.only(bottom: 10), child: _rowCard(row)));
      }
      children.addAll([
        const SizedBox(height: 4),
        InkWell(
          onTap: _pickDate,
          child: InputDecorator(
            decoration: const InputDecoration(labelText: 'Effective from', suffixIcon: Icon(Icons.calendar_today_outlined)),
            child: Text(coverageDate(_effectiveFrom)),
          ),
        ),
        const SizedBox(height: 8),
        TextField(controller: _reason, decoration: const InputDecoration(labelText: 'Reason (optional)')),
        if (_formError != null) Padding(padding: const EdgeInsets.only(top: 8), child: Text(_formError!, style: TextStyle(color: theme.colorScheme.error))),
        const SizedBox(height: 12),
        FilledButton(
          onPressed: changes.isEmpty || _saving ? null : _review,
          child: Text(changes.isEmpty ? 'No changes' : (changes.length == 1 ? 'Review 1 change' : 'Review ${changes.length} changes')),
        ),
      ]);
    }
    return RefreshIndicator(
      onRefresh: _loadCoverage,
      child: ListView(padding: const EdgeInsets.fromLTRB(16, 12, 16, 96), children: children),
    );
  }
}

/// Web's "Review changes" dialog as a sheet: the list of changes, warnings, then Confirm. The
/// sheet stays open with the message if the save fails.
class _ReviewSheet extends StatefulWidget {
  const _ReviewSheet({required this.changes, required this.scopeLabel, required this.effectiveFrom, required this.inPast, required this.previewed, required this.save});
  final List<CoverageChange> changes;
  final String scopeLabel;
  final String effectiveFrom;
  final bool inPast;
  final int previewed;
  final Future<String?> Function(List<CoverageChange>) save;

  @override
  State<_ReviewSheet> createState() => _ReviewSheetState();
}

class _ReviewSheetState extends State<_ReviewSheet> {
  bool _saving = false;
  String? _error;

  Future<void> _confirm() async {
    setState(() {
      _saving = true;
      _error = null;
    });
    final error = await widget.save(widget.changes);
    if (!mounted) return;
    if (error == null) {
      Navigator.of(context).pop(true);
    } else {
      setState(() {
        _saving = false;
        _error = error;
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final muted = TextStyle(color: theme.colorScheme.onSurfaceVariant);
    return PopScope(
      canPop: !_saving,
      child: SafeArea(
        child: Padding(
          padding: const EdgeInsets.fromLTRB(16, 0, 16, 16),
          child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text('Review changes', style: theme.textTheme.titleLarge),
            const SizedBox(height: 4),
            Text('For ${widget.scopeLabel}, from ${coverageDate(widget.effectiveFrom)}.', style: muted),
            const SizedBox(height: 10),
            Flexible(
              child: ListView(shrinkWrap: true, children: [
                for (final c in widget.changes)
                  ListTile(
                    contentPadding: EdgeInsets.zero,
                    title: Text(c.row.label),
                    subtitle: Text('${(c.row.own?['policy_name'] ?? c.row.applied?['policy_name'] ?? 'Not set')} → ${c.policyName}'),
                  ),
              ]),
            ),
            if (widget.inPast) Text('This starts in the past.', style: TextStyle(color: toneColors(context, Tone.warning).fg)),
            if (widget.previewed > 0)
              Padding(
                padding: const EdgeInsets.only(top: 6),
                child: Text(
                  'Work calendar and weekly-off changes open an impact preview next, one at a time. Other changes are saved first, and stay saved if you cancel a preview.',
                  style: muted,
                ),
              ),
            if (_error != null) Padding(padding: const EdgeInsets.only(top: 8), child: Text(_error!, style: TextStyle(color: theme.colorScheme.error))),
            const SizedBox(height: 12),
            Row(mainAxisAlignment: MainAxisAlignment.end, children: [
              TextButton(onPressed: _saving ? null : () => Navigator.of(context).pop(false), child: const Text('Back')),
              const SizedBox(width: 8),
              FilledButton(onPressed: _saving ? null : _confirm, child: Text(_saving ? 'Saving…' : 'Confirm')),
            ]),
          ]),
        ),
      ),
    );
  }
}
