import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api/api_error.dart';
import '../../auth/state/auth_controller.dart';
import '../../profile/data/employee_repository.dart';
import '../../profile/presentation/profile_screen.dart' show employeeRepositoryProvider;
import '../data/attendance_repository.dart';

/// Month grid of roster entries for a chosen employee — mirrors
/// `apps/web/src/app/app/rosters/calendar/page.tsx`. One cell per day; badge
/// shows "Week off" / "Holiday working" / the shift, in that priority order.
class RosterCalendarScreen extends ConsumerStatefulWidget {
  const RosterCalendarScreen({super.key});

  @override
  ConsumerState<RosterCalendarScreen> createState() => _RosterCalendarScreenState();
}

class _RosterCalendarScreenState extends ConsumerState<RosterCalendarScreen> {
  DateTime _month = DateTime(DateTime.now().year, DateTime.now().month);
  String? _employeeId;
  bool _loadingEmployees = true;
  bool _loadingRosters = false;
  List<Employee> _employees = const [];
  Map<String, ShiftRoster> _rostersByDate = {};
  ApiError? _error;

  @override
  void initState() {
    super.initState();
    _employeeId = ref.read(authControllerProvider).user?.employeeId;
    _loadEmployees();
  }

  Future<void> _loadEmployees() async {
    try {
      final employees = await ref.read(employeeRepositoryProvider).listEmployees();
      if (mounted) {
        setState(() {
          _employees = employees;
          _employeeId ??= employees.isNotEmpty ? employees.first.id : null;
        });
      }
    } finally {
      if (mounted) setState(() => _loadingEmployees = false);
      _loadRosters();
    }
  }

  Future<void> _loadRosters() async {
    if (_employeeId == null) return;
    setState(() {
      _loadingRosters = true;
      _error = null;
    });
    final from = DateTime(_month.year, _month.month, 1);
    final to = DateTime(_month.year, _month.month + 1, 0);
    try {
      final rosters = await ref.read(attendanceRepositoryProvider).listRosters(
            employeeId: _employeeId,
            dateFrom: from.toIso8601String().split('T').first,
            dateTo: to.toIso8601String().split('T').first,
          );
      if (mounted) setState(() => _rostersByDate = {for (final r in rosters) r.rosterDate: r});
    } catch (error) {
      if (mounted) setState(() => _error = error is ApiError ? error : ApiError(status: 0, code: 'UNKNOWN_ERROR', message: 'Something went wrong.'));
    } finally {
      if (mounted) setState(() => _loadingRosters = false);
    }
  }

  void _changeMonth(int delta) {
    setState(() => _month = DateTime(_month.year, _month.month + delta));
    _loadRosters();
  }

  String _label(ShiftRoster? roster) {
    if (roster == null) return '';
    if (roster.isWeekOffOverride) return 'Week off';
    if (roster.isHolidayWorkingOverride) return 'Holiday working';
    if (roster.shiftId != null) return 'Shift';
    return '';
  }

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final firstOfMonth = DateTime(_month.year, _month.month, 1);
    final daysInMonth = DateTime(_month.year, _month.month + 1, 0).day;
    final leadingBlanks = (firstOfMonth.weekday - 1) % 7;

    return Scaffold(
      appBar: AppBar(title: const Text('Roster Calendar')),
      body: _loadingEmployees
          ? const Center(child: CircularProgressIndicator())
          : Column(
              children: [
                Padding(
                  padding: const EdgeInsets.all(12),
                  child: DropdownButtonFormField<String>(
                    value: _employeeId,
                    decoration: const InputDecoration(labelText: 'Employee'),
                    items: [for (final e in _employees) DropdownMenuItem(value: e.id, child: Text(e.fullName.isEmpty ? e.employeeCode : e.fullName))],
                    onChanged: (v) {
                      setState(() => _employeeId = v);
                      _loadRosters();
                    },
                  ),
                ),
                Padding(
                  padding: const EdgeInsets.symmetric(horizontal: 12),
                  child: Row(
                    mainAxisAlignment: MainAxisAlignment.spaceBetween,
                    children: [
                      IconButton(icon: const Icon(Icons.chevron_left), onPressed: () => _changeMonth(-1)),
                      Text('${_month.year}-${_month.month.toString().padLeft(2, '0')}', style: Theme.of(context).textTheme.headlineSmall),
                      IconButton(icon: const Icon(Icons.chevron_right), onPressed: () => _changeMonth(1)),
                    ],
                  ),
                ),
                if (_loadingRosters) const LinearProgressIndicator(),
                if (_error != null) Padding(padding: const EdgeInsets.all(16), child: Text(_error!.message)),
                Expanded(
                  child: GridView.builder(
                    padding: const EdgeInsets.all(12),
                    gridDelegate: const SliverGridDelegateWithFixedCrossAxisCount(crossAxisCount: 7, childAspectRatio: 0.8),
                    itemCount: daysInMonth + leadingBlanks,
                    itemBuilder: (context, index) {
                      if (index < leadingBlanks) return const SizedBox.shrink();
                      final day = index - leadingBlanks + 1;
                      final date = DateTime(_month.year, _month.month, day);
                      final key = date.toIso8601String().split('T').first;
                      final roster = _rostersByDate[key];
                      final label = _label(roster);
                      return Container(
                        margin: const EdgeInsets.all(2),
                        padding: const EdgeInsets.all(4),
                        decoration: BoxDecoration(
                          border: Border.all(color: scheme.outlineVariant),
                          borderRadius: BorderRadius.circular(6),
                          color: roster?.status == 'PUBLISHED' ? scheme.primaryContainer.withValues(alpha: 0.15) : null,
                        ),
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Text('$day', style: const TextStyle(fontSize: 12)),
                            if (label.isNotEmpty)
                              Expanded(
                                child: Text(label, style: TextStyle(fontSize: 9, color: scheme.onSurfaceVariant), overflow: TextOverflow.clip),
                              ),
                          ],
                        ),
                      );
                    },
                  ),
                ),
              ],
            ),
    );
  }
}
