import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api/api_error.dart';
import '../../../core/widgets/async_list_screen.dart';
import '../../auth/presentation/widgets/auth_form_field.dart';
import '../../profile/data/employee_repository.dart';
import '../../profile/presentation/profile_screen.dart' show employeeRepositoryProvider;
import '../data/attendance_repository.dart';

class RostersScreen extends ConsumerStatefulWidget {
  const RostersScreen({super.key});

  @override
  ConsumerState<RostersScreen> createState() => _RostersScreenState();
}

class _RostersScreenState extends ConsumerState<RostersScreen> {
  final _listKey = GlobalKey<AsyncListScreenState<ShiftRoster>>();

  Future<void> _create() async {
    final changed = await Navigator.of(context).push<bool>(MaterialPageRoute(builder: (_) => const _RosterFormScreen()));
    if (changed == true) _listKey.currentState?.reload();
  }

  @override
  Widget build(BuildContext context) {
    final now = DateTime.now();
    final from = DateTime(now.year, now.month, 1).toIso8601String().split('T').first;
    final to = DateTime(now.year, now.month + 1, 0).toIso8601String().split('T').first;
    return AsyncListScreen<ShiftRoster>(
      key: _listKey,
      title: 'Shift Rosters',
      fetch: () => ref.read(attendanceRepositoryProvider).listRosters(dateFrom: from, dateTo: to),
      createLabel: 'New entry',
      onCreate: _create,
      emptyLabel: 'No roster entries this month.',
      itemBuilder: (context, roster) => ListTile(
        title: Text(roster.rosterDate),
        subtitle: Text([
          if (roster.isWeekOffOverride) 'Week off' else if (roster.isHolidayWorkingOverride) 'Holiday working' else if (roster.shiftId != null) 'Shift assigned',
          roster.status,
        ].join(' · ')),
      ),
    );
  }
}

class _RosterFormScreen extends ConsumerStatefulWidget {
  const _RosterFormScreen();

  @override
  ConsumerState<_RosterFormScreen> createState() => _RosterFormScreenState();
}

class _RosterFormScreenState extends ConsumerState<_RosterFormScreen> {
  final _date = TextEditingController();
  final _reason = TextEditingController();
  String? _employeeId;
  String? _shiftId;
  bool _isWeekOffOverride = false;
  bool _submitting = false;
  bool _loadingOptions = true;
  String? _formError;
  List<Employee> _employees = const [];
  List<Shift> _shifts = const [];

  @override
  void initState() {
    super.initState();
    _loadOptions();
  }

  Future<void> _loadOptions() async {
    try {
      final results = await Future.wait([
        ref.read(employeeRepositoryProvider).listEmployees(),
        ref.read(attendanceRepositoryProvider).listShifts(),
      ]);
      if (mounted) {
        setState(() {
          _employees = results[0] as List<Employee>;
          _shifts = results[1] as List<Shift>;
        });
      }
    } finally {
      if (mounted) setState(() => _loadingOptions = false);
    }
  }

  Future<void> _submit() async {
    if (_employeeId == null || DateTime.tryParse(_date.text.trim()) == null) {
      setState(() => _formError = 'Employee and a valid date are required.');
      return;
    }
    setState(() {
      _submitting = true;
      _formError = null;
    });
    try {
      await ref.read(attendanceRepositoryProvider).createRoster({
        'employee_id': _employeeId,
        'roster_date': _date.text.trim(),
        if (!_isWeekOffOverride && _shiftId != null) 'shift_id': _shiftId,
        'is_week_off_override': _isWeekOffOverride,
        'is_holiday_working_override': false,
        if (_reason.text.trim().isNotEmpty) 'reason': _reason.text.trim(),
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
      appBar: AppBar(title: const Text('New roster entry')),
      body: _loadingOptions
          ? const Center(child: CircularProgressIndicator())
          : ListView(
              padding: const EdgeInsets.all(16),
              children: [
                if (_formError != null) ...[InlineAlert(message: _formError!), const SizedBox(height: 16)],
                AuthFormField(
                  label: 'Employee',
                  required: true,
                  child: DropdownButtonFormField<String>(
                    value: _employeeId,
                    items: [for (final e in _employees) DropdownMenuItem(value: e.id, child: Text(e.fullName.isEmpty ? e.employeeCode : e.fullName))],
                    onChanged: _submitting ? null : (v) => setState(() => _employeeId = v),
                  ),
                ),
                const SizedBox(height: 16),
                AuthFormField(label: 'Date', required: true, description: 'YYYY-MM-DD', child: TextField(controller: _date, enabled: !_submitting)),
                const SizedBox(height: 8),
                SwitchListTile(
                  contentPadding: EdgeInsets.zero,
                  title: const Text('Week off override'),
                  value: _isWeekOffOverride,
                  onChanged: _submitting ? null : (v) => setState(() => _isWeekOffOverride = v),
                ),
                if (!_isWeekOffOverride) ...[
                  const SizedBox(height: 8),
                  AuthFormField(
                    label: 'Shift',
                    description: 'Optional',
                    child: DropdownButtonFormField<String?>(
                      value: _shiftId,
                      items: [
                        const DropdownMenuItem(value: null, child: Text('None')),
                        for (final s in _shifts) DropdownMenuItem(value: s.id, child: Text(s.name)),
                      ],
                      onChanged: _submitting ? null : (v) => setState(() => _shiftId = v),
                    ),
                  ),
                ],
                const SizedBox(height: 16),
                AuthFormField(label: 'Reason', description: 'Optional', child: TextField(controller: _reason, enabled: !_submitting)),
                const SizedBox(height: 20),
                PrimaryButton(label: 'Create', loading: _submitting, onPressed: _submit),
              ],
            ),
    );
  }
}
