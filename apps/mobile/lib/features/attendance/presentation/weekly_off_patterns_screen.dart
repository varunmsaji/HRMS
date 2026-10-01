import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api/api_error.dart';
import '../../../core/widgets/async_list_screen.dart';
import '../../auth/presentation/widgets/auth_form_field.dart';
import '../data/attendance_repository.dart';
import 'holiday_calendars_screen.dart' show attendanceRepositoryProvider;

const _weekdays = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'];

class WeeklyOffPatternsScreen extends ConsumerStatefulWidget {
  const WeeklyOffPatternsScreen({super.key});

  @override
  ConsumerState<WeeklyOffPatternsScreen> createState() => _WeeklyOffPatternsScreenState();
}

class _WeeklyOffPatternsScreenState extends ConsumerState<WeeklyOffPatternsScreen> {
  final _listKey = GlobalKey<AsyncListScreenState<WeeklyOffPattern>>();

  Future<void> _create() async {
    final changed = await Navigator.of(context).push<bool>(MaterialPageRoute(builder: (_) => const _WeeklyOffPatternFormScreen()));
    if (changed == true) _listKey.currentState?.reload();
  }

  @override
  Widget build(BuildContext context) {
    return AsyncListScreen<WeeklyOffPattern>(
      key: _listKey,
      title: 'Weekly-Off Patterns',
      fetch: () => ref.read(attendanceRepositoryProvider).listWeeklyOffPatterns(),
      createLabel: 'New pattern',
      onCreate: _create,
      emptyLabel: 'No weekly-off patterns yet.',
      itemBuilder: (context, pattern) => ListTile(
        title: Text(pattern.name),
        subtitle: Text([pattern.patternKind, if (!pattern.isActive) 'Inactive'].join(' · ')),
      ),
    );
  }
}

class _WeeklyOffPatternFormScreen extends ConsumerStatefulWidget {
  const _WeeklyOffPatternFormScreen();

  @override
  ConsumerState<_WeeklyOffPatternFormScreen> createState() => _WeeklyOffPatternFormScreenState();
}

class _WeeklyOffPatternFormScreenState extends ConsumerState<_WeeklyOffPatternFormScreen> {
  final _name = TextEditingController();
  final _code = TextEditingController();
  final Set<int> _selectedWeekdays = {6};
  bool _submitting = false;
  String? _formError;

  Future<void> _submit() async {
    if (_name.text.trim().isEmpty || _selectedWeekdays.isEmpty) {
      setState(() => _formError = 'Name and at least one weekly-off day are required.');
      return;
    }
    setState(() {
      _submitting = true;
      _formError = null;
    });
    try {
      await ref.read(attendanceRepositoryProvider).createWeeklyOffPattern({
        'name': _name.text.trim(),
        if (_code.text.trim().isNotEmpty) 'code': _code.text.trim(),
        'pattern_kind': 'FIXED_WEEKDAYS',
        'rules': [for (final weekday in _selectedWeekdays) {'weekday': weekday, 'off_fraction': 1.0}],
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
      appBar: AppBar(title: const Text('New weekly-off pattern')),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          if (_formError != null) ...[InlineAlert(message: _formError!), const SizedBox(height: 16)],
          AuthFormField(label: 'Name', required: true, child: TextField(controller: _name, enabled: !_submitting)),
          const SizedBox(height: 16),
          AuthFormField(label: 'Code', description: 'Optional', child: TextField(controller: _code, enabled: !_submitting)),
          const SizedBox(height: 20),
          Text('Weekly-off days', style: Theme.of(context).textTheme.labelMedium),
          const SizedBox(height: 4),
          Text('Fixed weekdays off every week — 0 is Monday, matching the API.', style: Theme.of(context).textTheme.bodySmall),
          Wrap(
            spacing: 8,
            children: [
              for (var i = 0; i < _weekdays.length; i++)
                FilterChip(
                  label: Text(_weekdays[i]),
                  selected: _selectedWeekdays.contains(i),
                  onSelected: _submitting
                      ? null
                      : (selected) => setState(() => selected ? _selectedWeekdays.add(i) : _selectedWeekdays.remove(i)),
                ),
            ],
          ),
          const SizedBox(height: 20),
          PrimaryButton(label: 'Create', loading: _submitting, onPressed: _submit),
        ],
      ),
    );
  }
}
