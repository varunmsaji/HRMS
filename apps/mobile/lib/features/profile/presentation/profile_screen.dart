import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api/api_error.dart';
import '../../../core/providers.dart';
import '../../../features/shell/more_action.dart';
import '../../auth/state/auth_controller.dart';
import '../data/employee_repository.dart';

final employeeRepositoryProvider = Provider<EmployeeRepository>(
  (ref) => EmployeeRepository(ref.watch(apiClientProvider)),
);

/// Basic personal-record view — the mobile counterpart of `apps/web/src/app/app/me/page.tsx`'s
/// "Overview" tab only (identity, personal contact, present address, emergency
/// contact). The web page's other tabs (Employment, Assignment, Compensation,
/// Statutory, Banking, Attendance) each call separate, join-heavy endpoints
/// and are a follow-up, not a partial/half-built copy of this one.
class ProfileScreen extends ConsumerStatefulWidget {
  const ProfileScreen({super.key});

  @override
  ConsumerState<ProfileScreen> createState() => _ProfileScreenState();
}

class _ProfileScreenState extends ConsumerState<ProfileScreen> {
  bool _loading = true;
  Employee? _employee;
  ApiError? _error;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    final employeeId = ref.read(authControllerProvider).user?.employeeId;
    if (employeeId == null) {
      setState(() {
        _loading = false;
        _employee = null;
        _error = null;
      });
      return;
    }
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final employee = await ref.read(employeeRepositoryProvider).getEmployee(employeeId);
      if (mounted) setState(() => _employee = employee);
    } catch (error) {
      if (mounted) {
        setState(() => _error = error is ApiError ? error : ApiError(status: 0, code: 'UNKNOWN_ERROR', message: 'Something went wrong.'));
      }
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final user = ref.watch(authControllerProvider).user;

    Widget body;
    if (user?.employeeId == null) {
      body = const Center(
        child: Padding(
          padding: EdgeInsets.all(24),
          child: Text(
            'No employee record is linked to your account. Ask your admin to link one.',
            textAlign: TextAlign.center,
          ),
        ),
      );
    } else if (_loading) {
      body = const Center(child: CircularProgressIndicator());
    } else if (_error != null) {
      body = Center(
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Text(_error!.message, textAlign: TextAlign.center),
              const SizedBox(height: 16),
              FilledButton(onPressed: _load, child: const Text('Retry')),
            ],
          ),
        ),
      );
    } else {
      body = RefreshIndicator(onRefresh: _load, child: _ProfileBody(employee: _employee!));
    }

    return Scaffold(
      appBar: AppBar(title: const Text('My Profile'), automaticallyImplyLeading: false, actions: const [MoreAction()]),
      body: body,
    );
  }
}

class _ProfileBody extends StatelessWidget {
  const _ProfileBody({required this.employee});

  final Employee employee;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        Row(
          children: [
            CircleAvatar(
              radius: 28,
              backgroundColor: scheme.primaryContainer.withValues(alpha: 0.3),
              child: Text(
                employee.fullName.isEmpty ? '?' : employee.fullName.trim()[0].toUpperCase(),
                style: TextStyle(fontSize: 22, fontWeight: FontWeight.w700, color: scheme.primary),
              ),
            ),
            const SizedBox(width: 14),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(employee.fullName, style: Theme.of(context).textTheme.headlineMedium),
                  Text(employee.employeeCode, style: TextStyle(color: scheme.onSurfaceVariant)),
                ],
              ),
            ),
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
              decoration: BoxDecoration(color: scheme.surfaceContainerHigh, borderRadius: BorderRadius.circular(4)),
              child: Text(employee.status.toUpperCase(), style: const TextStyle(fontSize: 11, fontWeight: FontWeight.w600)),
            ),
          ],
        ),
        const SizedBox(height: 24),
        _Section(
          title: 'Identity',
          fields: [
            _Field('Employee code', employee.employeeCode),
            _Field('Date of birth', employee.dateOfBirth),
            _Field('Gender', employee.gender),
            _Field('Marital status', employee.maritalStatus),
            _Field('Blood group', employee.bloodGroup),
            _Field('Nationality', employee.nationality),
          ],
        ),
        const SizedBox(height: 20),
        _Section(
          title: 'Personal contact',
          fields: [
            _Field('Personal email', employee.personalEmail),
            _Field('Personal mobile', employee.personalMobile),
          ],
        ),
        const SizedBox(height: 20),
        _Section(
          title: 'Present address',
          fields: [
            _Field('Address', employee.presentAddressLine1),
            _Field('Address line 2', employee.presentAddressLine2),
            _Field('City', employee.presentCity),
            _Field('State', employee.presentStateCode),
            _Field('Pincode', employee.presentPincode),
            _Field('Country', employee.presentCountryCode),
          ],
        ),
        const SizedBox(height: 20),
        _Section(
          title: 'Emergency contact',
          fields: [
            _Field('Name', employee.emergencyContactName),
            _Field('Relationship', employee.emergencyContactRelationship),
            _Field('Phone', employee.emergencyContactPhone),
          ],
        ),
      ],
    );
  }
}

class _Field {
  const _Field(this.label, this.value);
  final String label;
  final String? value;
}

class _Section extends StatelessWidget {
  const _Section({required this.title, required this.fields});

  final String title;
  final List<_Field> fields;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: scheme.surfaceContainerLowest,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: scheme.outlineVariant),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(title, style: Theme.of(context).textTheme.headlineSmall),
          const SizedBox(height: 12),
          Wrap(
            runSpacing: 16,
            children: [
              for (final field in fields)
                SizedBox(
                  width: (MediaQuery.of(context).size.width - 32 - 32) / 2,
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        field.label.toUpperCase(),
                        style: TextStyle(fontSize: 11, fontWeight: FontWeight.w600, color: scheme.onSurfaceVariant, letterSpacing: 0.4),
                      ),
                      const SizedBox(height: 3),
                      Text(
                        (field.value != null && field.value!.trim().isNotEmpty) ? field.value! : 'Not configured',
                        style: TextStyle(
                          color: (field.value != null && field.value!.trim().isNotEmpty) ? scheme.onSurface : scheme.onSurfaceVariant,
                        ),
                      ),
                    ],
                  ),
                ),
            ],
          ),
        ],
      ),
    );
  }
}
