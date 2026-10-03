import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api/api_error.dart';
import '../../../core/auth/permissions.dart';
import '../../auth/presentation/widgets/auth_form_field.dart';
import '../../auth/state/auth_controller.dart';
import '../../profile/data/employee_repository.dart';
import '../../profile/presentation/profile_screen.dart' show employeeRepositoryProvider;
import '../data/leave_repository.dart';

/// Mirrors `apps/web/src/app/app/leave-balances/page.tsx`: balance per leave type, the
/// append-only ledger behind it, and (with `LEAVE.BALANCE_ADJUST`) encashment and manual
/// adjustment. Self by default; `LEAVE.BALANCE_VIEW_ALL` can switch to another employee.
class LeaveBalancesScreen extends ConsumerStatefulWidget {
  const LeaveBalancesScreen({super.key});

  @override
  ConsumerState<LeaveBalancesScreen> createState() => _LeaveBalancesScreenState();
}

class _LeaveBalancesScreenState extends ConsumerState<LeaveBalancesScreen> {
  String? _employeeId;
  List<Employee> _employees = const [];
  bool _loadingEmployees = true;
  bool _loading = false;
  bool _loadingMore = false;
  List<LeaveBalance> _balances = const [];
  List<LeaveLedgerEntry> _ledger = const [];
  int _ledgerPage = 1;
  bool _hasMore = false;
  ApiError? _error;

  @override
  void initState() {
    super.initState();
    _employeeId = ref.read(authControllerProvider).user?.employeeId;
    _init();
  }

  Future<void> _init() async {
    final permissions = ref.read(authControllerProvider).user?.permissions ?? const <String>[];
    if (permissions.contains(leaveBalanceViewAll)) {
      try {
        final employees = await ref.read(employeeRepositoryProvider).listEmployees();
        if (mounted) {
          setState(() {
            _employees = employees;
            _employeeId ??= employees.isNotEmpty ? employees.first.id : null;
          });
        }
      } catch (_) {
        // Fall back to self only.
      }
    }
    if (mounted) setState(() => _loadingEmployees = false);
    await _load();
  }

  Future<void> _load() async {
    final id = _employeeId;
    if (id == null) return;
    setState(() {
      _loading = true;
      _error = null;
      _ledgerPage = 1;
    });
    try {
      final repo = ref.read(leaveRepositoryProvider);
      final balances = await repo.listLeaveBalances(id);
      final ledger = await repo.listLeaveLedger(id);
      if (mounted) {
        setState(() {
          _balances = balances;
          _ledger = ledger.data;
          _hasMore = ledger.pagination?.hasNext ?? false;
        });
      }
    } catch (error) {
      if (mounted) setState(() => _error = error is ApiError ? error : ApiError(status: 0, code: 'UNKNOWN_ERROR', message: 'Something went wrong.'));
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _loadMore() async {
    final id = _employeeId;
    if (id == null) return;
    setState(() => _loadingMore = true);
    try {
      final next = await ref.read(leaveRepositoryProvider).listLeaveLedger(id, page: _ledgerPage + 1);
      if (mounted) {
        setState(() {
          _ledger = [..._ledger, ...next.data];
          _ledgerPage += 1;
          _hasMore = next.pagination?.hasNext ?? false;
        });
      }
    } catch (error) {
      _toast(error is ApiError ? error.message : 'Something went wrong.');
    } finally {
      if (mounted) setState(() => _loadingMore = false);
    }
  }

  void _toast(String m) => ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(m)));

  String _today() {
    final n = DateTime.now();
    return '${n.year.toString().padLeft(4, '0')}-${n.month.toString().padLeft(2, '0')}-${n.day.toString().padLeft(2, '0')}';
  }

