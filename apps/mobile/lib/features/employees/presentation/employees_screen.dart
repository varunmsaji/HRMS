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
import '../../profile/presentation/employee_documents_panel.dart';
import '../../profile/data/employee_repository.dart';
import '../../profile/presentation/employee_overview.dart';
import '../../profile/presentation/employee_record_sections.dart';
import '../../profile/presentation/profile_screen.dart' show employeeRepositoryProvider;
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
  ApiError? _error;
  int _page = 1;
  int _request = 0;

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void dispose() {
    _debounce?.cancel();
    _search.dispose();
    super.dispose();
  }

  /// Loads page 1 for the current search; a slower, older answer never overwrites a newer one.
  Future<void> _load() async {
    final mine = ++_request;
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final page = await ref.read(employeeRepositoryProvider).listEmployeesPage(search: _search.text);
      if (!mounted || mine != _request) return;
      setState(() {
        _items = page.rows;
        _hasNext = page.hasNext;
        _page = 1;
      });
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
      final page = await ref.read(employeeRepositoryProvider).listEmployeesPage(search: _search.text, page: _page + 1);
      if (!mounted || mine != _request) return;
      setState(() {
        _items = [..._items, ...page.rows];
        _hasNext = page.hasNext;
        _page += 1;
      });
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

  Future<void> _create() async {
    final repo = ref.read(employeeRepositoryProvider);
    final saved = await openSpecForm(
      context,
      title: 'New employee',
      spec: employeeSpec,
      onSubmit: (payload, _) async => repo.createEmployee({
        for (final e in payload.entries)
          if (e.value != null) e.key: e.value,
      }),
    );
    if (saved) _load();
  }

  @override
  Widget build(BuildContext context) {
    final canCreate = (ref.watch(authControllerProvider).user?.permissions ?? const <String>[]).contains(employeeCreate);
    final searching = _search.text.trim().isNotEmpty;
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
      body = ListView.separated(
        padding: const EdgeInsets.fromLTRB(16, 4, 16, 96),
        itemCount: _items.length + (_hasNext ? 1 : 0),
        separatorBuilder: (_, __) => const SizedBox(height: 10),
        itemBuilder: (context, index) {
          if (index == _items.length) {
            return Center(
              child: _loadingMore ? const Padding(padding: EdgeInsets.all(12), child: CircularProgressIndicator()) : TextButton(onPressed: _loadMore, child: const Text('Load more')),
            );
          }
          final employee = _items[index];
          final name = employee.fullName.isEmpty ? employee.employeeCode : employee.fullName;
          return ListRowCard(
            title: name,
            subtitle: employee.employeeCode,
            leading: InitialsAvatar(name: name),
            trailing: employee.isActive ? StatusChip.status(employee.status) : const StatusChip(label: 'Inactive'),
            onTap: () async {
              await Navigator.of(context).push(MaterialPageRoute(builder: (_) => EmployeeDetailScreen(employee: employee)));
              _load();
            },
          );
        },
      );
    }
    return Scaffold(
      appBar: AppBar(title: const Text('Employees')),
      body: Column(children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(16, 4, 16, 10),
          child: AppSearchField(hint: 'Search name, code, email or mobile', controller: _search, onChanged: _onSearchChanged),
        ),
        Expanded(child: RefreshIndicator(onRefresh: _load, child: body)),
      ]),
      floatingActionButton: canCreate ? FloatingActionButton.extended(onPressed: _create, icon: const Icon(Icons.add_rounded), label: const Text('New employee')) : null,
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
      if (permissions.contains(employeeViewCompensation)) ('Salary', EmployeeSalaryPanel(employeeId: e.id)),
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
