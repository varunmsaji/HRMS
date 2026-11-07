import 'dart:async';

import 'package:flutter/material.dart';
import '../../../core/widgets/ui.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api/api_error.dart';
import '../../../core/auth/permissions.dart';
import '../../../core/forms/spec_form_screen.dart';
import '../../attendance/presentation/employee_attendance_panel.dart';
import '../../auth/state/auth_controller.dart';
import '../../payroll/presentation/employee_salary_panel.dart';
import '../../../core/nav/nav_entries.dart' show kPayrollInRelease;
import '../../profile/presentation/employee_documents_panel.dart';
import '../../profile/data/employee_repository.dart';
import '../../profile/presentation/employee_overview.dart';
import '../../profile/presentation/employee_record_sections.dart';
import '../../profile/presentation/profile_screen.dart' show employeeRepositoryProvider;
import '../../../core/export/csv_export.dart';
import '../../../core/widgets/dashboard_kit.dart';
import '../domain/employee_directory.dart';
import '../domain/employee_forms.dart';

/// Employee directory — mirrors `apps/web/src/app/app/employees/page.tsx`.
class EmployeesScreen extends ConsumerStatefulWidget {
  const EmployeesScreen({super.key});

  @override
  ConsumerState<EmployeesScreen> createState() => _EmployeesScreenState();
}

class _EmployeesScreenState extends ConsumerState<EmployeesScreen> {
  final _search = TextEditingController();
  Timer? _debounce;
  List<Employee> _items = const [];
  bool _hasNext = false;
  bool _loading = true;
  bool _loadingMore = false;
  bool _exporting = false;
  ApiError? _error;
  int _page = 1;
  int _request = 0;

  /// Headline counts; null until loaded (and stays null if the summary fails, as on web).
  DirectorySummary? _summary;

  /// Designation, department, manager and shift for the loaded rows, by employee id.
  final Map<String, DirectoryRow> _details = {};

  /// Web's two dropdowns: employment status, and active/inactive record state.
  String? _status;
  RecordState _state = RecordState.all;

  EmployeeRepository get _repo => ref.read(employeeRepositoryProvider);

  @override
  void initState() {
    super.initState();
    _load();
    _loadSummary();
  }

  @override
  void dispose() {
    _debounce?.cancel();
    _search.dispose();
    super.dispose();
  }

  Future<void> _loadSummary() async {
    try {
      final summary = await _repo.directorySummary();
      if (mounted) setState(() => _summary = summary);
    } catch (_) {
      // The cards are extra context; the directory works without them (as on web).
    }
  }

  /// Fetches directory details for [rows] not already known. A failure leaves the subtitle at the
  /// employee code, as web leaves those cells blank.
  Future<void> _loadDetails(List<Employee> rows) async {
    final missing = [
      for (final e in rows)
        if (!_details.containsKey(e.id)) e.id,
    ];
    if (missing.isEmpty) return;
    try {
      final found = await _repo.directoryRows(missing);
      if (mounted) setState(() => _details.addAll(found));
    } catch (_) {}
  }

