import 'package:flutter/material.dart';

import '../api/api_error.dart';
import '../widgets/ui.dart';

/// One headline figure at the top of a decision centre.
class DecisionStat {
  const DecisionStat(this.label, this.value, {this.note, this.needsAction = false});
  final String label;
  final String value;
  final String? note;
  final bool needsAction;
}

/// The frame shared by the approver screens for leave and attendance corrections (web
/// `components/*/decision-center.tsx`): headline figures, status tabs with counts, and the request
/// cards of the chosen tab. Every figure is the backend's; a slower answer for a tab the user has
/// left never overwrites the current one.
class DecisionCenterView<T> extends StatefulWidget {
  const DecisionCenterView({
    super.key,
    required this.tabs,
    required this.load,
    required this.stats,
    required this.count,
    required this.cards,
    required this.forbiddenMessage,
    required this.narrowHint,
    required this.emptyIcon,
  });

  /// Tab key and label.
  final List<(String, String)> tabs;
  final Future<T> Function(String tab) load;
  final List<DecisionStat> Function(T data) stats;

  /// How many requests the tab holds in all (the server sends at most a page of them).
  final int Function(T data, String tab) count;

  /// The cards of the current answer. Call the callback after a decision to refresh.
  final List<Widget> Function(BuildContext context, T data, VoidCallback reload) cards;
  final String forbiddenMessage;

  /// Where to go for the rest when the server sent only part of a tab.
  final String narrowHint;
  final IconData emptyIcon;

  @override
  State<DecisionCenterView<T>> createState() => _DecisionCenterViewState<T>();
}

class _DecisionCenterViewState<T> extends State<DecisionCenterView<T>> {
  late String _tab = widget.tabs.first.$1;
  T? _data;
  bool _loading = true;
  ApiError? _error;
  int _request = 0;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    final mine = ++_request;
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final data = await widget.load(_tab);
      if (mounted && mine == _request) setState(() => _data = data);
    } catch (e) {
      if (mounted && mine == _request) setState(() => _error = e is ApiError ? e : ApiError(status: 0, code: 'UNKNOWN_ERROR', message: 'Something went wrong.'));
    } finally {
      if (mounted && mine == _request) setState(() => _loading = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final data = _data;
    final scheme = Theme.of(context).colorScheme;
    final cards = data == null || _loading ? const <Widget>[] : widget.cards(context, data, _load);
    return RefreshIndicator(
      onRefresh: _load,
      child: ListView(
        padding: const EdgeInsets.fromLTRB(16, 12, 16, 96),
        children: [
          if (data != null) _StatGrid(stats: widget.stats(data)),
          const SizedBox(height: 12),
          Wrap(spacing: 8, runSpacing: 4, children: [
            for (final (key, label) in widget.tabs)
              ChoiceChip(
                label: Text(data == null ? label : '$label (${widget.count(data, key)})'),
                selected: _tab == key,
                labelStyle: TextStyle(fontWeight: FontWeight.w600, color: _tab == key ? scheme.primary : scheme.onSurfaceVariant),
                onSelected: (_) {
                  setState(() => _tab = key);
                  _load();
                },
              ),
          ]),
          const SizedBox(height: 12),
          if (_error != null)
            StateMessage(icon: Icons.error_outline_rounded, tone: Tone.danger, title: 'Something went wrong', message: _error!.status == 403 ? widget.forbiddenMessage : _error!.message, actionLabel: 'Retry', onAction: _load)
          else if (_loading)
            const Padding(padding: EdgeInsets.all(32), child: Center(child: CircularProgressIndicator(strokeWidth: 2.5)))
          else if (cards.isEmpty)
            StateMessage(icon: widget.emptyIcon, title: 'No requests here.', message: 'Nothing to show for this tab.')
          else ...[
            for (final card in cards) Padding(padding: const EdgeInsets.only(bottom: 12), child: card),
            if (data != null && widget.count(data, _tab) > cards.length)
              Text('Showing ${cards.length} of ${widget.count(data, _tab)}. ${widget.narrowHint}', textAlign: TextAlign.center, style: TextStyle(fontSize: 12, color: scheme.onSurfaceVariant)),
          ],
        ],
      ),
    );
  }
}

