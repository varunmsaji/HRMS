import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../api/api_client.dart';
import '../api/api_error.dart';
import '../forms/choice_sources.dart';
import '../forms/form_spec.dart';
import '../forms/spec_form_screen.dart';
import '../providers.dart';
import '../time.dart';
import '../../features/auth/presentation/widgets/auth_form_field.dart';
import '../../features/auth/state/auth_controller.dart';
import '../../features/shell/more_action.dart';
import 'request_config.dart';
import '../status_words.dart';
import '../widgets/list_filter.dart';
import '../widgets/ui.dart' hide DetailSection;
import '../widgets/ui.dart' as ui show DetailSection;
import '../theme/employee_theme_scope.dart';
import '../diagnostics/app_diagnostics.dart';

/// A request's status, in the shared words and theme colours (audit MOB-UX-042, 039). [labels]
/// overrides a word for one resource; most pass none.
class RequestStatusChip extends StatelessWidget {
  const RequestStatusChip({super.key, required this.status, this.labels = const {}});
  final String status;
  final Map<String, String> labels;

  @override
  Widget build(BuildContext context) => StatusChip.request(status, labels: labels);
}

/// A "Mine / Team" list with date, status and extra filters — mirrors the web list pages
/// (`regularizations/page.tsx`, `overtime/page.tsx`). Both views are the same permission-scoped
/// read; the server only returns what the caller may see. Defaults to the last 30 business days.
/// Choice sources the API has refused (403) for this user in this session, so a form does not ask a
/// forbidden endpoint again. Keyed by user id: the next user starts clean.
final deniedChoiceSourcesProvider = StateProvider.family<Set<String>, String>((ref, userId) => const {});

class RequestListScreen extends ConsumerStatefulWidget {
  const RequestListScreen({super.key, required this.config, this.decisionCenter});
  final RequestConfig config;

  /// The approver's screen, offered beside Mine and Team when given.
  final Widget? decisionCenter;

  @override
  ConsumerState<RequestListScreen> createState() => _RequestListScreenState();
}

class _RequestListScreenState extends ConsumerState<RequestListScreen> {
  late bool _team;
  late ListFilter _defaults;
  late ListFilter _filter;
  bool _decisions = false;
  int _decisionsKey = 0;
  bool _loading = true;
  ApiError? _error;
  List<Rec> _rows = const [];
  List<Choice> _employees = const [];

  RequestConfig get _c => widget.config;
  List<String> get _perms => ref.read(authControllerProvider).user?.permissions ?? const <String>[];
  String get _zone => ref.read(authControllerProvider).user?.companyTimezone ?? 'Asia/Kolkata';

  @override
  void initState() {
    super.initState();
    // The company account has no employee record, so "Mine" would mean nothing: it starts on Team.
    _team = _perms.contains(_c.approvePermission) || ref.read(authControllerProvider).user?.employeeId == null;
    // An approver starts on what is waiting for them, as on the web.
    _decisions = widget.decisionCenter != null && _perms.contains(_c.approvePermission);
    _defaults = ListFilter(from: businessDayOffset(_zone, -30), to: businessToday(_zone));
    _filter = _defaults;
    _loadEmployees();
    if (!_decisions) _load();
  }

  Future<void> _loadEmployees() async {
    if (!_perms.contains(_c.approvePermission) && !(_c.onBehalfPermission != null && _perms.contains(_c.onBehalfPermission))) return;
    try {
      final c = await loadChoices(ref.read(apiClientProvider), const ['employees']);
      if (mounted) setState(() => _employees = c['employees'] ?? const []);
    } catch (e, s) { AppDiagnostics.instance.recordHandled(e, s); }
  }

