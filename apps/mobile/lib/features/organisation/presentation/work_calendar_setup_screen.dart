import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api/api_client.dart';
import '../../../core/api/api_error.dart';
import '../../../core/auth/permissions.dart';
import '../../../core/providers.dart';
import '../../../core/resource/resource_screens.dart' show ResourceDetailScreen;
import '../../../core/time.dart';
import '../../../core/widgets/ui.dart';
import '../../auth/state/auth_controller.dart';
import '../domain/calendar_views.dart';
import '../domain/org_resources.dart' show workCalendarResource;
import 'work_calendar_month_view.dart';

/// Web's weekday order and names; the API counts weekly offs from 0 = Monday.
const setupWeekdays = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'];

/// Guided work calendar setup — mirrors web `work-calendars/setup/page.tsx`: review the server's
/// unconfirmed suggestion for the working week, link holiday calendars, preview the result as a
/// day grid (nothing saved), then activate it after an explicit acknowledgement. Once a
/// company-wide calendar is active the screen says so and links to it.
class WorkCalendarSetupScreen extends ConsumerStatefulWidget {
  const WorkCalendarSetupScreen({super.key});

  @override
  ConsumerState<WorkCalendarSetupScreen> createState() => _WorkCalendarSetupScreenState();
}

class _WorkCalendarSetupScreenState extends ConsumerState<WorkCalendarSetupScreen> {
  Rec? _status;
  List<Rec> _holidayCalendars = const [];
  bool _loading = true;
  ApiError? _error;

  // The editable proposal, seeded from the suggestion. None of it is saved until confirmed.
  List<int> _offDays = [];
  List<String> _holidayIds = [];
  late String _effectiveFrom = businessToday(ref.read(authControllerProvider).user?.companyTimezone ?? 'Asia/Kolkata');
  final _name = TextEditingController(text: 'Default work calendar');

  Rec? _preview;
  bool _previewing = false;
  String? _previewError;

  /// The proposal changed after the last preview, so the preview no longer describes it.
  bool _previewStale = false;
  bool _confirmed = false;
  bool _activating = false;

  ApiClient get _client => ref.read(apiClientProvider);

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void dispose() {
    _name.dispose();
    super.dispose();
  }

