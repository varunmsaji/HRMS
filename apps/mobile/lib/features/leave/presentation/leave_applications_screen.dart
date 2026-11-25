import 'package:flutter/material.dart';
import '../../../core/widgets/ui.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api/api_error.dart';
import '../../../core/auth/permissions.dart';
import '../../../core/forms/choice_sources.dart';
import '../../../core/forms/form_spec.dart';
import '../../../core/forms/spec_form_screen.dart';
import '../../../core/format.dart';
import '../../../core/providers.dart';
import '../../../core/widgets/employee/leave_balance_strip.dart';
import '../../../core/widgets/list_filter.dart';
import 'package:go_router/go_router.dart';
import '../../auth/state/auth_controller.dart';
import '../../shell/more_action.dart';
import '../data/leave_repository.dart';
import '../domain/leave_application_form.dart';
import 'leave_application_detail_screen.dart';
import 'leave_apply_screen.dart';
import '../../../core/theme/employee_theme_scope.dart';
import '../../../core/diagnostics/app_diagnostics.dart';

/// Leave applications — mirrors `apps/web/src/app/app/leave-applications/page.tsx`. "Mine" and
/// "Team" are two filters over the same permission-scoped read: the server only returns what the
/// caller may see. Filter by date range, status and (for the team) employee.
class LeaveApplicationsScreen extends ConsumerStatefulWidget {
  const LeaveApplicationsScreen({super.key, this.decisionCenter});

  /// The approver's screen, offered beside Mine and Team when given.
  final Widget? decisionCenter;

  @override
  ConsumerState<LeaveApplicationsScreen> createState() => _LeaveApplicationsScreenState();
}

class _LeaveApplicationsScreenState extends ConsumerState<LeaveApplicationsScreen> {
  late bool _team;
  ListFilter _filter = const ListFilter();
  String get _status => _filter.group('status');
  String get _employee => _filter.employee;
  bool _loading = true;
  bool _loadingMore = false;
  ApiError? _error;
  List<LeaveApplication> _rows = const [];
  int _page = 1;
  bool _hasMore = false;
  bool _moreFailed = false;
  bool _decisions = false;
  int _decisionsKey = 0;
  List<Choice> _employees = const [];
  Map<String, String> _typeNames = const {};

  /// The signed-in employee's balances, shown above "Mine" (audit MOB-UX-011); null until read,
  /// and left null when they cannot be read (the list still works).
  List<LeaveBalance>? _balances;

  String? get _myEmployeeId => ref.read(authControllerProvider).user?.employeeId;

  List<String> get _permissions => ref.read(authControllerProvider).user?.permissions ?? const <String>[];

  @override
  void initState() {
    super.initState();
    // The company account has no employee record, so "Mine" would mean nothing: it starts on Team.
    _team = _permissions.contains(leaveApplicationApprove) || _myEmployeeId == null;
    // An approver starts on what is waiting for them, as on the web.
    _decisions = widget.decisionCenter != null && _permissions.contains(leaveApplicationApprove);
    _loadLookups();
    _loadBalances();
    if (!_decisions) _load();
  }