  Future<void> _load() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    final myEmployeeId = ref.read(authControllerProvider).user?.employeeId;
    final status = _filter.group('status');
    final common = <String, dynamic>{
      for (final f in _c.filters)
        if (_filter.group(f.param).isNotEmpty) f.param: _filter.group(f.param),
      if (!_team && myEmployeeId != null) 'employee_id': myEmployeeId,
      if (_team && _filter.employee.isNotEmpty) 'employee_id': _filter.employee,
    };
    Future<List<Rec>> fetch(Map<String, dynamic> filters) async => (await ref.read(apiClientProvider).getList<Rec>(
          _c.path,
          query: PageQuery(perPage: 100),
          filters: {...common, ...filters},
          parseItem: (d) => d as Rec,
        ))
            .data;
    try {
      final open = _c.openStatus;
      final results = await Future.wait([
        fetch({
          if (_filter.from != null) 'date_from': _filter.from,
          if (_filter.to != null) 'date_to': _filter.to,
          if (status.isNotEmpty) _c.statusParam: status,
        }),
        // Anything still waiting, whatever its date, unless a status was chosen.
        if (status.isEmpty && open != null) fetch({_c.statusParam: open}),
      ]);
      final seen = <Object?>{};
      final rows = [
        for (final list in results)
          for (final r in list)
            if (seen.add(r['id'])) r,
      ];
      if (mounted) setState(() => _rows = rows);
    } catch (e) {
      if (mounted) setState(() => _error = e is ApiError ? e : ApiError(status: 0, code: 'UNKNOWN_ERROR', message: 'Something went wrong.'));
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _create() async {
    final onBehalf = _team || _decisions;
    final client = ref.read(apiClientProvider);
    final zone = _zone;
    final required = [if (onBehalf) 'employees', ..._c.createChoiceKeys];
    final optional = _c.optionalChoiceKeys;
    final userId = ref.read(authControllerProvider).user?.id ?? '';
    final denied = ref.read(deniedChoiceSourcesProvider(userId).notifier);
    final saved = await openSpecForm(
      context,
      title: onBehalf ? '${_c.singular} on behalf' : _c.singular,
      spec: _c.createSpec!(onBehalf),
      submitLabel: 'Submit request',
      loadChoiceSet: (required.isEmpty && optional.isEmpty)
          ? null
          : () async {
              final set = await loadChoicesTolerant(client, required: required, optional: optional, knownDenied: denied.state);
              // A 403 is remembered for the session so the refused endpoint is not asked again.
              final newlyDenied = {for (final e in set.unavailable.entries) if (e.value == ChoiceUnavailable.denied) e.key};
              if (newlyDenied.difference(denied.state).isNotEmpty) denied.state = {...denied.state, ...newlyDenied};
              return set;
            },
      onSubmit: (payload, _) async => client.post<Object?>(_c.path, body: _c.buildCreateBody!(payload, zone), parse: (_) => null),
    );
    if (saved && mounted) {
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('${_c.singular} submitted.')));
      setState(() => _decisionsKey++);
      _load();
    }
  }

  /// Back from a request: re-reads only that one and updates it in place, keeping the scroll
  /// position (audit MOB-UX-010).
  Future<void> _refreshRow(String id) async {
    try {
      final fresh = await ref.read(apiClientProvider).get<Rec>('${_c.path}/$id', parse: (d) => d as Rec);
      if (mounted) setState(() => _rows = [for (final r in _rows) r['id'] == id ? fresh : r]);
    } catch (e, s) { AppDiagnostics.instance.recordHandled(e, s); }
  }

  List<FilterGroup> get _groups => [
        FilterGroup(key: 'status', label: 'Status', options: [for (final st in _c.statuses) (st, _c.statusLabels[st] ?? requestStatusLabel(st))]),
        for (final f in _c.filters) FilterGroup(key: f.param, label: f.label, options: f.options),
      ];

  Future<void> _openFilter() async {
    final next = await showListFilterSheet(context, initial: _filter, defaults: _defaults, groups: _groups, employees: _team ? _employees : null);
    if (next == null || next == _filter || !mounted) return;
    setState(() => _filter = next);
    _load();
  }

  String _filterSummary() {
    final status = _filter.group('status');
    final dates = _filter.from == _defaults.from && _filter.to == _defaults.to ? 'Last 30 days' : describeDates(_filter.from, _filter.to);
    return [
      // The open ones are added whatever their date; say so, or an old one looks misplaced.
      status.isEmpty && _c.openStatus != null ? '$dates, plus anything awaiting approval' : dates,
      if (status.isNotEmpty) _c.statusLabels[status] ?? requestStatusLabel(status),
      for (final f in _c.filters)
        if (_filter.group(f.param).isNotEmpty) f.options.firstWhere((o) => o.$1 == _filter.group(f.param), orElse: () => (_filter.group(f.param), _filter.group(f.param))).$2,
      if (_team && _filter.employee.isNotEmpty) _employeeName(_filter.employee),
    ].join(' · ');
  }

  String _employeeName(String id) {
    for (final c in _employees) {
      if (c.value == id) return c.label;
    }
    return '';
  }

  @override
  Widget build(BuildContext context) {
    final perms = ref.watch(authControllerProvider).user?.permissions ?? const <String>[];
    final canApprove = perms.contains(_c.approvePermission);
    final onBehalf = _c.onBehalfPermission != null && perms.contains(_c.onBehalfPermission);
    final notMine = _team || _decisions;
    final canCreate = _c.createSpec != null && (notMine ? onBehalf : (_c.submitPermission == null || perms.contains(_c.submitPermission)));
    final scopes = [
      if (ref.read(authControllerProvider).user?.employeeId != null) const ButtonSegment(value: 'mine', label: Text('Mine')),
      if (widget.decisionCenter != null && canApprove) const ButtonSegment(value: 'decisions', label: Text('Decisions')),
      if (canApprove || onBehalf) const ButtonSegment(value: 'team', label: Text('Team')),
    ];
    return Scaffold(
      appBar: AppBar(title: Text(_c.title), actions: const [MoreAction()]),
      floatingActionButton: canCreate ? FloatingActionButton.extended(onPressed: _create, icon: const Icon(Icons.add), label: Text(notMine ? '${_c.singular} on behalf' : _c.singular)) : null,
      body: Column(children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(16, 12, 16, 0),
          child: Column(children: [
            if (scopes.length > 1)
              SegmentedButton<String>(
                showSelectedIcon: false,
                segments: scopes,
                selected: {_decisions ? 'decisions' : (_team ? 'team' : 'mine')},
                onSelectionChanged: (s) {
                  setState(() {
                    _decisions = s.first == 'decisions';
                    _team = s.first == 'team';
                  });
                  if (!_decisions) _load();
                },
              ),
            const SizedBox(height: 8),
            if (!_decisions)
              ListFilterBar(summary: _filterSummary(), activeCount: _filter.countAgainst(_defaults), onTap: _openFilter),
          ]),
        ),
        Expanded(
          child: _decisions
              ? KeyedSubtree(key: ValueKey(_decisionsKey), child: widget.decisionCenter!)
              : _loading
              ? const ListSkeleton()
              : _error != null
                  ? StateMessage(icon: Icons.error_outline_rounded, tone: Tone.danger, title: "Couldn't load requests", message: describeApiError(_error!), actionLabel: 'Try again', onAction: _load)
                  : RefreshIndicator(
                      onRefresh: _load,
                      child: ListView(
                        padding: const EdgeInsets.only(top: 8, bottom: 88),
                        children: [
                          if (_rows.isEmpty)
                            SizedBox(
                              height: 320,
                              child: StateMessage(
                                icon: Icons.inbox_outlined,
                                title: 'No ${_c.title.toLowerCase()}',
                                message: _filter.countAgainst(_defaults) > 0
                                    ? 'Nothing matches these filters. Change them with Filter.'
                                    : (_c.emptyHint ?? 'Nothing in the last 30 days, and nothing awaiting approval.'),
                              ),
                            ),
                          for (final r in _rows)
                            Padding(
                              padding: const EdgeInsets.fromLTRB(16, 0, 16, 10),
                              child: ListRowCard(
                                leading: InitialsAvatar(name: _team ? _employeeName(r['employee_id'] as String) : _c.singular),
                                title: _c.rowTitle(r, _team ? _employeeName(r['employee_id'] as String) : ''),
                                subtitle: _c.rowSubtitle?.call(r),
                                trailing: RequestStatusChip(status: r['status'] as String, labels: _c.statusLabels),
                                onTap: () async {
                                  await pushKeepingTheme<void>(context, (_) => RequestDetailScreen(config: _c, requestId: r['id'] as String, initial: r));
                                  _refreshRow(r['id'] as String);
                                },
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

/// One request: its sections, and — with the right permission and state — review (approve /
/// reject with a comment) and cancel. Mirrors the web `[id]` pages.
class RequestDetailScreen extends ConsumerStatefulWidget {
  const RequestDetailScreen({super.key, required this.config, required this.requestId, this.initial, this.reviewOnOpen});
  final RequestConfig config;
  final String requestId;
  final Rec? initial;

  /// Opens straight on the approve (true) or reject (false) step, and leaves when it is done.
  final bool? reviewOnOpen;

  @override
  ConsumerState<RequestDetailScreen> createState() => _RequestDetailScreenState();
}

class _RequestDetailScreenState extends ConsumerState<RequestDetailScreen> {
  Rec? _row;
  ApiError? _error;
  bool _loading = true;
  bool _busy = false;

  RequestConfig get _c => widget.config;
  ApiClient get _client => ref.read(apiClientProvider);
  String get _url => '${_c.path}/${widget.requestId}';

  @override
  void initState() {
    super.initState();
    _row = widget.initial;
    _load();
  }

  Future<void> _load() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final r = await _client.get<Rec>(_url, parse: (d) => d as Rec);
      if (mounted) setState(() => _row = r);
      _reviewOnce(r);
    } catch (e) {
      if (mounted) setState(() => _error = e is ApiError ? e : ApiError(status: 0, code: 'UNKNOWN_ERROR', message: 'Something went wrong.'));
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  void _toast(String m) => ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(m)));

  bool _reviewStarted = false;

  Future<void> _reviewOnce(Rec r) async {
    final approve = widget.reviewOnOpen;
    if (approve == null || _reviewStarted || !mounted) return;
    _reviewStarted = true;
    await _review(r, approve: approve);
    if (mounted) Navigator.of(context).pop();
  }

  Future<void> _review(Rec r, {required bool approve}) async {
    final updated = await showRequestReviewDialog(context, _client, _c, r, approve: approve);
    if (updated == null || !mounted) return;
    setState(() => _row = updated);
    _toast(approve ? '${_c.singular} approved.' : '${_c.singular} rejected.');
    _load();
  }

  Future<void> _cancel(Rec r) async {
    final yes = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: Text('${_c.cancelLabel}?'),
        content: const Text('The request is withdrawn.'),
        actions: [
          TextButton(onPressed: () => Navigator.of(ctx).pop(false), child: const Text('Keep it')),
          FilledButton(style: FilledButton.styleFrom(backgroundColor: Theme.of(ctx).colorScheme.error), onPressed: () => Navigator.of(ctx).pop(true), child: Text(_c.cancelLabel)),
        ],
      ),
    );
    if (yes != true) return;
    setState(() => _busy = true);
    try {
      final updated = await _client.post<Rec>('$_url/cancel', body: const {}, ifMatch: r['version'].toString(), parse: (d) => d as Rec);
      if (mounted) setState(() => _row = updated);
      _toast('Request cancelled.');
      _load();
    } catch (e) {
      _toast(e is ApiError ? describeApiError(e) : 'Something went wrong.');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final user = ref.watch(authControllerProvider).user;
    final perms = user?.permissions ?? const <String>[];
    final tz = user?.companyTimezone ?? 'Asia/Kolkata';
    final r = _row;
    Widget body;
    if (r == null && _loading) {
      body = const ListSkeleton(count: 3);
    } else if (r == null) {
      body = StateMessage(
        icon: _error?.status == 404 ? Icons.search_off_rounded : Icons.error_outline_rounded,
        tone: _error?.status == 404 ? Tone.neutral : Tone.danger,
        title: _error?.status == 404 ? 'Not found' : 'Something went wrong',
        message: _error?.status == 404 ? "This ${_c.singular.toLowerCase()} was not found, or you don't have access to it." : (_error?.message ?? 'Something went wrong.'),
        actionLabel: 'Retry',
        onAction: _load,
      );
    } else {
      final isOwn = user?.employeeId != null && r['employee_id'] == user!.employeeId;
      final canReview = perms.contains(_c.approvePermission) && _c.isPending(r) && !isOwn;
      final canCancel = user != null && (_c.canCancel?.call(r, user) ?? false);
      body = RefreshIndicator(
        onRefresh: _load,
        child: ListView(
          padding: const EdgeInsets.all(16),
          children: [
            HeroCard(
              child: Row(children: [
                Expanded(child: Text(_c.singular, style: const TextStyle(color: Colors.white, fontWeight: FontWeight.w800, fontSize: 19))),
                RequestStatusChip(status: r['status'] as String, labels: _c.statusLabels),
              ]),
            ),
            if (canReview || canCancel)
              Padding(
                padding: const EdgeInsets.only(top: 10),
                child: Wrap(spacing: 8, runSpacing: 8, children: [
                  if (canReview) FilledButton(onPressed: _busy ? null : () => _review(r, approve: true), child: const Text('Approve')),
                  if (canReview) OutlinedButton(onPressed: _busy ? null : () => _review(r, approve: false), child: const Text('Reject')),
                  if (canCancel) OutlinedButton(onPressed: _busy ? null : () => _cancel(r), child: Text(_c.cancelLabel)),
                ]),
              ),
            for (final s in _c.sections(r, tz))
              ui.DetailSection(
                title: s.title,
                children: [
                  for (final (k, v) in s.rows) KeyValueRow(k, v == '—' ? null : v),
                  for (final l in s.lines) Padding(padding: const EdgeInsets.symmetric(vertical: 3), child: Text(l)),
                ],
              ),
          ],
        ),
      );
    }
    return Scaffold(appBar: AppBar(title: Text(_c.singular)), body: body);
  }
}

/// `formatDateTime` for an optional ISO string.
String when(String? iso, String zone) => formatDateTime(iso, zone);

/// Approve or reject request [r] of kind [c] in a dialog; resolves to the updated record, or null
/// when the approver backed out.
///
/// One text field (audit MOB-UX-015): when approving, an optional comment (required only when the
/// approved overtime minutes are changed); when rejecting, a required reason. Both are shown to
/// the employee. Used by the detail screen and straight from the decision-centre cards (MOB-UX-014).
Future<Rec?> showRequestReviewDialog(BuildContext context, ApiClient client, RequestConfig c, Rec r, {required bool approve}) async {
  final url = '${c.path}/${r['id']}';
  final note = TextEditingController();
  final maxMinutes = approve ? c.editableMinutes?.call(r) : null;
  final minutes = TextEditingController(text: maxMinutes?.toString() ?? '');
  String? formError;
  Rec? updated;
  final ok = await showDialog<bool>(
    context: context,
    builder: (ctx) => StatefulBuilder(
      builder: (ctx, setLocal) => AlertDialog(
        title: Text('${approve ? 'Approve' : 'Reject'} ${c.singular.toLowerCase()}'),
        content: SingleChildScrollView(
          child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.start, children: [
            if (maxMinutes != null) ...[
              AuthFormField(
                label: 'Minutes to approve',
                description: '$maxMinutes detected. You can approve fewer, not more.',
                child: TextField(controller: minutes, keyboardType: TextInputType.number),
              ),
              const SizedBox(height: 12),
            ],
            AuthFormField(
              label: approve ? 'Comment' : 'Reason',
              required: !approve,
              description: approve
                  ? (maxMinutes != null ? 'Required if you change the minutes. Shown to the employee.' : 'Optional. Shown to the employee.')
                  : 'Shown to the employee.',
              child: TextField(controller: note, minLines: 2, maxLines: 4, textCapitalization: TextCapitalization.sentences),
            ),
            if (formError != null) Padding(padding: const EdgeInsets.only(top: 12), child: Text(formError!, style: TextStyle(color: Theme.of(ctx).colorScheme.error))),
          ]),
        ),
        actions: [
          TextButton(onPressed: () => Navigator.of(ctx).pop(false), child: const Text('Cancel')),
          FilledButton(
            style: approve ? null : FilledButton.styleFrom(backgroundColor: Theme.of(ctx).colorScheme.error),
            onPressed: () async {
              final text = note.text.trim();
              final entered = int.tryParse(minutes.text.trim());
              final minutesChanged = maxMinutes != null && entered != maxMinutes;
              if (!approve && text.isEmpty) {
                setLocal(() => formError = 'Give the employee a reason.');
                return;
              }
              if (minutesChanged && (entered == null || entered < 1 || entered > maxMinutes)) {
                setLocal(() => formError = 'Enter whole minutes from 1 to $maxMinutes. To pay nothing, reject instead.');
                return;
              }
              if (minutesChanged && text.isEmpty) {
                setLocal(() => formError = 'Add a comment explaining why the minutes were changed.');
                return;
              }
              try {
                updated = await client.post<Rec>(
                  '$url/${approve ? 'approve' : 'reject'}',
                  body: {
                    if (approve && text.isNotEmpty) 'reviewer_comment': text,
                    if (minutesChanged) 'minutes_approved': entered,
                    if (!approve) 'rejection_reason': text,
                  },
                  ifMatch: r['version'].toString(),
                  parse: (d) => d as Rec,
                );
                if (ctx.mounted) Navigator.of(ctx).pop(true);
              } on ApiError catch (e) {
                setLocal(() => formError = e.status == 403
                    ? (e.code == c.selfApprovalCode
                        ? 'You cannot approve or reject your own ${c.singular.toLowerCase()}.'
                        : e.code == c.approverMismatchCode
                            ? "You are not the resolved approver for this ${c.singular.toLowerCase()}'s current stage."
                            : describeApiError(e))
                    : e.status == 409
                        ? 'This ${c.singular.toLowerCase()} has already moved on (decided or cancelled by someone else). Refresh to see its current state.'
                        : describeApiError(e));
              } catch (_) {
                setLocal(() => formError = 'Something went wrong.');
              }
            },
            child: Text(approve ? 'Approve' : 'Reject'),
          ),
        ],
      ),
    ),
  );
  // Not disposed here: the dialog is still animating out and its fields still use them.
  return ok == true ? updated : null;
}