class _StatGrid extends StatelessWidget {
  const _StatGrid({required this.stats});
  final List<DecisionStat> stats;

  @override
  Widget build(BuildContext context) {
    final muted = Theme.of(context).colorScheme.onSurfaceVariant;
    return LayoutBuilder(
      builder: (context, box) {
        final width = (box.maxWidth - 10) / 2;
        return Wrap(spacing: 10, runSpacing: 10, children: [
          for (final s in stats)
            SizedBox(
              width: width,
              child: AppCard(
                child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Text(s.label, style: TextStyle(fontSize: 12, color: muted)),
                  const SizedBox(height: 4),
                  Text(s.value, style: const TextStyle(fontSize: 22, fontWeight: FontWeight.w700)),
                  if (s.needsAction) Padding(padding: const EdgeInsets.only(top: 4), child: Text('Action required', style: TextStyle(fontSize: 12, fontWeight: FontWeight.w600, color: toneColors(context, Tone.warning).fg))),
                  if (s.note != null) Padding(padding: const EdgeInsets.only(top: 4), child: Text(s.note!, style: TextStyle(fontSize: 11, color: muted))),
                ]),
              ),
            ),
        ]);
      },
    );
  }
}

/// A labelled block inside a request card.
class DecisionBlock extends StatelessWidget {
  const DecisionBlock({super.key, required this.title, required this.children, this.trailing});
  final String title;
  final String? trailing;
  final List<Widget> children;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(color: scheme.surfaceContainerHighest.withValues(alpha: 0.5), borderRadius: BorderRadius.circular(10)),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [
          Expanded(child: Text(title.toUpperCase(), style: TextStyle(fontSize: 11, fontWeight: FontWeight.w600, letterSpacing: 0.5, color: scheme.onSurfaceVariant))),
          if (trailing != null) Flexible(child: Text(trailing!, textAlign: TextAlign.end, style: TextStyle(fontSize: 12, fontWeight: FontWeight.w600, color: scheme.primary))),
        ]),
        const SizedBox(height: 8),
        ...children,
      ]),
    );
  }
}

/// Who is asking, shown at the top of a request card.
class DecisionCardHeader extends StatelessWidget {
  const DecisionCardHeader({super.key, required this.name, required this.code, required this.lines, required this.status});
  final String name;
  final String code;
  final List<String> lines;
  final Widget status;

  @override
  Widget build(BuildContext context) {
    final muted = Theme.of(context).colorScheme.onSurfaceVariant;
    return Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
      InitialsAvatar(name: name),
      const SizedBox(width: 10),
      Expanded(
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text('$name ($code)', style: const TextStyle(fontWeight: FontWeight.w700)),
          for (final l in lines) Text(l, style: TextStyle(fontSize: 12, color: muted)),
          const SizedBox(height: 6),
          // A chip does not wrap; on a narrow phone at large text it shrinks instead of overflowing.
          FittedBox(fit: BoxFit.scaleDown, alignment: Alignment.centerLeft, child: status),
        ]),
      ),
    ]);
  }
}

/// "View details", and Decline and Approve for someone who may decide it.
class DecisionCardFooter extends StatelessWidget {
  const DecisionCardFooter({super.key, required this.detailsLabel, required this.onDetails, required this.approveLabel, this.onDecline, this.onApprove});
  final String detailsLabel;
  final VoidCallback onDetails;
  final String approveLabel;
  final VoidCallback? onDecline;
  final VoidCallback? onApprove;

  @override
  Widget build(BuildContext context) {
    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      if (onApprove != null) ...[
        Row(children: [
          Expanded(child: OutlinedButton(onPressed: onDecline, child: const Text('Decline'))),
          const SizedBox(width: 8),
          Expanded(child: FilledButton(onPressed: onApprove, child: Text(approveLabel))),
        ]),
        const SizedBox(height: 4),
      ],
      Align(alignment: Alignment.centerLeft, child: TextButton(onPressed: onDetails, child: Text(detailsLabel))),
    ]);
  }
}
