import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api/api_error.dart';
import '../../../core/providers.dart';

const _dayTypeLabels = {
  'WORKING': 'Working day',
  'WEEKLY_OFF': 'Weekly off',
  'HOLIDAY': 'Holiday',
  'SPECIAL_WORKING': 'Special working day',
  'SHUTDOWN': 'Shutdown',
};

/// "Day-type lookup" for a work calendar — mirrors the web work-calendar page's tab
/// (`GET /work-calendars/{id}/day-type?date=`).
class DayTypeLookup extends ConsumerStatefulWidget {
  const DayTypeLookup({super.key, required this.calendarId});
  final String calendarId;

  @override
  ConsumerState<DayTypeLookup> createState() => _DayTypeLookupState();
}

class _DayTypeLookupState extends ConsumerState<DayTypeLookup> {
  DateTime? _date;
  bool _loading = false;
  String? _error;
  Map<String, dynamic>? _result;

  String _iso(DateTime d) => '${d.year.toString().padLeft(4, '0')}-${d.month.toString().padLeft(2, '0')}-${d.day.toString().padLeft(2, '0')}';

  Future<void> _lookup() async {
    final picked = await showDatePicker(context: context, initialDate: _date ?? DateTime.now(), firstDate: DateTime(2000), lastDate: DateTime(2100));
    if (picked == null) return;
    setState(() {
      _date = picked;
      _loading = true;
      _error = null;
      _result = null;
    });
    try {
      final data = await ref.read(apiClientProvider).get<Map<String, dynamic>>(
            '/work-calendars/${widget.calendarId}/day-type?date=${_iso(picked)}',
            parse: (d) => d as Map<String, dynamic>,
          );
      if (mounted) setState(() => _result = data);
    } catch (e) {
      if (mounted) setState(() => _error = e is ApiError ? e.message : 'Something went wrong.');
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final r = _result;
    final lines = <String>[
      if (r != null) ...[
        if (r['holiday_name'] != null) 'Holiday: ${r['holiday_name']}',
        if (r['exception_type'] != null) 'Exception: ${r['exception_type']}',
        if (r['holiday_on_weekly_off'] == true) 'Holiday falls on a weekly off',
        if (r['optional_holiday_name'] != null) 'Optional holiday: ${r['optional_holiday_name']}',
        if (r['restricted_holiday_name'] != null) 'Restricted holiday: ${r['restricted_holiday_name']}',
      ],
    ];
    return Padding(
      padding: const EdgeInsets.fromLTRB(16, 16, 16, 0),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text('Day-type lookup', style: Theme.of(context).textTheme.titleMedium),
        const SizedBox(height: 8),
        OutlinedButton.icon(
          onPressed: _loading ? null : _lookup,
          icon: const Icon(Icons.search),
          label: Text(_date == null ? 'Pick a date' : 'Date: ${_iso(_date!)} (change)'),
        ),
        if (_loading) const Padding(padding: EdgeInsets.only(top: 12), child: LinearProgressIndicator()),
        if (_error != null) Padding(padding: const EdgeInsets.only(top: 8), child: Text(_error!, style: TextStyle(color: Theme.of(context).colorScheme.error))),
        if (r != null)
          Card(
            margin: const EdgeInsets.only(top: 12),
            child: Padding(
              padding: const EdgeInsets.all(12),
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Text(_dayTypeLabels[r['day_type']] ?? '${r['day_type']}', style: const TextStyle(fontWeight: FontWeight.w700, fontSize: 16)),
                for (final l in lines) Padding(padding: const EdgeInsets.only(top: 4), child: Text(l)),
              ]),
            ),
          ),
      ]),
    );
  }
}
