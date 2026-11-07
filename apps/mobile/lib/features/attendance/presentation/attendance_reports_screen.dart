import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api/api_client.dart';
import '../../../core/api/api_error.dart';
import '../../../core/providers.dart';
import '../../../core/widgets/ui.dart';
import '../data/attendance_repository.dart';
import '../domain/attendance_pulse.dart';
import '../domain/attendance_reports.dart';
import 'attendance_period_detail_screen.dart' show AttendancePeriodDetailScreen;

/// The Reports panel of the web attendance dashboard (`reports-panel.tsx`) as its own phone screen:
/// six read-only reports with search, sort and 15-row pages. It takes what the insights screen
/// already loaded for the selected range; only the payroll report fetches (its period summary).
class AttendanceReportsScreen extends ConsumerStatefulWidget {
  const AttendanceReportsScreen({
    super.key,
    required this.days,
    required this.overtime,
    required this.overtimeError,
    required this.periods,
    required this.name,
    required this.zone,
    required this.today,
    required this.rangeLabel,
  });

  /// Attendance days in the selected range.
  final List<AttendanceDay> days;

  /// Overtime records in the range; ignored when [overtimeError] is set.
  final List<Rec> overtime;
  final String? overtimeError;

  /// Attendance periods, or null when they could not be loaded.
  final List<Rec>? periods;
  final String Function(String employeeId) name;
  final String zone;
  final String today;
  final String rangeLabel;

  @override
  ConsumerState<AttendanceReportsScreen> createState() => _AttendanceReportsScreenState();
}

class _AttendanceReportsScreenState extends ConsumerState<AttendanceReportsScreen> {
  final _search = TextEditingController();
  String _report = 'daily';
  String? _sortKey;
  bool _ascending = true;
  int _page = 1;

  late final List<ReportDef> _reports = buildReports(days: widget.days, overtime: widget.overtime, name: widget.name, zone: widget.zone);

  // Payroll attendance: loaded the first time that report is opened.
  late final Rec? _period = pickDefaultPeriod(widget.periods ?? const [], widget.today);
  List<Rec>? _summary;
  ApiError? _summaryError;
  bool _summaryLoading = false;

  @override
  void dispose() {
    _search.dispose();
    super.dispose();
  }

  Future<void> _loadSummary() async {
    final period = _period;
    if (period == null || _summaryLoading) return;
    setState(() {
      _summaryLoading = true;
      _summaryError = null;
    });
    try {
      final client = ref.read(apiClientProvider);
      final out = <Rec>[];
      for (var page = 1; page <= 50; page++) {
        final env = await client.getList<Rec>('/attendance-periods/${period['id']}/summary', query: PageQuery(page: page, perPage: 100), parseItem: (d) => d as Rec);
        out.addAll(env.data);
        if (env.pagination == null || !env.pagination!.hasNext) break;
      }
      if (mounted) setState(() => _summary = out);
    } catch (e) {
      if (mounted) setState(() => _summaryError = e is ApiError ? e : ApiError(status: 0, code: 'UNKNOWN_ERROR', message: 'Something went wrong.'));
    } finally {
      if (mounted) setState(() => _summaryLoading = false);
    }
  }

  void _choose(String key) {
    setState(() {
      _report = key;
      _sortKey = null;
      _ascending = true;
      _page = 1;
    });
    if (key == 'payroll' && _summary == null) _loadSummary();
  }

  Widget _note(String text, {bool alert = false}) => Padding(
        padding: const EdgeInsets.symmetric(vertical: 24),
        child: Text(text, textAlign: TextAlign.center, style: TextStyle(color: alert ? Theme.of(context).colorScheme.error : null)),
      );

  /// What to show instead of a table, or null when the report has rows to show.
  Widget? _blocked() {
    if (_report == 'overtime' && widget.overtimeError != null) return _note(widget.overtimeError!, alert: true);
    if (_report != 'payroll') return null;
    if (_period == null) return _note('No attendance period to report on yet.');
    if (_summaryError != null) {
      final forbidden = _summaryError!.status == 403;
      return Column(children: [
        _note(forbidden ? 'You do not have permission to view the period summary.' : 'The period summary failed to load.', alert: true),
        if (!forbidden) TextButton(onPressed: _loadSummary, child: const Text('Try again')),
      ]);
    }
    if (_summary == null) return const Padding(padding: EdgeInsets.all(24), child: Center(child: CircularProgressIndicator(semanticsLabel: 'Loading period summary…')));
    return null;
  }