  /// Loads page 1 for the current search; a slower, older answer never overwrites a newer one.
  Future<void> _load() async {
    final mine = ++_request;
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final page = await _repo.listEmployeesPage(search: _search.text);
      if (!mounted || mine != _request) return;
      setState(() {
        _items = page.rows;
        _hasNext = page.hasNext;
        _page = 1;
      });
      unawaited(_loadDetails(page.rows));
    } catch (e) {
      if (!mounted || mine != _request) return;
      setState(() => _error = e is ApiError ? e : ApiError(status: 0, code: 'UNKNOWN_ERROR', message: 'Something went wrong.'));
    } finally {
      if (mounted && mine == _request) setState(() => _loading = false);
    }
  }

  Future<void> _loadMore() async {
    if (_loadingMore || !_hasNext) return;
    final mine = _request;
    setState(() => _loadingMore = true);
    try {
      final page = await _repo.listEmployeesPage(search: _search.text, page: _page + 1);
      if (!mounted || mine != _request) return;
      setState(() {
        _items = [..._items, ...page.rows];
        _hasNext = page.hasNext;
        _page += 1;
      });
      unawaited(_loadDetails(page.rows));
    } catch (e) {
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(e is ApiError ? e.message : 'Something went wrong.')));
    } finally {
      if (mounted) setState(() => _loadingMore = false);
    }
  }

  void _onSearchChanged(String _) {
    _debounce?.cancel();
    _debounce = Timer(const Duration(milliseconds: 350), _load);
  }

  List<Employee> get _shown => filterEmployees(_items, status: _status, state: _state);

  bool get _filtered => _status != null || _state != RecordState.all;

  /// Shares the rows on screen as `employees.csv`, with web's columns.
  Future<void> _export() async {
    final rows = _shown;
    setState(() => _exporting = true);
    try {
      await _loadDetails(rows);
      await ref.read(csvSharerProvider)('employees.csv', employeesCsv(rows, _details));
    } catch (_) {
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Could not export the list. Try again.')));
    } finally {
      if (mounted) setState(() => _exporting = false);
    }
  }

  Future<void> _create() async {
    final repo = _repo;
    final saved = await openSpecForm(
      context,
      title: 'New employee',
      spec: employeeSpec,
      onSubmit:
          (payload, _) async => repo.createEmployee({
            for (final e in payload.entries)
              if (e.value != null) e.key: e.value,
          }),
    );
    if (saved) {
      _load();
      _loadSummary();
    }
  }

  String _subtitle(Employee e) {
    final d = _details[e.id];
    return [e.employeeCode, d?.designation, d?.department].whereType<String>().where((p) => p.isNotEmpty).join(' · ');
  }

  Widget _header(BuildContext context) {
    final statuses = {for (final e in _items) e.status}.where((s) => s.isNotEmpty).toList()..sort();
    final summary = _summary;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        if (summary != null) ...[
          _TilePairs(
            tiles: [
              StatTile(icon: Icons.groups_outlined, label: 'Total employees', value: '${summary.total}', hint: '${summary.active} active', accent: toneColors(context, Tone.accent).fg),
              StatTile(icon: Icons.schedule_outlined, label: 'On probation', value: '${summary.onProbation}', accent: toneColors(context, Tone.warning).fg),
              StatTile(icon: Icons.logout_rounded, label: 'On notice', value: '${summary.onNotice}', accent: toneColors(context, Tone.info).fg),
              StatTile(
                icon: Icons.account_tree_outlined,
                label: 'Departments',
                value: '${summary.departmentCount}',
                hint: summary.departmentNames.isEmpty ? null : summary.departmentNames.join(', '),
                accent: toneColors(context, Tone.neutral).fg,
              ),
            ],
          ),
          const SizedBox(height: 14),
        ],
        Wrap(
          spacing: 8,
          runSpacing: 8,
          crossAxisAlignment: WrapCrossAlignment.center,
          children: [
            // As on web, the status filter appears only when the loaded rows have more than one status.
            if (statuses.length > 1)
              _FilterMenu<String?>(
                semanticLabel: 'Filter by employment status',
                value: _status,
                options: {null: 'All statuses', for (final s in statuses) s: s.replaceAll('_', ' ')},
                onChanged: (v) => setState(() => _status = v),
              ),
            _FilterMenu<RecordState>(
              semanticLabel: 'Filter by record state',
              value: _state,
              options: const {RecordState.all: 'All states', RecordState.active: 'Active only', RecordState.inactive: 'Inactive only'},
              onChanged: (v) => setState(() => _state = v),
            ),
            if (_filtered)
              TextButton.icon(
                onPressed:
                    () => setState(() {
                      _status = null;
                      _state = RecordState.all;
                    }),
                icon: const Icon(Icons.close_rounded, size: 16),
                label: const Text('Clear'),
              ),
          ],
        ),
        if (_filtered && _hasNext)
          Padding(
            padding: const EdgeInsets.only(top: 6),
            child: Text(
              'Filters apply to the ${_items.length} employees loaded so far.',
              style: Theme.of(context).textTheme.bodySmall?.copyWith(color: Theme.of(context).colorScheme.onSurfaceVariant),
            ),
          ),
        const SizedBox(height: 4),
      ],
    );
  }

  @override
  Widget build(BuildContext context) {
    final canCreate = (ref.watch(authControllerProvider).user?.permissions ?? const <String>[]).contains(employeeCreate);
    final searching = _search.text.trim().isNotEmpty;
    final shown = _shown;
    Widget body;
    if (_loading && _items.isEmpty) {
      body = const ListSkeleton();
    } else if (_error != null) {
      final forbidden = _error!.status == 403;
      body = StateMessage(
        icon: forbidden ? Icons.lock_outline_rounded : Icons.cloud_off_rounded,
        tone: forbidden ? Tone.warning : Tone.danger,
        title: forbidden ? 'No access' : 'Couldn\'t load this',
        message: forbidden ? 'You do not have permission to view this.' : _error!.message,
        actionLabel: forbidden ? null : 'Try again',
        onAction: _load,
      );
    } else if (_items.isEmpty) {
      body = StateMessage(
        icon: searching ? Icons.search_off_rounded : Icons.inbox_outlined,
        title: searching ? 'No matches' : 'No employees yet.',
        message: searching ? 'Nothing matches "${_search.text.trim()}".' : (canCreate ? 'Tap "New employee" to add the first one.' : null),
      );
    } else {
      // Item 0 is the summary and filters; then the rows; then "Load more" when there is a next page.
      final rowCount = shown.isEmpty ? 1 : shown.length;
      body = ListView.separated(
        padding: const EdgeInsets.fromLTRB(16, 4, 16, 96),
        itemCount: 1 + rowCount + (_hasNext ? 1 : 0),
        separatorBuilder: (_, __) => const SizedBox(height: 10),
        itemBuilder: (context, index) {
          if (index == 0) return _header(context);
          if (index == rowCount + 1) {
            return Center(child: _loadingMore ? const Padding(padding: EdgeInsets.all(12), child: CircularProgressIndicator()) : TextButton(onPressed: _loadMore, child: const Text('Load more')));
          }
          if (shown.isEmpty) {
            return const Padding(padding: EdgeInsets.symmetric(vertical: 24), child: Text('No employees match these filters.', textAlign: TextAlign.center));
          }
          final employee = shown[index - 1];
          final name = employeeDisplayName(employee);
          return ListRowCard(
            title: name,
            subtitle: _subtitle(employee),
            leading: InitialsAvatar(name: name),
            trailing: employee.isActive ? StatusChip.status(employee.status) : const StatusChip(label: 'Inactive'),
            onTap: () async {
              await Navigator.of(context).push(MaterialPageRoute(builder: (_) => EmployeeDetailScreen(employee: employee)));
              _load();
              _loadSummary();
            },
          );
        },
      );
    }
    return Scaffold(
      appBar: AppBar(
        title: const Text('Employees'),
        actions: [
          if (_items.isNotEmpty && _error == null)
            IconButton(
              tooltip: 'Export CSV',
              onPressed: _exporting || shown.isEmpty ? null : _export,
              icon: _exporting ? const SizedBox(width: 20, height: 20, child: CircularProgressIndicator(strokeWidth: 2)) : const Icon(Icons.file_download_outlined),
            ),
        ],
      ),
      body: Column(
        children: [
          Padding(padding: const EdgeInsets.fromLTRB(16, 4, 16, 10), child: AppSearchField(hint: 'Search name, code, email or mobile', controller: _search, onChanged: _onSearchChanged)),
          Expanded(
            child: RefreshIndicator(
              onRefresh: () async {
                await Future.wait([_load(), _loadSummary()]);
              },
              child: body,
            ),
          ),
        ],
      ),
      floatingActionButton: canCreate ? FloatingActionButton.extended(onPressed: _create, icon: const Icon(Icons.add_rounded), label: const Text('New employee')) : null,
    );
  }
}