  Future<void> _loadBalances() async {
    final id = _myEmployeeId;
    if (id == null || !_permissions.contains(leaveBalanceView)) return;
    try {
      final balances = await ref.read(leaveRepositoryProvider).listLeaveBalances(id);
      if (mounted) setState(() => _balances = balances);
    } catch (e, s) { AppDiagnostics.instance.recordHandled(e, s); }
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
    } catch (e, s) { AppDiagnostics.instance.recordHandled(e, s); }
  }

  Future<ListEnvelopeLike> _fetch(int page) async {
    final myEmployeeId = ref.read(authControllerProvider).user?.employeeId;
    final env = await ref.read(leaveRepositoryProvider).listLeaveApplicationsPage(
          employeeId: _team ? (_employee.isEmpty ? null : _employee) : myEmployeeId,
          dateFrom: _filter.from,
          dateTo: _filter.to,
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
    setState(() {
      _loadingMore = true;
      _moreFailed = false;
    });
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
      // Said at the end of the list, with a retry (audit MOB-UX-036).
      if (mounted) setState(() => _moreFailed = true);
    } finally {
      if (mounted) setState(() => _loadingMore = false);
    }
  }

  Future<void> _apply() async {
    final saved = await openLeaveApplicationForm(context, ref, onBehalf: _team || _decisions);
    if (saved && mounted) {
      _loadBalances();
      ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Leave application submitted.')));
      setState(() => _decisionsKey++);
      _load();
    }
  }

  static final _statusGroup = FilterGroup(key: 'status', label: 'Status', options: [for (final st in leaveApplicationStatuses) (st, leaveApplicationStatusLabels[st] ?? st)]);

  Future<void> _openFilter() async {
    final next = await showListFilterSheet(context, initial: _filter, defaults: const ListFilter(), groups: [_statusGroup], employees: _team ? _employees : null);
    if (next == null || next == _filter || !mounted) return;
    setState(() => _filter = next);
    _load();
  }

  String _filterSummary() => [
        describeDates(_filter.from, _filter.to),
        _status.isEmpty ? 'All statuses' : (leaveApplicationStatusLabels[_status] ?? _status),
        if (_team && _employee.isNotEmpty) _employeeName(_employee),
      ].join(' · ');

  /// Back from a request: re-reads only that one and updates it where it is, keeping the loaded
  /// pages and the scroll position (audit MOB-UX-010). Balances may have moved too.
  Future<void> _refreshRow(String id) async {
    _loadBalances();
    try {
      final fresh = await ref.read(leaveRepositoryProvider).getLeaveApplication(id);
      if (mounted) setState(() => _rows = [for (final r in _rows) r.id == id ? fresh : r]);
    } catch (e, s) {
      // Keep the row as it was; pull to refresh reloads everything.
      AppDiagnostics.instance.recordHandled(e, s);
    }
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
    final notMine = _team || _decisions;
    final canCreate = notMine ? permissions.contains(leaveApplicationSubmitOnBehalf) : permissions.contains(leaveApplicationSubmit);
    final scopes = [
      if (_myEmployeeId != null) const ButtonSegment(value: 'mine', label: Text('Mine')),
      if (widget.decisionCenter != null && canApprove) const ButtonSegment(value: 'decisions', label: Text('Decisions')),
      if (canApprove || permissions.contains(leaveApplicationSubmitOnBehalf)) const ButtonSegment(value: 'team', label: Text('Team')),
    ];
    return Scaffold(
      appBar: AppBar(title: const Text('Leave'), automaticallyImplyLeading: false, actions: const [MoreAction()]),
      floatingActionButton: canCreate ? FloatingActionButton.extended(onPressed: _apply, icon: const Icon(Icons.add_rounded), label: Text(notMine ? 'Apply on behalf' : 'Apply for leave')) : null,
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
            const SizedBox(height: 10),
            if (!_decisions && !_team && (_balances?.isNotEmpty ?? false)) ...[
              LeaveBalanceStrip(
                items: [for (final b in _balances!) LeaveBalanceItem(name: b.leaveTypeName, balance: formatLeaveDays(b.balance), reserved: b.reservedBalance == 0 ? null : formatLeaveDays(b.reservedBalance))],
                onAll: () => context.push('/app/leave-balances'),
              ),
              const SizedBox(height: 10),
            ],
            if (!_decisions)
              ListFilterBar(summary: _filterSummary(), activeCount: _filter.countAgainst(const ListFilter()), onTap: _openFilter),
          ]),
        ),
        Expanded(
          child: _decisions
              ? KeyedSubtree(key: ValueKey(_decisionsKey), child: widget.decisionCenter!)
              : _loading
              ? const ListSkeleton(count: 5)
              : _error != null
                  ? StateMessage(icon: Icons.cloud_off_rounded, tone: Tone.danger, title: 'Couldn\'t load leave', message: describeApiError(_error!), actionLabel: 'Try again', onAction: _load)
                  : RefreshIndicator(
                      onRefresh: _load,
                      child: ListView(
                        padding: const EdgeInsets.fromLTRB(16, 12, 16, 96),
                        children: [
                          if (_rows.isEmpty)
                            SizedBox(
                              height: MediaQuery.sizeOf(context).height * 0.4,
                              child: StateMessage(
                                icon: Icons.beach_access_outlined,
                                title: 'No leave applications',
                                // Says what would appear here and how to make it appear (MOB-UX-044).
                                message: _filter.countAgainst(const ListFilter()) > 0
                                    ? 'Nothing matches these filters. Change them with Filter.'
                                    : _team
                                        ? 'Your team\'s leave applications will appear here.'
                                        : 'Your leave applications will appear here. Apply with the button below.',
                              ),
                            ),
                          for (final a in _rows)
                            Padding(
                              padding: const EdgeInsets.only(bottom: 10),
                              child: ListRowCard(
                                title: _title(a),
                                subtitle: '${formatDateRange(a.startDate, a.endDate)}${a.totalDays != null ? ' · ${formatDayCount(a.totalDays!)}' : ''}',
                                leading: IconBadge(icon: _iconFor(a.status), tone: toneForRequestStatus(a.status)),
                                trailing: _StatusChip(status: a.status),
                                onTap: () async {
                                  await pushKeepingTheme<void>(context, (_) => LeaveApplicationDetailScreen(applicationId: a.id, initial: a));
                                  _refreshRow(a.id);
                                },
                              ),
                            ),
                          if (_hasMore)
                            Center(
                              child: _moreFailed
                                  ? TextButton.icon(onPressed: _more, icon: const Icon(Icons.refresh_rounded), label: const Text('Couldn\'t load more · Try again'))
                                  : TextButton(onPressed: _loadingMore ? null : _more, child: Text(_loadingMore ? 'Loading…' : 'Load more')),
                            ),
                        ],
                      ),
                    ),
        ),
      ]),
    );
  }
}