  ReportDef get _def => _report == 'payroll' ? payrollReport(_summary ?? const [], widget.name) : _reports.firstWhere((r) => r.key == _report);

  Widget _row(ReportDef def, dynamic row) {
    final theme = Theme.of(context);
    final title = def.columns.take(def.titleColumns).map((c) => c.render(row)).join(' · ');
    return AppCard(
      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text(title, style: theme.textTheme.bodyLarge?.copyWith(fontWeight: FontWeight.w600), maxLines: 1, overflow: TextOverflow.ellipsis),
        const SizedBox(height: 4),
        Wrap(spacing: 14, runSpacing: 2, children: [
          for (final c in def.columns.skip(def.titleColumns))
            Text.rich(TextSpan(children: [
              TextSpan(text: '${c.label} ', style: TextStyle(color: theme.colorScheme.onSurfaceVariant, fontSize: 12)),
              TextSpan(text: c.render(row), style: const TextStyle(fontWeight: FontWeight.w600, fontSize: 13)),
            ])),
        ]),
      ]),
    );
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final blocked = _blocked();
    final def = _def;
    final view = reportView(def, query: _search.text, sortKey: _sortKey, ascending: _ascending, page: _page);
    final sortKey = _sortKey ?? def.columns.first.key;
    return Scaffold(
      appBar: AppBar(title: const Text('Reports')),
      body: ListView(padding: const EdgeInsets.fromLTRB(16, 4, 16, 32), children: [
        Text('${widget.rangeLabel}. Read-only views of existing attendance data.', style: TextStyle(fontSize: 12, color: theme.colorScheme.onSurfaceVariant)),
        const SizedBox(height: 10),
        SingleChildScrollView(
          scrollDirection: Axis.horizontal,
          child: Row(children: [
            for (final e in reportLabels.entries)
              Padding(padding: const EdgeInsets.only(right: 6), child: ChoiceChip(label: Text(e.value), selected: _report == e.key, onSelected: (_) => _choose(e.key))),
          ]),
        ),
        const SizedBox(height: 10),
        if (_report == 'payroll' && _period != null)
          Row(children: [
            Expanded(child: Text(periodTitle(_period), style: TextStyle(fontSize: 12, color: theme.colorScheme.onSurfaceVariant))),
            TextButton(
              onPressed: () => Navigator.of(context).push(MaterialPageRoute(builder: (_) => AttendancePeriodDetailScreen(periodId: _period['id'] as String, initial: _period))),
              child: const Text('Open period'),
            ),
          ]),
        if (blocked != null)
          blocked
        else ...[
          AppSearchField(
            hint: 'Search',
            controller: _search,
            onChanged: (_) => setState(() => _page = 1),
          ),
          const SizedBox(height: 8),
          Row(children: [
            Text('Sort by', style: theme.textTheme.labelLarge),
            const SizedBox(width: 8),
            Expanded(
              child: DropdownButton<String>(
                isExpanded: true,
                value: sortKey,
                items: [for (final c in def.columns) DropdownMenuItem(value: c.key, child: Text(c.label))],
                onChanged: (k) => setState(() {
                  _sortKey = k;
                  _page = 1;
                }),
              ),
            ),
            IconButton(
              tooltip: _ascending ? 'Ascending' : 'Descending',
              onPressed: () => setState(() => _ascending = !_ascending),
              icon: Icon(_ascending ? Icons.arrow_upward_rounded : Icons.arrow_downward_rounded),
            ),
          ]),
          const SizedBox(height: 4),
          if (view.total == 0)
            _note(def.empty)
          else ...[
            for (final row in view.rows) Padding(padding: const EdgeInsets.only(bottom: 8), child: _row(def, row)),
            Row(children: [
              Expanded(child: Text('${view.total} row${view.total == 1 ? '' : 's'}', style: TextStyle(fontSize: 12, color: theme.colorScheme.onSurfaceVariant))),
              if (view.pages > 1) ...[
                TextButton(onPressed: view.page <= 1 ? null : () => setState(() => _page = view.page - 1), child: const Text('Previous')),
                Text('Page ${view.page} of ${view.pages}', style: const TextStyle(fontSize: 12)),
                TextButton(onPressed: view.page >= view.pages ? null : () => setState(() => _page = view.page + 1), child: const Text('Next')),
              ],
            ]),
          ],
        ],
      ]),
    );
  }
}
