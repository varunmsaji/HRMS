import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api/api_error.dart';
import '../../../core/widgets/async_list_screen.dart';
import '../../auth/presentation/widgets/auth_form_field.dart';
import '../data/attendance_repository.dart';
import 'holiday_calendars_screen.dart' show attendanceRepositoryProvider;

class WorkCalendarsScreen extends ConsumerStatefulWidget {
  const WorkCalendarsScreen({super.key});

  @override
  ConsumerState<WorkCalendarsScreen> createState() => _WorkCalendarsScreenState();
}

class _WorkCalendarsScreenState extends ConsumerState<WorkCalendarsScreen> {
  final _listKey = GlobalKey<AsyncListScreenState<WorkCalendar>>();

  Future<void> _create() async {
    final changed = await Navigator.of(context).push<bool>(MaterialPageRoute(builder: (_) => const _WorkCalendarFormScreen()));
    if (changed == true) _listKey.currentState?.reload();
  }

  @override
  Widget build(BuildContext context) {
    return AsyncListScreen<WorkCalendar>(
      key: _listKey,
      title: 'Work Calendars',
      fetch: () => ref.read(attendanceRepositoryProvider).listWorkCalendars(),
      createLabel: 'New calendar',
      onCreate: _create,
      emptyLabel: 'No work calendars yet.',
      itemBuilder: (context, calendar) => ListTile(
        title: Text(calendar.name),
        subtitle: calendar.description == null ? null : Text(calendar.description!),
      ),
    );
  }
}

class _WorkCalendarFormScreen extends ConsumerStatefulWidget {
  const _WorkCalendarFormScreen();

  @override
  ConsumerState<_WorkCalendarFormScreen> createState() => _WorkCalendarFormScreenState();
}

class _WorkCalendarFormScreenState extends ConsumerState<_WorkCalendarFormScreen> {
  final _name = TextEditingController();
  final _description = TextEditingController();
  String? _weeklyOffPatternId;
  final Set<String> _holidayCalendarIds = {};
  bool _submitting = false;
  bool _loadingOptions = true;
  String? _formError;
  List<WeeklyOffPattern> _patterns = const [];
  List<HolidayCalendar> _calendars = const [];

  @override
  void initState() {
    super.initState();
    _loadOptions();
  }

  Future<void> _loadOptions() async {
    try {
      final repository = ref.read(attendanceRepositoryProvider);
      final results = await Future.wait([repository.listWeeklyOffPatterns(), repository.listHolidayCalendars()]);
      if (mounted) {
        setState(() {
          _patterns = results[0] as List<WeeklyOffPattern>;
          _calendars = results[1] as List<HolidayCalendar>;
        });
      }
    } finally {
      if (mounted) setState(() => _loadingOptions = false);
    }
  }

  Future<void> _submit() async {
    if (_name.text.trim().isEmpty) {
      setState(() => _formError = 'Name is required.');
      return;
    }
    setState(() {
      _submitting = true;
      _formError = null;
    });
    try {
      await ref.read(attendanceRepositoryProvider).createWorkCalendar({
        'name': _name.text.trim(),
        if (_description.text.trim().isNotEmpty) 'description': _description.text.trim(),
        if (_weeklyOffPatternId != null) 'weekly_off_pattern_id': _weeklyOffPatternId,
        'holiday_calendar_ids': _holidayCalendarIds.toList(),
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
      appBar: AppBar(title: const Text('New work calendar')),
      body: _loadingOptions
          ? const Center(child: CircularProgressIndicator())
          : ListView(
              padding: const EdgeInsets.all(16),
              children: [
                if (_formError != null) ...[InlineAlert(message: _formError!), const SizedBox(height: 16)],
                AuthFormField(label: 'Name', required: true, child: TextField(controller: _name, enabled: !_submitting)),
                const SizedBox(height: 16),
                AuthFormField(label: 'Description', description: 'Optional', child: TextField(controller: _description, enabled: !_submitting)),
                const SizedBox(height: 16),
                AuthFormField(
                  label: 'Weekly-off pattern',
                  description: 'Optional',
                  child: DropdownButtonFormField<String?>(
                    value: _weeklyOffPatternId,
                    items: [
                      const DropdownMenuItem(value: null, child: Text('None')),
                      for (final p in _patterns) DropdownMenuItem(value: p.id, child: Text(p.name)),
                    ],
                    onChanged: _submitting ? null : (v) => setState(() => _weeklyOffPatternId = v),
                  ),
                ),
                const SizedBox(height: 16),
                Text('Holiday calendars', style: Theme.of(context).textTheme.labelMedium),
                for (final calendar in _calendars)
                  CheckboxListTile(
                    contentPadding: EdgeInsets.zero,
                    title: Text(calendar.name),
                    value: _holidayCalendarIds.contains(calendar.id),
                    onChanged: _submitting
                        ? null
                        : (v) => setState(() => (v ?? false) ? _holidayCalendarIds.add(calendar.id) : _holidayCalendarIds.remove(calendar.id)),
                  ),
                const SizedBox(height: 12),
                PrimaryButton(label: 'Create', loading: _submitting, onPressed: _submit),
              ],
            ),
    );
  }
}
