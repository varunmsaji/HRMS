import 'package:flutter/material.dart';
import '../../../core/widgets/ui.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api/api_error.dart';
import '../../../core/providers.dart';
import '../../../features/shell/more_action.dart';
import '../../auth/state/auth_controller.dart';
import '../../employees/presentation/employees_screen.dart' show EmployeeDetailScreen;
import '../data/employee_repository.dart';
import 'employee_overview.dart';

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
      body = const StateMessage(
        icon: Icons.person_off_outlined,
        tone: Tone.warning,
        title: 'No employee record',
        message: 'No employee record is linked to your account. Ask your admin to link one.',
      );
    } else if (_loading) {
      body = const ListSkeleton(count: 4);
    } else if (_error != null) {
      body = StateMessage(icon: Icons.cloud_off_rounded, tone: Tone.danger, title: 'Couldn\'t load profile', message: _error!.message, actionLabel: 'Try again', onAction: _load);
    } else {
      body = RefreshIndicator(onRefresh: _load, child: EmployeeOverview(
          employee: _employee!,
          actions: [
            OutlinedButton.icon(
              icon: const Icon(Icons.folder_open_outlined),
              label: const Text('Employment & records'),
              onPressed: () => Navigator.of(context).push(MaterialPageRoute(builder: (_) => EmployeeDetailScreen(employee: _employee!))),
            ),
            TextButton.icon(
              icon: const Icon(Icons.logout_rounded),
              label: const Text('Sign out'),
              style: TextButton.styleFrom(foregroundColor: Theme.of(context).colorScheme.error),
              onPressed: () => ref.read(authControllerProvider.notifier).logout(),
            ),
          ],
        ));
    }

    return Scaffold(
      appBar: AppBar(title: const Text('My Profile'), automaticallyImplyLeading: false, actions: const [MoreAction()]),
      body: body,
    );
  }
}

