import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../core/api/api_client.dart';
import '../../../core/api/api_error.dart';
import '../../../core/forms/choice_sources.dart';
import '../../../core/forms/form_spec.dart';
import '../../../core/forms/spec_form_screen.dart';
import '../../../core/providers.dart';
import '../../../core/time.dart';
import '../../../core/widgets/ui.dart';
import '../../auth/state/auth_controller.dart';
import '../../organisation/presentation/change_impact_screen.dart';
import '../domain/policy_assignment_form.dart';
import '../domain/policy_coverage.dart';
import '../domain/policy_followers.dart';
import 'set_policies_panel.dart' show endPolicyAssignment;

/// The add form (web `assign-policy-dialog.tsx`): who, from when, and why.
final _followerSpec = FormSpec(name: 'policy_follower', label: 'Who follows it', fields: [
  FieldSpec('scope_type', 'Who', kind: FieldKind.select, required: true, options: coverageScopeTypes, optionLabels: scopeTypeLabels),
  const FieldSpec('scope_id', 'Applies to', kind: FieldKind.choice, required: true, showWhen: 'scope_type!=COMPANY', dependsOn: 'scope_type', choiceMap: scopeSources),
  const FieldSpec('effective_from', 'Starts on', kind: FieldKind.date, required: true),
  const FieldSpec('reason', 'Reason (optional)', kind: FieldKind.multiline),
]);

/// "Who follows this" on a policy's own screen — mirrors web `policy-followers-panel.tsx`: the
/// groups and people the policy applies to today or from a later date, adding more, and ending
/// one. Rules by Group (Policy Assignments) stays the place to compare every kind at once.
class PolicyFollowersSection extends ConsumerStatefulWidget {
  const PolicyFollowersSection({super.key, required this.kind, required this.policy, this.manage, this.versionsPath, this.leaveTypeId});

  /// `ATTENDANCE_POLICY`, `WORK_CALENDAR`, …
  final String kind;
  final Map<String, dynamic> policy;

  /// The policy's own manage permission; assignment permissions are checked on top of it.
  final String? manage;

  /// For versioned policies: where its versions live, to tell whether it has published rules.
  final String? versionsPath;
  final String? leaveTypeId;

  @override
  ConsumerState<PolicyFollowersSection> createState() => _PolicyFollowersSectionState();
}

class _PolicyFollowersSectionState extends ConsumerState<PolicyFollowersSection> {
  List<Rec>? _rows;
  bool _truncated = false;
  ApiError? _error;
  bool? _hasPublished;
  Map<String, String> _names = const {};

  ApiClient get _client => ref.read(apiClientProvider);
  String get _zone => ref.read(authControllerProvider).user?.companyTimezone ?? 'Asia/Kolkata';
  String get _today => businessToday(_zone);
  String get _id => '${widget.policy['id']}';
  String get _policyName => '${widget.policy['name'] ?? 'this policy'}';

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void didUpdateWidget(PolicyFollowersSection old) {
    super.didUpdateWidget(old);
    // The detail screen reloads the record after an edit or a publish.
    if (old.policy['version'] != widget.policy['version']) _load();
  }

  Future<void> _load() async {
    setState(() => _error = null);
    try {
      final env = await _client.getList<Rec>(
        '/policy-assignments',
        query: PageQuery(perPage: followersPageSize),
        filters: {'policy_kind': widget.kind, 'policy_id': _id},
        parseItem: (d) => d as Rec,
      );
      if (!mounted) return;
      setState(() {
        _rows = liveFollowers(env.data, _today);
        _truncated = (env.pagination?.total ?? 0) > env.data.length;
      });
      _loadNames();
    } catch (e) {
      if (mounted) setState(() => _error = e is ApiError ? e : ApiError(status: 0, code: 'UNKNOWN_ERROR', message: 'Something went wrong.'));
    }
    final path = widget.versionsPath;
    if (path != null) {
      try {
        final versions = await _client.getList<Rec>(path, query: PageQuery(perPage: 100), parseItem: (d) => d as Rec);
        if (mounted) setState(() => _hasPublished = versions.data.any((v) => v['status'] == 'PUBLISHED' && v['effective_to'] == null));
      } catch (_) {
        if (mounted) setState(() => _hasPublished = null);
      }
    }
  }

