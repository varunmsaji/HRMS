import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api/api_error.dart';
import '../../../core/providers.dart';
import '../../../core/widgets/async_list_screen.dart';
import '../../auth/presentation/widgets/auth_form_field.dart';
import '../data/attendance_repository.dart';

final attendanceRepositoryProvider = Provider<AttendanceRepository>(
  (ref) => AttendanceRepository(ref.watch(apiClientProvider)),
);

class HolidayCalendarsScreen extends ConsumerStatefulWidget {
  const HolidayCalendarsScreen({super.key});

  @override
  ConsumerState<HolidayCalendarsScreen> createState() => _HolidayCalendarsScreenState();
}

class _HolidayCalendarsScreenState extends ConsumerState<HolidayCalendarsScreen> {
  final _listKey = GlobalKey<AsyncListScreenState<HolidayCalendar>>();

  Future<void> _create() async {
    final nameController = TextEditingController();
    String kind = 'COMPANY';
    final created = await showDialog<bool>(
      context: context,
      builder: (context) => StatefulBuilder(
        builder: (context, setState) => AlertDialog(
          title: const Text('New holiday calendar'),
          content: Column(mainAxisSize: MainAxisSize.min, children: [
            AuthFormField(label: 'Name', required: true, child: TextField(controller: nameController)),
            const SizedBox(height: 12),
            AuthFormField(
              label: 'Kind',
              child: DropdownButtonFormField<String>(
                value: kind,
                items: const [
                  DropdownMenuItem(value: 'NATIONAL', child: Text('National')),
                  DropdownMenuItem(value: 'REGIONAL', child: Text('Regional')),
                  DropdownMenuItem(value: 'COMPANY', child: Text('Company')),
                  DropdownMenuItem(value: 'LOCATION', child: Text('Location')),
                ],
                onChanged: (v) => setState(() => kind = v ?? kind),
              ),
            ),
          ]),
          actions: [
            TextButton(onPressed: () => Navigator.of(context).pop(false), child: const Text('Cancel')),
            FilledButton(
              onPressed: () async {
                if (nameController.text.trim().isEmpty) return;
                try {
                  await ref.read(attendanceRepositoryProvider).createHolidayCalendar(name: nameController.text.trim(), kind: kind);
                  if (context.mounted) Navigator.of(context).pop(true);
                } catch (error) {
                  if (context.mounted) {
                    ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(error is ApiError ? error.message : 'Something went wrong.')));
                  }
                }
              },
              child: const Text('Create'),
            ),
          ],
        ),
      ),
    );
    if (created == true) _listKey.currentState?.reload();
  }

  @override
  Widget build(BuildContext context) {
    return AsyncListScreen<HolidayCalendar>(
      key: _listKey,
      title: 'Holiday Calendars',
      fetch: () => ref.read(attendanceRepositoryProvider).listHolidayCalendars(),
      createLabel: 'New calendar',
      onCreate: _create,
      emptyLabel: 'No holiday calendars yet.',
      itemBuilder: (context, calendar) => ListTile(
        title: Text(calendar.name),
        subtitle: Text([calendar.kind, if (!calendar.isActive) 'Inactive'].join(' · ')),
        trailing: const Icon(Icons.chevron_right, size: 20),
        onTap: () => Navigator.of(context).push(
          MaterialPageRoute(builder: (_) => HolidaysScreen(calendar: calendar)),
        ),
      ),
    );
  }
}

class HolidaysScreen extends ConsumerStatefulWidget {
  const HolidaysScreen({super.key, required this.calendar});
  final HolidayCalendar calendar;

  @override
  ConsumerState<HolidaysScreen> createState() => _HolidaysScreenState();
}

class _HolidaysScreenState extends ConsumerState<HolidaysScreen> {
  final _listKey = GlobalKey<AsyncListScreenState<Holiday>>();

  Future<void> _create() async {
    final nameController = TextEditingController();
    final dateController = TextEditingController();
    String holidayType = 'PUBLIC';
    final created = await showDialog<bool>(
      context: context,
      builder: (context) => StatefulBuilder(
        builder: (context, setState) => AlertDialog(
          title: const Text('New holiday'),
          content: Column(mainAxisSize: MainAxisSize.min, children: [
            AuthFormField(label: 'Date', required: true, description: 'YYYY-MM-DD', child: TextField(controller: dateController)),
            const SizedBox(height: 12),
            AuthFormField(label: 'Name', required: true, child: TextField(controller: nameController)),
            const SizedBox(height: 12),
            AuthFormField(
              label: 'Type',
              child: DropdownButtonFormField<String>(
                value: holidayType,
                items: const [
                  DropdownMenuItem(value: 'PUBLIC', child: Text('Public')),
                  DropdownMenuItem(value: 'COMPANY', child: Text('Company')),
                  DropdownMenuItem(value: 'OPTIONAL', child: Text('Optional')),
                  DropdownMenuItem(value: 'RESTRICTED', child: Text('Restricted')),
                ],
                onChanged: (v) => setState(() => holidayType = v ?? holidayType),
              ),
            ),
          ]),
          actions: [
            TextButton(onPressed: () => Navigator.of(context).pop(false), child: const Text('Cancel')),
            FilledButton(
              onPressed: () async {
                if (nameController.text.trim().isEmpty || DateTime.tryParse(dateController.text.trim()) == null) return;
                try {
                  await ref.read(attendanceRepositoryProvider).createHoliday(widget.calendar.id, {
                    'date': dateController.text.trim(),
                    'name': nameController.text.trim(),
                    'holiday_type': holidayType,
                  });
                  if (context.mounted) Navigator.of(context).pop(true);
                } catch (error) {
                  if (context.mounted) {
                    ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(error is ApiError ? error.message : 'Something went wrong.')));
                  }
                }
              },
              child: const Text('Create'),
            ),
          ],
        ),
      ),
    );
    if (created == true) _listKey.currentState?.reload();
  }

  @override
  Widget build(BuildContext context) {
    return AsyncListScreen<Holiday>(
      key: _listKey,
      title: widget.calendar.name,
      fetch: () => ref.read(attendanceRepositoryProvider).listHolidays(widget.calendar.id),
      createLabel: 'New holiday',
      onCreate: _create,
      emptyLabel: 'No holidays yet.',
      itemBuilder: (context, holiday) => ListTile(
        title: Text(holiday.name),
        subtitle: Text([holiday.date, holiday.holidayType, if (holiday.isWorking) 'Working'].join(' · ')),
      ),
    );
  }
}