/// [StatTile]s two to a row, without [StatGrid]'s page gutter (the list already has one).
class _TilePairs extends StatelessWidget {
  const _TilePairs({required this.tiles});
  final List<StatTile> tiles;

  @override
  Widget build(BuildContext context) => Column(
    children: [
      for (var i = 0; i < tiles.length; i += 2) ...[
        if (i > 0) const SizedBox(height: 12),
        IntrinsicHeight(
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [Expanded(child: tiles[i]), const SizedBox(width: 12), Expanded(child: i + 1 < tiles.length ? tiles[i + 1] : const SizedBox.shrink())],
          ),
        ),
      ],
    ],
  );
}

/// A compact dropdown chip ("All statuses ▾") for one list filter.
class _FilterMenu<T> extends StatelessWidget {
  const _FilterMenu({required this.semanticLabel, required this.value, required this.options, required this.onChanged});

  final String semanticLabel;
  final T value;
  final Map<T, String> options;
  final ValueChanged<T> onChanged;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    return Semantics(
      label: semanticLabel,
      button: true,
      child: PopupMenuButton<T>(
        tooltip: semanticLabel,
        initialValue: value,
        onSelected: onChanged,
        itemBuilder: (_) => [for (final o in options.entries) PopupMenuItem<T>(value: o.key, child: Text(o.value))],
        child: Container(
          padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
          decoration: BoxDecoration(border: Border.all(color: scheme.outlineVariant), borderRadius: BorderRadius.circular(20)),
          child: Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              Text(options[value] ?? '', style: Theme.of(context).textTheme.labelLarge),
              const SizedBox(width: 4),
              Icon(Icons.arrow_drop_down_rounded, size: 20, color: scheme.onSurfaceVariant),
            ],
          ),
        ),
      ),
    );
  }
}