  /// Only the names this list needs, as on web.
  Future<void> _loadNames() async {
    final rows = _rows ?? const <Rec>[];
    final sources = {for (final a in rows) if (a['scope_id'] != null && a['scope_type'] != 'EMPLOYEE') scopeSources['${a['scope_type']}']}.whereType<String>();
    final people = {for (final a in rows) if (a['scope_type'] == 'EMPLOYEE' && a['scope_id'] != null) '${a['scope_id']}'};
    final found = <String, String>{};
    try {
      final set = await loadChoicesTolerant(_client, optional: sources);
      for (final list in set.choices.values) {
        for (final c in list) {
          found[c.value] = c.label;
        }
      }
    } catch (_) {}
    for (final id in people) {
      try {
        final e = await _client.get<Rec>('/employees/$id', parse: (d) => d as Rec);
        final display = '${e['display_name'] ?? ''}'.trim();
        found[id] = display.isNotEmpty ? display : [e['first_name'], e['middle_name'], e['last_name']].where((s) => s != null && '$s'.trim().isNotEmpty).join(' ');
      } catch (_) {}
    }
    if (mounted) setState(() => _names = {..._names, ...found});
  }

  String _who(Rec a) {
    final label = scopeTypeLabels['${a['scope_type']}'] ?? '${a['scope_type']}';
    final id = a['scope_id'] as String?;
    return id == null ? label : '$label: ${_names[id] ?? '…'}';
  }

  bool get _canManage {
    final perms = ref.watch(authControllerProvider).user?.permissions ?? const <String>[];
    return (widget.manage == null || perms.contains(widget.manage)) && assignmentPermissionsFor(widget.kind).every(perms.contains);
  }

  String? get _cannotAssign => cannotAssignReason(
        kind: widget.kind,
        isActive: widget.policy['is_active'] != false,
        // Unknown (still loading or unreadable) is not a reason to block; the server decides.
        hasPublishedRules: widget.versionsPath == null || _hasPublished != false,
      );

  Future<void> _add() async {
    Map<String, dynamic>? preview;
    final saved = await openSpecForm(
      context,
      title: 'Add who follows $_policyName',
      spec: _followerSpec,
      defaults: {'scope_type': 'BRANCH', 'effective_from': _today},
      submitLabel: needsImpactPreview(widget.kind) ? 'Preview changes' : 'Assign',
      loadChoiceSet: () => loadChoicesTolerant(_client, optional: scopeSources.values),
      onSubmit: (p, _) async {
        final scopeType = '${p['scope_type']}';
        final scopeId = scopeType == 'COMPANY' ? null : p['scope_id'] as String?;
        final from = '${p['effective_from']}';
        final reason = '${p['reason'] ?? ''}'.trim();
        // What this group follows now, so a replacement carries its version (web `useCoverageRow`).
        final coverage = await _client.get<Rec>('/policy-assignments/coverage?${Uri(queryParameters: coverageQuery(scopeType, scopeId, _today)).query}', parse: (d) => d as Rec);
        final row = coverageRows(coverage).where((r) => r.kind == widget.kind && r.leaveTypeId == widget.leaveTypeId).firstOrNull;
        final problem = assignError(own: row?.own, policyId: _id, effectiveFrom: from);
        if (problem != null) throw ApiError(status: 422, code: 'ASSIGNMENT_NOT_ALLOWED', message: problem);
        if (needsImpactPreview(widget.kind)) {
          preview = {
            'change_type': 'ASSIGNMENT_CREATE',
            if (row?.own?['version'] != null) 'expected_version': row!.own!['version'],
            'body': {'policy_kind': widget.kind, 'policy_id': _id, 'scope_type': scopeType, 'scope_id': scopeId, 'effective_from': from, 'reason': reason.isEmpty ? null : reason},
          };
          return;
        }
        await _client.post<Object?>(
          '/policy-assignments/batch',
          body: {
            'scope_type': scopeType,
            'scope_id': scopeId,
            'effective_from': from,
            'reason': reason.isEmpty ? null : reason,
            'changes': [
              {'policy_kind': widget.kind, 'policy_id': _id, 'leave_type_id': widget.leaveTypeId, 'expected_version': row?.own?['version']},
            ],
          },
          parse: (_) => null,
        );
      },
    );
    if (!saved || !mounted) return;
    final change = preview;
    if (change != null) {
      await reviewCalendarChange(context, title: 'Assign $_policyName', change: change);
    } else {
      ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Assignment saved')));
    }
    if (mounted) _load();
  }