  Future<void> _load() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final status = await _client.get<Rec>('/work-calendar-setup', parse: (d) => d as Rec);
      final holidays = await _client.getList<Rec>('/holiday-calendars', query: PageQuery(page: 1, perPage: 100), parseItem: (d) => d as Rec);
      if (!mounted) return;
      setState(() {
        _status = status;
        _holidayCalendars = [for (final c in holidays.data) if (c['is_active'] == true) c];
        final suggestion = status['suggestion'] as Rec?;
        if (suggestion != null) _offDays = [for (final d in (suggestion['weekly_off_weekdays'] as List? ?? const [])) (d as num).toInt()];
      });
    } catch (e) {
      if (mounted) {
        setState(() {
          _status = null;
          _error = e is ApiError ? e : ApiError(status: 0, code: 'UNKNOWN_ERROR', message: 'Something went wrong.');
        });
      }
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  void _edited() {
    if (_preview != null) _previewStale = true;
  }

  Rec get _proposal => {'weekly_off_weekdays': _offDays, 'holiday_calendar_ids': _holidayIds, 'effective_from': _effectiveFrom};

  bool get _proposalValid => _effectiveFrom.isNotEmpty && _offDays.length < 7 && _name.text.trim().isNotEmpty;

  Future<void> _doPreview() async {
    setState(() {
      _previewing = true;
      _previewError = null;
    });
    try {
      final preview = await _client.post<Rec>('/work-calendar-setup/preview', body: _proposal, parse: (d) => d as Rec);
      if (mounted) {
        setState(() {
          _preview = preview;
          _previewStale = false;
        });
      }
    } catch (e) {
      if (mounted) setState(() => _previewError = describeApiError(e));
    } finally {
      if (mounted) setState(() => _previewing = false);
    }
  }

  Future<void> _reviewAndActivate() async {
    final activate = await showDialog<bool>(context: context, builder: (_) => _ActivateDialog(effectiveFrom: _effectiveFrom));
    if (activate != true || !mounted) return;
    final messenger = ScaffoldMessenger.of(context);
    setState(() => _activating = true);
    try {
      await _client.post<Object?>('/work-calendar-setup/confirm', body: {..._proposal, 'name': _name.text.trim(), 'confirm': true}, parse: (_) => null);
      _confirmed = true;
      messenger.showSnackBar(const SnackBar(content: Text('Work calendar activated')));
      await _load();
    } on ApiError catch (e) {
      if (e.code == 'WORK_CALENDAR_ALREADY_CONFIGURED') {
        messenger.showSnackBar(const SnackBar(content: Text('A calendar is already active. Someone else activated a calendar first. Reloading the current status.')));
        await _load();
        return;
      }
      messenger.showSnackBar(SnackBar(content: Text('Could not activate the work calendar. ${describeApiError(e)}')));
    } catch (e) {
      messenger.showSnackBar(SnackBar(content: Text('Could not activate the work calendar. ${describeApiError(e)}')));
    } finally {
      if (mounted) setState(() => _activating = false);
    }
  }

  Future<void> _openCalendar(String id) async {
    try {
      final row = await _client.get<Rec>('/work-calendars/$id', parse: (d) => d as Rec);
      if (!mounted) return;
      await Navigator.of(context).push(MaterialPageRoute(builder: (_) => ResourceDetailScreen(config: workCalendarResource, initial: row)));
    } catch (e) {
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(describeApiError(e))));
    }
  }

  Future<void> _pickDate() async {
    final current = DateTime.parse(_effectiveFrom);
    final picked = await showDatePicker(context: context, helpText: 'Effective from', initialDate: current, firstDate: DateTime(current.year - 5), lastDate: DateTime(current.year + 5));
    if (picked == null) return;
    setState(() {
      _effectiveFrom = isoOf(picked);
      _edited();
    });
  }

  Widget _configured(Rec status) {
    final assignment = status['company_assignment'] as Rec?;
    return AppCard(
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        const StatusChip(label: 'Configured', tone: Tone.success, dot: false),
        const SizedBox(height: 8),
        Text(
          '${_confirmed ? 'The work calendar has been activated.' : 'A company-wide work calendar is already active.'}'
          '${assignment != null ? ' It applies from ${assignment['effective_from']}.' : ''}',
        ),
        if (assignment != null) TextButton(onPressed: () => _openCalendar('${assignment['work_calendar_id']}'), child: const Text('View the calendar')),
      ]),
    );
  }

  List<Widget> _setupRequired(Rec status, bool canManage) {
    final theme = Theme.of(context);
    final muted = TextStyle(fontSize: 12.5, color: theme.colorScheme.onSurfaceVariant);
    final warn = toneColors(context, Tone.warning);
    final suggestion = status['suggestion'] as Rec?;
    final preview = _preview;
    return [
      Semantics(
        liveRegion: true,
        child: Container(
          padding: const EdgeInsets.all(12),
          decoration: BoxDecoration(color: warn.bg, border: Border.all(color: warn.fg.withValues(alpha: 0.3)), borderRadius: BorderRadius.circular(10)),
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            const Text('Work calendar setup required', style: TextStyle(fontWeight: FontWeight.w600)),
            const SizedBox(height: 4),
            Text((suggestion?['notice'] as String?) ?? 'No work calendar is active. Leave and attendance cannot classify days until one is confirmed.', style: muted),
            const SizedBox(height: 4),
            Text('The weekday settings on the company profile are not used for this. Nothing below is saved until you confirm.', style: muted),
          ]),
        ),
      ),
      const SizedBox(height: 12),
      AppCard(
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Wrap(spacing: 8, crossAxisAlignment: WrapCrossAlignment.center, children: [
            Text('Proposed configuration', style: theme.textTheme.titleSmall),
            const StatusChip(label: 'Unconfirmed suggestion', dot: false),
          ]),
          const SizedBox(height: 12),
          const Text('Weekly offs', style: TextStyle(fontWeight: FontWeight.w600)),
          Text('Checked days are non-working every week. Unchecked days are working days.', style: muted),
          for (var i = 0; i < setupWeekdays.length; i++)
            CheckboxListTile(
              dense: true,
              contentPadding: EdgeInsets.zero,
              controlAffinity: ListTileControlAffinity.leading,
              title: Text(setupWeekdays[i]),
              value: _offDays.contains(i),
              onChanged: !canManage
                  ? null
                  : (v) => setState(() {
                        _offDays = v == true ? ([..._offDays, i]..sort()) : [for (final d in _offDays) if (d != i) d];
                        _edited();
                      }),
            ),
          const SizedBox(height: 8),
          const Text('Holiday calendars', style: TextStyle(fontWeight: FontWeight.w600)),
          Text('Public holidays have not been added automatically. Create your holiday calendar under Holiday Calendars and link it here.', style: muted),
          if (_holidayCalendars.isEmpty)
            Padding(padding: const EdgeInsets.only(top: 6), child: Text('No active holiday calendars exist yet. You can still activate a working week now and link holidays later.', style: muted))
          else
            for (final c in _holidayCalendars)
              CheckboxListTile(
                dense: true,
                contentPadding: EdgeInsets.zero,
                controlAffinity: ListTileControlAffinity.leading,
                title: Text('${c['name']}'),
                value: _holidayIds.contains(c['id']),
                onChanged: !canManage
                    ? null
                    : (v) => setState(() {
                          _holidayIds = v == true ? [..._holidayIds, '${c['id']}'] : [for (final id in _holidayIds) if (id != c['id']) id];
                          _edited();
                        }),
              ),
          const SizedBox(height: 8),
          TextField(controller: _name, enabled: canManage, maxLength: 150, decoration: const InputDecoration(labelText: 'Calendar name'), onChanged: (_) => setState(() {})),
          InkWell(
            onTap: canManage ? _pickDate : null,
            child: InputDecorator(decoration: const InputDecoration(labelText: 'Effective from', suffixIcon: Icon(Icons.calendar_today_outlined)), child: Text(_effectiveFrom)),
          ),
          const SizedBox(height: 12),
          if (canManage)
            Wrap(spacing: 8, runSpacing: 8, children: [
              OutlinedButton(onPressed: !_proposalValid || _previewing ? null : _doPreview, child: Text(_previewing ? 'Previewing…' : 'Preview calendar')),
              FilledButton(
                onPressed: !_proposalValid || preview == null || _previewStale || _activating ? null : _reviewAndActivate,
                child: Text(_activating ? 'Activating…' : 'Review and activate'),
              ),
            ])
          else
            Text('You can view this suggestion but need calendar management permission to activate it.', style: muted),
          if (_previewStale)
            Padding(
              padding: const EdgeInsets.only(top: 8),
              child: Semantics(liveRegion: true, child: Text('The proposal changed after the last preview. Preview again before activating.', style: TextStyle(color: warn.fg))),
            ),
          if (_previewError != null) Padding(padding: const EdgeInsets.only(top: 8), child: Text(_previewError!, style: TextStyle(color: theme.colorScheme.error))),
        ]),
      ),
      if (preview != null) ...[
        const SizedBox(height: 12),
        AppCard(
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Wrap(spacing: 8, crossAxisAlignment: WrapCrossAlignment.center, children: [
              Text('Preview', style: theme.textTheme.titleSmall),
              const StatusChip(label: 'Not saved', dot: false),
            ]),
            const SizedBox(height: 6),
            Text(
              '${preview['notice']} Showing ${preview['range_from']} to ${preview['range_to']}: '
              '${preview['working_day_count']} working day${preview['working_day_count'] == 1 ? '' : 's'}, ${preview['non_working_day_count']} non-working.',
              style: muted,
            ),
            for (final w in (preview['warnings'] as List? ?? const [])) Padding(padding: const EdgeInsets.only(top: 4), child: Text('• $w')),
            const SizedBox(height: 8),
            const DayLegend(),
            const SizedBox(height: 8),
            WorkCalendarDayGrid(days: [for (final d in (preview['days'] as List? ?? const [])) d as Rec]),
          ]),
        ),
      ],
    ];
  }

  @override
  Widget build(BuildContext context) {
    final canManage = (ref.watch(authControllerProvider).user?.permissions ?? const <String>[]).contains(orgCalendarManage);
    final status = _status;
    final children = <Widget>[
      Text('Review a suggested working week, check the resulting calendar, then activate it.', style: TextStyle(color: Theme.of(context).colorScheme.onSurfaceVariant)),
      const SizedBox(height: 12),
    ];
    if (_loading && status == null) {
      children.add(const Padding(padding: EdgeInsets.all(24), child: Center(child: CircularProgressIndicator(semanticsLabel: 'Loading setup status…'))));
    } else if (_error != null) {
      final forbidden = _error!.status == 403;
      children.add(StateMessage(
        icon: forbidden ? Icons.lock_outline_rounded : Icons.cloud_off_rounded,
        tone: forbidden ? Tone.warning : Tone.danger,
        title: forbidden ? 'No access' : 'Couldn\'t load this',
        message: forbidden ? 'You do not have permission to manage work calendars.' : _error!.message,
        actionLabel: forbidden ? null : 'Try again',
        onAction: _load,
      ));
    } else if (status?['state'] == 'CONFIGURED') {
      children.add(_configured(status!));
    } else if (status?['state'] == 'SETUP_REQUIRED') {
      children.addAll(_setupRequired(status!, canManage));
    }
    return Scaffold(
      appBar: AppBar(title: const Text('Work calendar setup')),
      body: RefreshIndicator(onRefresh: _load, child: ListView(padding: const EdgeInsets.fromLTRB(16, 8, 16, 32), children: children)),
    );
  }
}