/// One employee — mirrors `apps/web/src/app/app/employees/[id]/page.tsx`: Overview (with edit,
/// deactivate/reactivate, confirm probation and invite) plus a tab per record section the viewer
/// may see.
class EmployeeDetailScreen extends ConsumerStatefulWidget {
  const EmployeeDetailScreen({super.key, required this.employee});
  final Employee employee;

  @override
  ConsumerState<EmployeeDetailScreen> createState() => _EmployeeDetailScreenState();
}

class _EmployeeDetailScreenState extends ConsumerState<EmployeeDetailScreen> {
  late Employee _employee = widget.employee;
  bool _busy = false;

  EmployeeRepository get _repo => ref.read(employeeRepositoryProvider);

  void _toast(String m) => ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(m)));

  String _explain(Object e) {
    if (e is ApiError) {
      if (e.code == 'STALE_RESOURCE') return 'This employee record was changed by someone else. Reload and try again.';
      if (e.status == 403) return "You don't have permission to do that.";
      return e.message;
    }
    return 'Something went wrong.';
  }

  Future<void> _reload() async {
    try {
      final latest = await _repo.getEmployee(_employee.id);
      if (mounted) setState(() => _employee = latest);
    } catch (_) {}
  }

  Future<void> _edit() async {
    final saved = await openSpecForm(
      context,
      title: 'Edit employee',
      spec: employeeSpec,
      initial: _employee.raw,
      onSubmit: (payload, changed) async {
        final updated = await _repo.updateEmployee(_employee.id, changed, version: _employee.version);
        if (mounted) setState(() => _employee = updated);
      },
    );
    if (saved && mounted) _toast('Employee saved.');
  }

  Future<void> _run(Future<Employee> Function() call, String done) async {
    setState(() => _busy = true);
    try {
      final updated = await call();
      if (mounted) setState(() => _employee = updated);
      _toast(done);
    } catch (e) {
      _toast(_explain(e));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _toggleActive() async {
    final deactivating = _employee.isActive;
    final yes = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: Text(deactivating ? 'Deactivate employee?' : 'Reactivate employee?'),
        content: Text(deactivating ? 'They will no longer appear as an active employee.' : 'They will become an active employee again.'),
        actions: [
          TextButton(onPressed: () => Navigator.of(ctx).pop(false), child: const Text('Cancel')),
          FilledButton(onPressed: () => Navigator.of(ctx).pop(true), child: Text(deactivating ? 'Deactivate' : 'Reactivate')),
        ],
      ),
    );
    if (yes != true) return;
    await _run(
      () => deactivating
          ? _repo.deactivateEmployee(_employee.id, version: _employee.version)
          : _repo.updateEmployee(_employee.id, {'is_active': true}, version: _employee.version),
      deactivating ? 'Employee deactivated.' : 'Employee reactivated.',
    );
  }

  Future<void> _confirmProbation() async {
    final yes = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Confirm employee?'),
        content: const Text('Ends probation — the employee becomes a confirmed, active employee.'),
        actions: [
          TextButton(onPressed: () => Navigator.of(ctx).pop(false), child: const Text('Cancel')),
          FilledButton(onPressed: () => Navigator.of(ctx).pop(true), child: const Text('Confirm')),
        ],
      ),
    );
    if (yes != true) return;
    await _run(() => _repo.confirmEmployee(_employee.id, version: _employee.version), 'Employee confirmed.');
  }

  Future<void> _invite() async {
    setState(() => _busy = true);
    try {
      final r = await _repo.inviteEmployee(_employee.id);
      _toast(r.emailSent ? 'Invite sent to ${r.email}.' : 'Invite created for ${r.email}, but the email could not be delivered — share the link manually.');
    } on ApiError catch (e) {
      _toast(e.status == 409
          ? 'This employee already has a login account.'
          : e.status == 422
              ? "Can't invite this employee — add a personal email to their profile first."
              : e.message);
    } catch (_) {
      _toast('Something went wrong.');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final permissions = ref.watch(authControllerProvider).user?.permissions ?? const <String>[];
    final sections = [
      for (final s in employeeRecordSections)
        if (s.permission == null || permissions.contains(s.permission)) s,
    ];
    final e = _employee;
    // The web page's Salary and Attendance tabs, after the record sections.
    final extraTabs = <(String, Widget)>[
      if (kPayrollInRelease && permissions.contains(employeeViewCompensation)) ('Salary', EmployeeSalaryPanel(employeeId: e.id)),
      ('Documents', EmployeeDocumentsPanel(employeeId: e.id)),
      if (permissions.contains(attendanceView)) ('Attendance', EmployeeAttendancePanel(employeeId: e.id, employeeLabel: e.fullName.isEmpty ? e.employeeCode : e.fullName)),
    ];
    final actions = <Widget>[
      if (permissions.contains(employeeUpdate)) FilledButton.icon(icon: const Icon(Icons.edit_outlined), label: const Text('Edit'), onPressed: _busy ? null : _edit),
      if (permissions.contains(employeeConfirm) && e.status == 'PROBATION') OutlinedButton(onPressed: _busy ? null : _confirmProbation, child: const Text('Confirm')),
      if (permissions.contains(employeeInvite)) OutlinedButton(onPressed: _busy ? null : _invite, child: const Text('Invite')),
      if (permissions.contains(employeeDeactivate)) OutlinedButton(onPressed: _busy ? null : _toggleActive, child: Text(e.isActive ? 'Deactivate' : 'Reactivate')),
    ];
    return DefaultTabController(
      length: sections.length + extraTabs.length + 1,
      child: Scaffold(
        appBar: AppBar(
          title: Text(e.fullName.isEmpty ? e.employeeCode : e.fullName),
          bottom: TabBar(
            isScrollable: true,
            tabAlignment: TabAlignment.start,
            tabs: [const Tab(text: 'Overview'), for (final s in sections) Tab(text: s.title), for (final x in extraTabs) Tab(text: x.$1)],
          ),
        ),
        body: TabBarView(
          children: [
            RefreshIndicator(onRefresh: _reload, child: EmployeeOverview(employee: e, actions: actions)),
            for (final s in sections) EmployeeRecordPanel(employeeId: e.id, section: s),
            for (final x in extraTabs) x.$2,
          ],
        ),
      ),
    );
  }
}
