import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api/api_error.dart';
import '../../../core/widgets/async_list_screen.dart';
import '../../auth/presentation/widgets/auth_form_field.dart';
import '../../auth/state/auth_controller.dart';
import '../../profile/data/employee_repository.dart';
import '../../profile/presentation/employee_record_sections.dart';
import '../../profile/presentation/profile_screen.dart' show employeeRepositoryProvider;

/// "Mobile Employees Directory" — mirrors `apps/web/src/app/app/employees/`.
class EmployeesScreen extends ConsumerStatefulWidget {
  const EmployeesScreen({super.key});

  @override
  ConsumerState<EmployeesScreen> createState() => _EmployeesScreenState();
}

class _EmployeesScreenState extends ConsumerState<EmployeesScreen> {
  final _listKey = GlobalKey<AsyncListScreenState<Employee>>();

  Future<void> _create() async {
    final changed = await Navigator.of(context).push<bool>(MaterialPageRoute(builder: (_) => const _EmployeeFormScreen()));
    if (changed == true) _listKey.currentState?.reload();
  }

  @override
  Widget build(BuildContext context) {
    return AsyncListScreen<Employee>(
      key: _listKey,
      title: 'Employees',
      fetch: () => ref.read(employeeRepositoryProvider).listEmployees(),
      createLabel: 'New employee',
      onCreate: _create,
      emptyLabel: 'No employees yet.',
      itemBuilder: (context, employee) => ListTile(
        title: Text(employee.fullName.isEmpty ? employee.employeeCode : employee.fullName),
        subtitle: Text([employee.employeeCode, employee.status].join(' · ')),
        trailing: const Icon(Icons.chevron_right, size: 20),
        onTap: () => Navigator.of(context).push(MaterialPageRoute(builder: (_) => EmployeeDetailScreen(employee: employee))),
      ),
    );
  }
}

/// "Employee Profile (Manager View)" — Overview plus a read-only tab per
/// employee-record section the viewer's permissions allow (web:
/// `apps/web/src/app/app/employees/[id]/page.tsx`).
class EmployeeDetailScreen extends ConsumerWidget {
  const EmployeeDetailScreen({super.key, required this.employee});
  final Employee employee;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final scheme = Theme.of(context).colorScheme;
    final permissions = ref.watch(authControllerProvider).user?.permissions ?? const <String>[];
    final sections = [
      for (final s in employeeRecordSections)
        if (s.permission == null || permissions.contains(s.permission)) s,
    ];
    final overview = ListView(
      padding: const EdgeInsets.all(16),
      children: [
        Container(
          padding: const EdgeInsets.all(16),
          decoration: BoxDecoration(color: scheme.surfaceContainerLowest, borderRadius: BorderRadius.circular(12), border: Border.all(color: scheme.outlineVariant)),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              _row(context, 'Employee code', employee.employeeCode),
              _row(context, 'Status', employee.status),
              _row(context, 'Personal email', employee.personalEmail ?? 'Not configured'),
              _row(context, 'Personal mobile', employee.personalMobile ?? 'Not configured'),
              _row(context, 'Gender', employee.gender ?? 'Not configured'),
              _row(context, 'Date of birth', employee.dateOfBirth ?? 'Not configured'),
            ],
          ),
        ),
      ],
    );
    return DefaultTabController(
      length: sections.length + 1,
      child: Scaffold(
        appBar: AppBar(
          title: Text(employee.fullName.isEmpty ? employee.employeeCode : employee.fullName),
          bottom: TabBar(
            isScrollable: true,
            tabAlignment: TabAlignment.start,
            tabs: [const Tab(text: 'Overview'), for (final s in sections) Tab(text: s.title)],
          ),
        ),
        body: TabBarView(
          children: [overview, for (final s in sections) EmployeeRecordPanel(employeeId: employee.id, section: s)],
        ),
      ),
    );
  }

  Widget _row(BuildContext context, String label, String value) {
    final scheme = Theme.of(context).colorScheme;
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 6),
      child: Row(mainAxisAlignment: MainAxisAlignment.spaceBetween, children: [
        Text(label, style: TextStyle(color: scheme.onSurfaceVariant)),
        Text(value),
      ]),
    );
  }
}

class _EmployeeFormScreen extends ConsumerStatefulWidget {
  const _EmployeeFormScreen();

  @override
  ConsumerState<_EmployeeFormScreen> createState() => _EmployeeFormScreenState();
}

class _EmployeeFormScreenState extends ConsumerState<_EmployeeFormScreen> {
  final _firstName = TextEditingController();
  final _lastName = TextEditingController();
  final _email = TextEditingController();
  final _mobile = TextEditingController();
  bool _submitting = false;
  String? _formError;

  Future<void> _submit() async {
    if (_firstName.text.trim().isEmpty) {
      setState(() => _formError = 'First name is required.');
      return;
    }
    setState(() {
      _submitting = true;
      _formError = null;
    });
    try {
      await ref.read(employeeRepositoryProvider).createEmployee({
        'first_name': _firstName.text.trim(),
        if (_lastName.text.trim().isNotEmpty) 'last_name': _lastName.text.trim(),
        if (_email.text.trim().isNotEmpty) 'personal_email': _email.text.trim(),
        if (_mobile.text.trim().isNotEmpty) 'personal_mobile': _mobile.text.trim(),
      });
      if (mounted) Navigator.of(context).pop(true);
    } catch (error) {
      setState(() => _formError = error is ApiError ? error.message : 'Something went wrong.');
    } finally {
      if (mounted) setState(() => _submitting = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('New employee')),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          if (_formError != null) ...[InlineAlert(message: _formError!), const SizedBox(height: 16)],
          Row(children: [
            Expanded(child: AuthFormField(label: 'First name', required: true, child: TextField(controller: _firstName, enabled: !_submitting))),
            const SizedBox(width: 12),
            Expanded(child: AuthFormField(label: 'Last name', child: TextField(controller: _lastName, enabled: !_submitting))),
          ]),
          const SizedBox(height: 16),
          AuthFormField(label: 'Personal email', child: TextField(controller: _email, enabled: !_submitting, keyboardType: TextInputType.emailAddress)),
          const SizedBox(height: 16),
          AuthFormField(label: 'Personal mobile', child: TextField(controller: _mobile, enabled: !_submitting)),
          const SizedBox(height: 20),
          PrimaryButton(label: 'Create', loading: _submitting, onPressed: _submit),
        ],
      ),
    );
  }
}