/// Web's activation dialog: what activating does, and an acknowledgement before it can proceed.
class _ActivateDialog extends StatefulWidget {
  const _ActivateDialog({required this.effectiveFrom});
  final String effectiveFrom;

  @override
  State<_ActivateDialog> createState() => _ActivateDialogState();
}

class _ActivateDialogState extends State<_ActivateDialog> {
  bool _acknowledged = false;

  @override
  Widget build(BuildContext context) => AlertDialog(
        title: const Text('Activate this work calendar?'),
        content: SingleChildScrollView(
          child: Column(mainAxisSize: MainAxisSize.min, children: [
            Text(
              'From ${widget.effectiveFrom}, leave and attendance will classify days using this working week and the linked holiday calendars. '
              'Existing approved leave records are not changed, and locked attendance periods and closed payroll are not recalculated.',
            ),
            CheckboxListTile(
              contentPadding: EdgeInsets.zero,
              controlAffinity: ListTileControlAffinity.leading,
              value: _acknowledged,
              onChanged: (v) => setState(() => _acknowledged = v ?? false),
              title: const Text('I have reviewed the preview and want to activate this calendar. Public holidays are only included if I linked a holiday calendar.'),
            ),
          ]),
        ),
        actions: [
          TextButton(onPressed: () => Navigator.of(context).pop(false), child: const Text('Cancel')),
          FilledButton(onPressed: _acknowledged ? () => Navigator.of(context).pop(true) : null, child: const Text('Activate calendar')),
        ],
      );
}
