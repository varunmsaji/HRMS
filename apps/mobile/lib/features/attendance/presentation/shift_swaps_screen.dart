import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api/api_error.dart';
import '../../../core/auth/permissions.dart';
import '../../../core/time.dart';
import '../../../core/widgets/ui.dart';
import '../../auth/state/auth_controller.dart';
import '../../shell/more_action.dart';
import '../data/schedule_repository.dart';
import '../domain/weekly_schedule.dart';

/// Shift swaps — mirrors the swap queue on the web Schedule page. An employee asks a colleague to
/// swap shifts for a day, the colleague agrees (or turns it down), and a roster manager approves.
class ShiftSwapsScreen extends ConsumerStatefulWidget {
  const ShiftSwapsScreen({super.key});

  @override
  ConsumerState<ShiftSwapsScreen> createState() => _ShiftSwapsScreenState();
}

class _ShiftSwapsScreenState extends ConsumerState<ShiftSwapsScreen> {
  List<SwapRequest>? _swaps;
  bool _loading = true;
  ApiError? _error;
  String? _busyId;

  ScheduleRepository get _repo => ref.read(scheduleRepositoryProvider);

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final swaps = await _repo.listSwaps();
      if (mounted) setState(() => _swaps = swaps);
    } catch (e) {
      if (mounted) setState(() => _error = e is ApiError ? e : ApiError(status: 0, code: 'UNKNOWN_ERROR', message: 'Something went wrong.'));
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  void _toast(String m) => ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(m)));

  Future<void> _act(SwapRequest swap, Future<SwapRequest> Function() call, String done) async {
    setState(() => _busyId = swap.id);
    try {
      await call();
      _toast(done);
    } catch (e) {
      _toast(e is ApiError ? e.message : 'Something went wrong.');
    }
    if (mounted) setState(() => _busyId = null);
    await _load();
  }

  Future<void> _request() async {
    final sent = await showModalBottomSheet<bool>(
      context: context,
      isScrollControlled: true,
      showDragHandle: true,
      builder: (_) => const RequestSwapSheet(),
    );
    if (sent == true) {
      _toast('Swap requested. Your colleague needs to agree, then a manager approves.');
      _load();
    }
  }

  @override
  Widget build(BuildContext context) {
    final user = ref.watch(authControllerProvider).user;
    final me = user?.employeeId;
    final canManage = (user?.permissions ?? const <String>[]).contains(attendanceRosterManage);
    final swaps = _swaps ?? const <SwapRequest>[];
    // What needs this person first: an answer they owe, or (for a manager) a swap ready to decide.
    final action = [for (final s in swaps) if (s.isPending && (s.needsAnswerFrom(me) || (canManage && s.counterpartConsented))) s];
    final waiting = [for (final s in swaps) if (s.isPending && !action.contains(s)) s];
    final recent = [for (final s in swaps) if (!s.isPending) s];
    return Scaffold(
      appBar: AppBar(title: const Text('Shift swaps'), actions: const [MoreAction()]),
      floatingActionButton: me == null ? null : FloatingActionButton.extended(onPressed: _request, icon: const Icon(Icons.swap_horiz_rounded), label: const Text('Request a swap')),
      body: _loading && _swaps == null
          ? const ListSkeleton()
          : _error != null
              ? StateMessage(icon: Icons.error_outline_rounded, tone: Tone.danger, title: 'Something went wrong', message: _error!.message, actionLabel: 'Retry', onAction: _load)
              : RefreshIndicator(
                  onRefresh: _load,
                  child: swaps.isEmpty
                      ? ListView(children: const [SizedBox(height: 320, child: StateMessage(icon: Icons.swap_horiz_rounded, tone: Tone.neutral, title: 'No swap requests', message: 'Swaps you ask for, or are asked to agree to, show up here.'))])
                      : ListView(
                          padding: const EdgeInsets.fromLTRB(16, 8, 16, 96),
                          children: [
                            if (action.isNotEmpty) ...[
                              const SectionHeader('Needs your action'),
                              for (final s in action) _SwapCard(swap: s, me: me, canManage: canManage, busy: _busyId == s.id, onAct: _act, repo: _repo),
                            ],
                            if (waiting.isNotEmpty) ...[
                              const SectionHeader('Waiting'),
                              for (final s in waiting) _SwapCard(swap: s, me: me, canManage: canManage, busy: _busyId == s.id, onAct: _act, repo: _repo),
                            ],
                            if (recent.isNotEmpty) ...[
                              const SectionHeader('Recent'),
                              for (final s in recent) _SwapCard(swap: s, me: me, canManage: canManage, busy: false, onAct: _act, repo: _repo),
                            ],
                          ],
                        ),
                ),
    );
  }
}

