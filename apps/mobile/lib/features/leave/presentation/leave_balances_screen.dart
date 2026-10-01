import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api/api_error.dart';
import '../../auth/state/auth_controller.dart';
import '../../profile/data/employee_repository.dart';
import '../../profile/presentation/profile_screen.dart' show employeeRepositoryProvider;
import '../data/leave_repository.dart';
import 'leave_types_screen.dart' show leaveRepositoryProvider;

/// `GET /leave-balances?employee_id=` — self by default; an admin/manager
/// can switch to another employee via the picker.
class LeaveBalancesScreen extends ConsumerStatefulWidget {
  const LeaveBalancesScreen({super.key});

  @override
  ConsumerState<LeaveBalancesScreen> createState() => _LeaveBalancesScreenState();
}

class _LeaveBalancesScreenState extends ConsumerState<LeaveBalancesScreen> {
  String? _employeeId;
  List<Employee> _employees = const [];
  bool _loadingEmployees = true;
  bool _loadingBalances = false;
  List<LeaveBalance> _balances = const [];
  ApiError? _error;

  @override
  void initState() {
    super.initState();
    _employeeId = ref.read(authControllerProvider).user?.employeeId;
    _init();
  }

  Future<void> _init() async {
    try {
      final employees = await ref.read(employeeRepositoryProvider).listEmployees();
      if (mounted) {
        setState(() {
          _employees = employees;
          _employeeId ??= employees.isNotEmpty ? employees.first.id : null;
        });
      }
    } catch (_) {
      // Non-admin callers may not hold EMPLOYEE.VIEW_ALL — fall back to self only.
    } finally {
      if (mounted) setState(() => _loadingEmployees = false);
      _load();
    }
  }

  Future<void> _load() async {
    if (_employeeId == null) return;
    setState(() {
      _loadingBalances = true;
      _error = null;
    });
    try {
      final balances = await ref.read(leaveRepositoryProvider).listLeaveBalances(_employeeId!);
      if (mounted) setState(() => _balances = balances);
    } catch (error) {
      if (mounted) setState(() => _error = error is ApiError ? error : ApiError(status: 0, code: 'UNKNOWN_ERROR', message: 'Something went wrong.'));
    } finally {
      if (mounted) setState(() => _loadingBalances = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    return Scaffold(
      appBar: AppBar(title: const Text('Leave Balances')),
      body: _loadingEmployees
          ? const Center(child: CircularProgressIndicator())
          : Column(
              children: [
                if (_employees.length > 1)
                  Padding(
                    padding: const EdgeInsets.all(12),
                    child: DropdownButtonFormField<String>(
                      value: _employeeId,
                      decoration: const InputDecoration(labelText: 'Employee'),
                      items: [for (final e in _employees) DropdownMenuItem(value: e.id, child: Text(e.fullName.isEmpty ? e.employeeCode : e.fullName))],
                      onChanged: (v) {
                        setState(() => _employeeId = v);
                        _load();
                      },
                    ),
                  ),
                if (_loadingBalances)
                  const Expanded(child: Center(child: CircularProgressIndicator()))
                else if (_error != null)
                  Expanded(
                    child: Center(
                      child: Padding(
                        padding: const EdgeInsets.all(24),
                        child: Column(mainAxisSize: MainAxisSize.min, children: [
                          Text(_error!.message, textAlign: TextAlign.center),
                          const SizedBox(height: 16),
                          FilledButton(onPressed: _load, child: const Text('Retry')),
                        ]),
                      ),
                    ),
                  )
                else if (_balances.isEmpty)
                  const Expanded(child: Center(child: Text('No leave balances yet.')))
                else
                  Expanded(
                    child: RefreshIndicator(
                      onRefresh: _load,
                      child: ListView(
                        padding: const EdgeInsets.all(16),
                        children: [
                          for (final balance in _balances)
                            Container(
                              margin: const EdgeInsets.only(bottom: 8),
                              padding: const EdgeInsets.all(12),
                              decoration: BoxDecoration(color: scheme.surfaceContainerLowest, borderRadius: BorderRadius.circular(10), border: Border.all(color: scheme.outlineVariant)),
                              child: Row(
                                mainAxisAlignment: MainAxisAlignment.spaceBetween,
                                children: [
                                  Text(balance.leaveTypeName),
                                  Column(crossAxisAlignment: CrossAxisAlignment.end, children: [
                                    Text('${balance.balance}', style: const TextStyle(fontWeight: FontWeight.w700)),
                                    if (balance.reservedBalance != 0) Text('${balance.reservedBalance} reserved', style: TextStyle(fontSize: 11, color: scheme.onSurfaceVariant)),
                                  ]),
                                ],
                              ),
                            ),
                        ],
                      ),
                    ),
                  ),
              ],
            ),
    );
  }
}