  /// Shared dialog for encashment (positive days) and manual adjustment (signed amount).
  Future<void> _entryDialog(LeaveBalance balance, {required bool encash}) async {
    final amount = TextEditingController();
    final date = TextEditingController(text: _today());
    final reason = TextEditingController();
    String? error;
    final done = await showDialog<bool>(
      context: context,
      builder: (ctx) => StatefulBuilder(
        builder: (ctx, setLocal) => AlertDialog(
          title: Text('${encash ? 'Encash' : 'Adjust'} ${balance.leaveTypeName}'),
          content: SingleChildScrollView(
            child: Column(mainAxisSize: MainAxisSize.min, children: [
              if (error != null) Padding(padding: const EdgeInsets.only(bottom: 8), child: Text(error!, style: TextStyle(color: Theme.of(ctx).colorScheme.error))),
              AuthFormField(
                label: encash ? 'Days to encash' : 'Amount (days)',
                required: true,
                description: encash ? null : 'Positive credits, negative debits.',
                child: TextField(controller: amount, keyboardType: const TextInputType.numberWithOptions(decimal: true, signed: true)),
              ),
              const SizedBox(height: 12),
              AuthFormField(label: 'Effective date', required: true, description: 'YYYY-MM-DD', child: TextField(controller: date)),
              const SizedBox(height: 12),
              AuthFormField(label: 'Reason', required: !encash, child: TextField(controller: reason)),
            ]),
          ),
          actions: [
            TextButton(onPressed: () => Navigator.of(ctx).pop(false), child: const Text('Cancel')),
            FilledButton(
              onPressed: () async {
                final value = num.tryParse(amount.text.trim());
                if (value == null || (encash && value <= 0) || (!encash && value == 0)) {
                  setLocal(() => error = encash ? 'Enter the number of days to encash.' : 'Enter a non-zero amount.');
                  return;
                }
                if (DateTime.tryParse(date.text.trim()) == null) {
                  setLocal(() => error = 'Enter a valid effective date.');
                  return;
                }
                if (!encash && reason.text.trim().isEmpty) {
                  setLocal(() => error = 'A reason is required.');
                  return;
                }
                try {
                  final repo = ref.read(leaveRepositoryProvider);
                  if (encash) {
                    await repo.encashLeave(
                      employeeId: _employeeId!,
                      leaveTypeId: balance.leaveTypeId,
                      days: amount.text.trim(),
                      effectiveDate: date.text.trim(),
                      reason: reason.text.trim().isEmpty ? 'Encashment' : reason.text.trim(),
                    );
                  } else {
                    await repo.adjustLeave(
                      employeeId: _employeeId!,
                      leaveTypeId: balance.leaveTypeId,
                      amount: amount.text.trim(),
                      effectiveDate: date.text.trim(),
                      reason: reason.text.trim(),
                    );
                  }
                  if (ctx.mounted) Navigator.of(ctx).pop(true);
                } catch (e) {
                  setLocal(() => error = e is ApiError ? e.message : 'Something went wrong.');
                }
              },
              child: const Text('Save'),
            ),
          ],
        ),
      ),
    );
    if (done == true) {
      _toast(encash ? 'Encashment recorded.' : 'Adjustment recorded.');
      await _load();
    }
  }

  String _typeName(String leaveTypeId) {
    for (final b in _balances) {
      if (b.leaveTypeId == leaveTypeId) return b.leaveTypeName;
    }
    return '';
  }

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final canAdjust = (ref.watch(authControllerProvider).user?.permissions ?? const <String>[]).contains(leaveBalanceAdjust);
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
                      isExpanded: true,
                      decoration: const InputDecoration(labelText: 'Employee'),
                      items: [for (final e in _employees) DropdownMenuItem(value: e.id, child: Text(e.fullName.isEmpty ? e.employeeCode : e.fullName))],
                      onChanged: (v) {
                        setState(() => _employeeId = v);
                        _load();
                      },
                    ),
                  ),
                if (_loading)
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
                else
                  Expanded(
                    child: RefreshIndicator(
                      onRefresh: _load,
                      child: ListView(
                        padding: const EdgeInsets.all(16),
                        children: [
                          if (_balances.isEmpty) const Padding(padding: EdgeInsets.all(24), child: Center(child: Text('No balance-backed leave types configured yet.'))),
                          for (final balance in _balances)
                            Container(
                              margin: const EdgeInsets.only(bottom: 8),
                              padding: const EdgeInsets.all(12),
                              decoration: BoxDecoration(color: scheme.surfaceContainerLowest, borderRadius: BorderRadius.circular(10), border: Border.all(color: scheme.outlineVariant)),
                              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                                Row(
                                  mainAxisAlignment: MainAxisAlignment.spaceBetween,
                                  children: [
                                    Expanded(child: Text('${balance.leaveTypeName} (${balance.leaveTypeCode})')),
                                    Column(crossAxisAlignment: CrossAxisAlignment.end, children: [
                                      Text('${balance.balance}', style: const TextStyle(fontWeight: FontWeight.w700)),
                                      if (balance.reservedBalance != 0) Text('${balance.reservedBalance} reserved', style: TextStyle(fontSize: 11, color: scheme.onSurfaceVariant)),
                                    ]),
                                  ],
                                ),
                                if (canAdjust)
                                  Padding(
                                    padding: const EdgeInsets.only(top: 8),
                                    child: Row(children: [
                                      OutlinedButton(onPressed: () => _entryDialog(balance, encash: true), child: const Text('Encash')),
                                      const SizedBox(width: 8),
                                      OutlinedButton(onPressed: () => _entryDialog(balance, encash: false), child: const Text('Adjust')),
                                    ]),
                                  ),
                              ]),
                            ),
                          const SizedBox(height: 16),
                          Text(canAdjust ? 'Ledger (append-only — a correction is always a new entry)' : 'Ledger', style: Theme.of(context).textTheme.titleSmall),
                          const SizedBox(height: 8),
                          if (_ledger.isEmpty) Text('No ledger activity yet.', style: TextStyle(color: scheme.onSurfaceVariant)),
                          for (final e in _ledger)
                            ListTile(
                              dense: true,
                              contentPadding: EdgeInsets.zero,
                              title: Text('${e.entryType.replaceAll('_', ' ')} · ${_typeName(e.leaveTypeId)}'),
                              subtitle: Text('${e.effectiveDate}${e.reason != null ? ' · ${e.reason}' : ''}'),
                              trailing: Text(e.amount > 0 ? '+${e.amount}' : '${e.amount}', style: TextStyle(fontWeight: FontWeight.w700, color: e.amount < 0 ? scheme.error : null)),
                            ),
                          if (_hasMore)
                            Center(
                              child: TextButton(onPressed: _loadingMore ? null : _loadMore, child: Text(_loadingMore ? 'Loading…' : 'Load more')),
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