class _SwapCard extends StatelessWidget {
  const _SwapCard({required this.swap, required this.me, required this.canManage, required this.busy, required this.onAct, required this.repo});
  final SwapRequest swap;
  final String? me;
  final bool canManage;
  final bool busy;
  final Future<void> Function(SwapRequest, Future<SwapRequest> Function(), String) onAct;
  final ScheduleRepository repo;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final isRequester = swap.isRequester(me);
    final isCounterpart = swap.isCounterpart(me);
    final needsMyAnswer = swap.needsAnswerFrom(me);
    final tone = toneForStatus(swap.status);
    final note = !swap.isPending
        ? (swap.decisionNote ?? '')
        : swap.counterpartConsented
            ? (swap.coverageOk ? 'Both agreed. Shift targets intact.' : 'Both agreed, but a shift is already below its target.')
            : 'Waiting for ${swap.counterpart.name.split(' ').first} to agree.';
    return Padding(
      padding: const EdgeInsets.only(bottom: 10),
      child: AppCard(
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Row(children: [
            Expanded(child: Text('${longDay(swap.swapDate)} · ${swap.reference}', style: theme.textTheme.titleSmall?.copyWith(fontWeight: FontWeight.w700))),
            StatusChip(label: swap.isPending ? (swap.counterpartConsented ? 'Agreed' : 'Pending') : _title(swap.status), tone: swap.isPending && swap.counterpartConsented ? Tone.info : tone),
          ]),
          const SizedBox(height: 10),
          _Party(party: swap.requester, you: isRequester),
          const Padding(padding: EdgeInsets.symmetric(vertical: 4), child: Icon(Icons.swap_vert_rounded, size: 18)),
          _Party(party: swap.counterpart, you: isCounterpart),
          if (swap.reason != null && swap.reason!.isNotEmpty) Padding(padding: const EdgeInsets.only(top: 8), child: Text('Reason: ${swap.reason}', style: theme.textTheme.bodyMedium)),
          if (note.isNotEmpty) Padding(padding: const EdgeInsets.only(top: 6), child: Text(note, style: theme.textTheme.bodySmall?.copyWith(color: theme.colorScheme.onSurfaceVariant))),
          if (swap.isPending && (isRequester || isCounterpart || canManage))
            Padding(
              padding: const EdgeInsets.only(top: 10),
              child: Wrap(spacing: 8, runSpacing: 8, alignment: WrapAlignment.end, children: [
                if (needsMyAnswer) FilledButton(onPressed: busy ? null : () => onAct(swap, () => repo.consent(swap.id), 'You agreed to the swap.'), child: const Text('Agree')),
                if (isRequester || isCounterpart)
                  OutlinedButton(
                    onPressed: busy ? null : () => onAct(swap, () => repo.withdraw(swap.id), isRequester ? 'Swap request withdrawn.' : 'You turned the swap down.'),
                    child: Text(isRequester ? 'Withdraw' : 'Turn down'),
                  ),
                if (canManage && !isRequester && !isCounterpart) ...[
                  OutlinedButton(onPressed: busy ? null : () => onAct(swap, () => repo.decline(swap.id), 'Swap declined.'), child: const Text('Decline')),
                  Tooltip(
                    message: swap.counterpartConsented ? '' : 'The colleague has not agreed yet',
                    child: FilledButton(onPressed: busy || !swap.counterpartConsented ? null : () => onAct(swap, () => repo.approve(swap.id), 'Swap approved.'), child: const Text('Approve')),
                  ),
                ],
              ]),
            ),
        ]),
      ),
    );
  }

  static String _title(String s) => s.isEmpty ? s : s[0] + s.substring(1).toLowerCase();
}

class _Party extends StatelessWidget {
  const _Party({required this.party, required this.you});
  final SwapParty party;
  final bool you;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Row(children: [
      InitialsAvatar(name: party.name, size: 36),
      const SizedBox(width: 10),
      Expanded(
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(you ? '${party.name} (you)' : party.name, style: theme.textTheme.bodyLarge?.copyWith(fontWeight: FontWeight.w600)),
          Text(party.shiftLabel, style: theme.textTheme.bodySmall?.copyWith(color: theme.colorScheme.onSurfaceVariant)),
        ]),
      ),
    ]);
  }
}

