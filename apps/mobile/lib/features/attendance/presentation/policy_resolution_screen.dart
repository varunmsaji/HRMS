import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api/api_error.dart';
import '../../auth/presentation/widgets/auth_form_field.dart';
import '../../profile/data/employee_repository.dart';
import '../../profile/presentation/profile_screen.dart' show employeeRepositoryProvider;
import '../data/attendance_repository.dart';

/// `GET /calendar-resolution?employee_id=&date=` — mirrors
/// `apps/web`'s policy-resolution lookup. Only covers WORK_CALENDAR/
/// WEEKLY_OFF kinds; there's no backend endpoint yet for resolving the
/// effective attendance/overtime/regularization/leave policy directly.
class PolicyResolutionScreen extends ConsumerStatefulWidget {
  const PolicyResolutionScreen({super.key});

  @override
  ConsumerState<PolicyResolutionScreen> createState() => _PolicyResolutionScreenState();
}

class _PolicyResolutionScreenState extends ConsumerState<PolicyResolutionScreen> {
  final _date = TextEditingController(text: DateTime.now().toIso8601String().split('T').first);
  String? _employeeId;
  List<Employee> _employees = const [];
  bool _loadingEmployees = true;
  bool _resolving = false;
  CalendarResolution? _result;
  String? _error;

  @override
  void initState() {
    super.initState();
    _loadEmployees();
  }

  Future<void> _loadEmployees() async {
    try {
      final employees = await ref.read(employeeRepositoryProvider).listEmployees();
      if (mounted) {
        setState(() {
          _employees = employees;
          _employeeId = employees.isNotEmpty ? employees.first.id : null;
        });
      }
    } finally {
      if (mounted) setState(() => _loadingEmployees = false);
    }
  }

  Future<void> _resolve() async {
    if (_employeeId == null) return;
    setState(() {
      _resolving = true;
      _error = null;
    });
    try {
      final result = await ref.read(attendanceRepositoryProvider).resolveCalendar(employeeId: _employeeId!, date: _date.text.trim());
      setState(() => _result = result);
    } catch (error) {
      setState(() => _error = error is ApiError ? error.message : 'Something went wrong.');
    } finally {
      setState(() => _resolving = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    return Scaffold(
      appBar: AppBar(title: const Text('Policy Resolution')),
      body: _loadingEmployees
          ? const Center(child: CircularProgressIndicator())
          : ListView(
              padding: const EdgeInsets.all(16),
              children: [
                AuthFormField(
                  label: 'Employee',
                  child: DropdownButtonFormField<String>(
                    value: _employeeId,
                    items: [for (final e in _employees) DropdownMenuItem(value: e.id, child: Text(e.fullName.isEmpty ? e.employeeCode : e.fullName))],
                    onChanged: (v) => setState(() => _employeeId = v),
                  ),
                ),
                const SizedBox(height: 16),
                AuthFormField(label: 'Date', description: 'YYYY-MM-DD', child: TextField(controller: _date)),
                const SizedBox(height: 20),
                PrimaryButton(label: 'Resolve', loading: _resolving, onPressed: _resolve),
                if (_error != null) ...[const SizedBox(height: 16), InlineAlert(message: _error!)],
                if (_result != null) ...[
                  const SizedBox(height: 20),
                  Container(
                    padding: const EdgeInsets.all(16),
                    decoration: BoxDecoration(color: scheme.surfaceContainerLowest, borderRadius: BorderRadius.circular(12), border: Border.all(color: scheme.outlineVariant)),
                    child: _result!.configIncomplete
                        ? const Text('No work calendar resolves for this employee on this date — configuration incomplete.')
                        : Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Text('Work calendar: ${_result!.workCalendarName ?? '—'}'),
                              if (_result!.dayType != null) ...[
                                const SizedBox(height: 8),
                                Text('Day type: ${_result!.dayType!['day_type'] ?? '—'}'),
                                if (_result!.dayType!['holiday_name'] != null) Text('Holiday: ${_result!.dayType!['holiday_name']}'),
                              ],
                            ],
                          ),
                  ),
                ],
              ],
            ),
    );
  }
}
