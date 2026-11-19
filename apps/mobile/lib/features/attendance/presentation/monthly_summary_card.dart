import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api/api_client.dart';
import '../../../core/api/api_error.dart';
import '../../../core/providers.dart';
import '../../../core/time.dart';
import '../domain/attendance_pulse.dart';
import '../../../core/widgets/ui.dart';

typedef _Rec = Map<String, dynamic>;

/// The monthly attendance summary of one period: employee-days as Payroll will read them (web
/// `monthly-summary.tsx`). It sits on the Attendance Periods screen, with the periods it
/// summarises, as on web since the periods moved under Payroll. Live while a period is open,
/// a frozen snapshot once it is closed.
///
/// [periods] are the periods to choose from (the screen's entity filter already applied); the
/// default is the one the web picks for [today] ([pickDefaultPeriod]).
class MonthlySummaryCard extends ConsumerStatefulWidget {
  const MonthlySummaryCard({super.key, required this.periods, required this.today});

  final List<Map<String, dynamic>> periods;
  final String today;

  @override
  ConsumerState<MonthlySummaryCard> createState() => _MonthlySummaryCardState();
}

class _MonthlySummaryCardState extends ConsumerState<MonthlySummaryCard> {
  String? _periodId;
  List<_Rec>? _rows;
  String? _error;
  int _request = 0;

  /// Newest first, as the choice list reads.
  List<_Rec> get _sorted => [...widget.periods]..sort((a, b) => '${b['period_start']}'.compareTo('${a['period_start']}'));

  _Rec? get _period {
    if (_periodId != null) {
      for (final p in widget.periods) {
        if (p['id'] == _periodId) return p;
      }
    }
    return pickDefaultPeriod(widget.periods, widget.today);
  }

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void didUpdateWidget(MonthlySummaryCard old) {
    super.didUpdateWidget(old);
    // The list changed (reloaded after finalizing or reopening, or the entity filter moved):
    // reload when the shown period is another one, or has changed state (a closed period's rows
    // are a frozen snapshot, an open one's are live).
    final before = _periodOf(old.periods);
    final now = _period;
    if (before?['id'] != now?['id'] || _stateOf(before) != _stateOf(now)) _load();
  }

  /// What makes the summary's rows change for the same period.
  static String _stateOf(Map<String, dynamic>? p) => p == null ? '' : '${p['status']}|${p['version']}|${p['closed_at']}|${p['reopened_at']}|${p['last_validation_status']}';

  _Rec? _periodOf(List<_Rec> periods) {
    if (_periodId != null) {
      for (final p in periods) {
        if (p['id'] == _periodId) return p;
      }
    }
    return pickDefaultPeriod(periods, widget.today);
  }

  Future<void> _load() async {
    final period = _period;
    final mine = ++_request;
    setState(() {
      _rows = null;
      _error = null;
    });
    if (period == null) return;
    try {
      final client = ref.read(apiClientProvider);
      final out = <_Rec>[];
      for (var page = 1; page <= 50; page++) {
        final env = await client.getList<_Rec>('/attendance-periods/${period['id']}/summary', query: PageQuery(page: page, perPage: 100), parseItem: (d) => d as _Rec);
        out.addAll(env.data);
        if (env.pagination == null || !env.pagination!.hasNext) break;
      }
      if (mounted && mine == _request) setState(() => _rows = out);
    } catch (e) {
      final message = e is ApiError ? (e.status == 403 ? "You don't have permission to view this." : e.message) : 'Something went wrong.';
      if (mounted && mine == _request) setState(() => _error = message);
    }
  }

  Widget _stat(String label, String value) => Container(
        width: 150,
        padding: const EdgeInsets.all(12),
        decoration: BoxDecoration(color: Theme.of(context).colorScheme.surfaceContainerLow, borderRadius: BorderRadius.circular(14)),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(label, style: TextStyle(fontSize: 11.5, color: Theme.of(context).colorScheme.onSurfaceVariant)),
          const SizedBox(height: 2),
          Text(value, style: const TextStyle(fontSize: 18, fontWeight: FontWeight.w800)),
        ]),
      );

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final period = _period;
    final list = _sorted;

    Widget body;
    if (period == null) {
      body = const Text('No attendance period to summarise. Open a period for a company first.');
    } else if (_error != null) {
      body = Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text(_error!, style: TextStyle(color: theme.colorScheme.error)),
        TextButton(onPressed: _load, child: const Text('Try again')),
      ]);
    } else if (_rows == null) {
      body = const Padding(padding: EdgeInsets.all(12), child: Center(child: CircularProgressIndicator()));
    } else {
      final t = sumPeriodSummary(_rows!);
      body = Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Wrap(spacing: 8, crossAxisAlignment: WrapCrossAlignment.center, children: [
          StatusChip(label: t.frozen ? 'Frozen snapshot' : 'Live preview', tone: t.frozen ? Tone.neutral : Tone.info, dot: false),
          Text('${t.employees} employee${t.employees == 1 ? '' : 's'}', style: TextStyle(fontSize: 12, color: theme.colorScheme.onSurfaceVariant)),
        ]),
        const SizedBox(height: 10),
        Wrap(spacing: 8, runSpacing: 8, children: [
          for (final (label, field) in periodDayFields) _stat(label, formatDays(t.values[field])),
          _stat('Overtime', formatMinutes(t.otMinutes)),
          _stat('Late count', '${t.lateCount}'),
        ]),
      ]);
    }

    return AppCard(
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text('Monthly attendance summary', style: theme.textTheme.titleMedium?.copyWith(fontWeight: FontWeight.w700)),
        Text('Employee-days across the period, as Payroll will read them.', style: TextStyle(fontSize: 12, color: theme.colorScheme.onSurfaceVariant)),
        const SizedBox(height: 10),
        if (period != null && list.length > 1)
          DropdownButton<String>(
            isExpanded: true,
            value: period['id'] as String,
            items: [for (final p in list) DropdownMenuItem(value: p['id'] as String, child: Text(periodTitle(p), overflow: TextOverflow.ellipsis))],
            onChanged: (id) {
              setState(() => _periodId = id);
              _load();
            },
          ),
        body,
      ]),
    );
  }
}