/// Bottom sheet to ask a colleague for a swap: pick the day, then someone on a different shift.
class RequestSwapSheet extends ConsumerStatefulWidget {
  const RequestSwapSheet({super.key});

  @override
  ConsumerState<RequestSwapSheet> createState() => _RequestSwapSheetState();
}

class _RequestSwapSheetState extends ConsumerState<RequestSwapSheet> {
  late String _date;
  late final String _today;
  List<SwapCandidate>? _candidates;
  String _counterpart = '';
  final _reason = TextEditingController();
  bool _saving = false;
  String? _error;
  int _request = 0;

  @override
  void initState() {
    super.initState();
    final zone = ref.read(authControllerProvider).user?.companyTimezone ?? 'Asia/Kolkata';
    _today = businessToday(zone);
    _date = addDaysIso(_today, 1);
    _loadCandidates();
  }

  @override
  void dispose() {
    _reason.dispose();
    super.dispose();
  }

  Future<void> _loadCandidates() async {
    final mine = ++_request;
    setState(() {
      _candidates = null;
      _counterpart = '';
    });
    try {
      final rows = await ref.read(scheduleRepositoryProvider).candidates(_date);
      if (mounted && mine == _request) setState(() => _candidates = rows);
    } catch (_) {
      if (mounted && mine == _request) setState(() => _candidates = const []);
    }
  }

  Future<void> _pickDate() async {
    final picked = await showDatePicker(context: context, initialDate: DateTime.parse(_date), firstDate: DateTime.parse(_today), lastDate: DateTime.parse(_today).add(const Duration(days: 180)));
    if (picked == null) return;
    setState(() => _date = '${picked.year.toString().padLeft(4, '0')}-${picked.month.toString().padLeft(2, '0')}-${picked.day.toString().padLeft(2, '0')}');
    _loadCandidates();
  }

  Future<void> _submit() async {
    setState(() {
      _saving = true;
      _error = null;
    });
    try {
      await ref.read(scheduleRepositoryProvider).requestSwap(counterpartEmployeeId: _counterpart, date: _date, reason: _reason.text);
      if (mounted) Navigator.of(context).pop(true);
    } catch (e) {
      if (mounted) setState(() => _error = e is ApiError ? e.message : 'Something went wrong.');
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final candidates = _candidates;
    return Padding(
      padding: EdgeInsets.fromLTRB(16, 0, 16, 16 + MediaQuery.of(context).viewInsets.bottom),
      child: SingleChildScrollView(
        child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text('Request a shift swap', style: theme.textTheme.titleLarge?.copyWith(fontWeight: FontWeight.w700)),
          const SizedBox(height: 4),
          Text('You both need a different published shift on the day.', style: theme.textTheme.bodyMedium?.copyWith(color: theme.colorScheme.onSurfaceVariant)),
          const SizedBox(height: 14),
          OutlinedButton.icon(onPressed: _saving ? null : _pickDate, icon: const Icon(Icons.event_outlined), label: Text(longDay(_date))),
          const SizedBox(height: 12),
          if (candidates == null)
            const LinearProgressIndicator()
          else if (candidates.isEmpty)
            Text('No one in your department is on a different shift that day.', style: theme.textTheme.bodyMedium)
          else
            DropdownButtonFormField<String>(
              value: _counterpart.isEmpty ? null : _counterpart,
              isExpanded: true,
              decoration: const InputDecoration(labelText: 'Swap with'),
              items: [for (final c in candidates) DropdownMenuItem(value: c.employeeId, child: Text('${c.name} · ${c.shiftName}', overflow: TextOverflow.ellipsis))],
              onChanged: _saving ? null : (v) => setState(() => _counterpart = v ?? ''),
            ),
          const SizedBox(height: 12),
          TextField(controller: _reason, enabled: !_saving, maxLength: 500, maxLines: 2, decoration: const InputDecoration(labelText: 'Reason (optional)')),
          if (_error != null) Padding(padding: const EdgeInsets.only(bottom: 8), child: Text(_error!, style: TextStyle(color: theme.colorScheme.error))),
          Row(children: [
            Expanded(child: OutlinedButton(onPressed: _saving ? null : () => Navigator.of(context).pop(false), child: const Text('Cancel'))),
            const SizedBox(width: 12),
            Expanded(child: FilledButton(onPressed: _saving || _counterpart.isEmpty ? null : _submit, child: Text(_saving ? 'Sending…' : 'Send request'))),
          ]),
        ]),
      ),
    );
  }
}