  Future<void> _end(Rec a) async {
    final ended = await endPolicyAssignment(context, _client, id: '${a['id']}', version: a['version'], effectiveFrom: '${a['effective_from']}');
    if (ended && mounted) _load();
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final muted = theme.textTheme.bodySmall?.copyWith(color: theme.colorScheme.onSurfaceVariant);
    final canManage = _canManage;
    final blocked = _cannotAssign;
    final rows = _rows;
    final today = _today;
    final addButton = canManage && blocked == null
        ? FilledButton.icon(onPressed: _add, icon: const Icon(Icons.add), label: const Text('Add who follows it'))
        : null;
    return Padding(
      padding: const EdgeInsets.only(top: 16),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text('Who follows this', style: theme.textTheme.titleMedium?.copyWith(fontWeight: FontWeight.w700)),
        const SizedBox(height: 8),
        if (blocked != null && canManage) Padding(padding: const EdgeInsets.only(bottom: 8), child: Text(blocked, style: theme.textTheme.bodyMedium)),
        if (_error != null)
          StateMessage(
            icon: Icons.error_outline_rounded,
            tone: Tone.danger,
            title: 'Something went wrong',
            message: _error!.status == 403 ? 'You do not have permission to see who follows this policy.' : _error!.message,
            actionLabel: 'Retry',
            onAction: _load,
          )
        else if (rows == null)
          const Padding(padding: EdgeInsets.all(16), child: Center(child: CircularProgressIndicator(strokeWidth: 2.5)))
        else if (rows.isEmpty) ...[
          Text('Nobody follows this policy yet', style: theme.textTheme.titleSmall),
          Text('Choose the whole company, a branch, department or other group, or a single person.', style: muted),
          if (addButton != null) Padding(padding: const EdgeInsets.only(top: 8), child: addButton),
        ] else ...[
          Text('People in these groups follow this policy unless something more specific is set for them.', style: muted),
          const SizedBox(height: 8),
          for (final a in rows)
            Padding(
              padding: const EdgeInsets.only(bottom: 8),
              child: ListRowCard(
                title: _who(a),
                subtitle: '${coverageDate('${a['effective_from']}')} – ${a['effective_to'] == null ? 'No end date' : coverageDate('${a['effective_to']}')}',
                showChevron: false,
                trailing: Row(mainAxisSize: MainAxisSize.min, children: [
                  if ('${a['effective_from']}'.compareTo(today) > 0) const StatusChip(label: 'Starts later', tone: Tone.neutral),
                  if (canManage && canEndAssignment(widget.kind, '${a['scope_type']}', a['effective_to'])) TextButton(onPressed: () => _end(a), child: const Text('End')),
                ]),
              ),
            ),
          if (addButton != null) addButton,
        ],
        if (_truncated) Padding(padding: const EdgeInsets.only(top: 8), child: Text('Showing the first $followersPageSize. See every assignment in Rules by Group.', style: muted)),
        const SizedBox(height: 8),
        Text(
          [
            if (rows?.any((a) => a['scope_type'] == 'COMPANY') ?? false)
              "The whole-company assignment is the fallback for everyone, so it can't be ended here; replace it by giving the whole company another policy.",
            if (needsImpactPreview(widget.kind)) 'Calendar changes are replaced rather than ended, after a preview of the days they change.',
            'To compare every policy a group follows, use Rules by Group.',
          ].join(' '),
          style: muted,
        ),
        Align(alignment: Alignment.centerLeft, child: TextButton(onPressed: () => context.push('/app/policy-assignments'), child: const Text('Open Rules by Group'))),
      ]),
    );
  }
}

/// A [ResourceConfig.detailFooter] showing who follows the record. [versionsPath] is the policy
/// list path when the record is versioned (its rules must be published before it can be assigned);
/// [leaveTyped] passes the leave policy's leave type along with each assignment.
Widget Function(BuildContext, Map<String, dynamic>, VoidCallback) followersFooter(String kind, {String? manage, String? versionsPath, bool leaveTyped = false}) =>
    (context, row, reload) => PolicyFollowersSection(
          key: ValueKey('followers-${row['id']}'),
          kind: kind,
          policy: row,
          manage: manage,
          versionsPath: versionsPath == null ? null : '$versionsPath/${row['id']}/versions',
          leaveTypeId: leaveTyped ? row['leave_type_id'] as String? : null,
        );