/// Opens the apply-for-leave form ([onBehalf] adds the employee picker). Resolves to true once a
/// request was submitted. Shared by the Leave tab and Home's "Apply Leave" shortcut, which opens
/// the form directly rather than the list (MOB-UX-007).
///
/// Self-service opens the dedicated [LeaveApplyScreen] (balances on the type chips, one date-range
/// picker, a day summary). Applying on behalf keeps the generic form with its employee picker.
Future<bool> openLeaveApplicationForm(BuildContext context, WidgetRef ref, {bool onBehalf = false}) async {
  if (!onBehalf) return (await pushKeepingTheme<bool>(context, (_) => const LeaveApplyScreen())) == true;
  final client = ref.read(apiClientProvider);
  return openSpecForm(
    context,
    title: onBehalf ? 'Apply on behalf' : 'Apply for leave',
    spec: leaveApplicationSpec(onBehalf: onBehalf),
    submitLabel: 'Submit request',
    loadChoices: () => loadChoices(client, [if (onBehalf) 'employees', 'leave_types']),
    onSubmit: (payload, _) async => ref.read(leaveRepositoryProvider).submitLeaveApplication(payload),
  );
}

IconData _iconFor(String status) => switch (status) {
      'APPROVED' => Icons.check_circle_outline_rounded,
      'REJECTED' => Icons.cancel_outlined,
      'CANCELLED' => Icons.block_rounded,
      _ => Icons.hourglass_top_rounded,
    };

typedef ListEnvelopeLike = ({List<LeaveApplication> rows, bool hasNext});

class _StatusChip extends StatelessWidget {
  const _StatusChip({required this.status});
  final String status;

  @override
  Widget build(BuildContext context) =>
      StatusChip.request(status);
}

/// Shared with the detail screen.
class LeaveStatusChip extends StatelessWidget {
  const LeaveStatusChip({super.key, required this.status});
  final String status;

  @override
  Widget build(BuildContext context) => _StatusChip(status: status);
}
