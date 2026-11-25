import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../api/api_error.dart';
import '../theme/app_theme.dart';
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
    this.pendingHint,
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

  /// A line shown above the cards of the pending tab (how to use the swipe shortcut).
  final String? pendingHint;

  @override
  State<DecisionCenterView<T>> createState() => _DecisionCenterViewState<T>();
}

class _DecisionCenterViewState<T> extends State<DecisionCenterView<T>> {
  late String _tab = widget.tabs.first.$1;
  T? _data;
  bool _loading = true;
  ApiError? _error;
  int _request = 0;

  /// The headline figures start folded into one line, so the requests themselves begin near the
  /// top of the screen (audit MOB-UX-016).
  bool _showFigures = false;

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
          if (data != null)
            _StatSummary(
              stats: widget.stats(data),
              expanded: _showFigures,
              onToggle: () => setState(() => _showFigures = !_showFigures),
            ),
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
            StateMessage(icon: Icons.cloud_off_rounded, tone: Tone.danger, title: 'Couldn\'t load requests', message: _error!.status == 403 ? widget.forbiddenMessage : describeApiError(_error!), actionLabel: 'Try again', onAction: _load)
          else if (_loading)
            const ListSkeleton(count: 3, embedded: true)
          else if (cards.isEmpty)
            _tab == 'pending'
                ? StateMessage(icon: widget.emptyIcon, tone: Tone.success, title: 'Nothing awaiting your decision', message: 'New requests appear here as soon as they are submitted.')
                : StateMessage(icon: widget.emptyIcon, title: 'Nothing here yet', message: 'Requests appear here once they are decided.')
          else ...[
            if (_tab == 'pending' && widget.pendingHint != null)
              Padding(padding: const EdgeInsets.only(bottom: 10), child: Text(widget.pendingHint!, style: TextStyle(fontSize: 12, color: scheme.onSurfaceVariant))),
            for (final card in cards) Padding(padding: const EdgeInsets.only(bottom: 12), child: card),
            if (data != null && widget.count(data, _tab) > cards.length)
              Text('Showing ${cards.length} of ${widget.count(data, _tab)}. ${widget.narrowHint}', textAlign: TextAlign.center, style: TextStyle(fontSize: 12, color: scheme.onSurfaceVariant)),
          ],
        ],
      ),
    );
  }
}

/// "5 pending requests · 2 on leave today", with the first figure's note, and a toggle that opens
/// the full figures below.
class _StatSummary extends StatelessWidget {
  const _StatSummary({required this.stats, required this.expanded, required this.onToggle});
  final List<DecisionStat> stats;
  final bool expanded;
  final VoidCallback onToggle;

  @override
  Widget build(BuildContext context) {
    if (stats.isEmpty) return const SizedBox.shrink();
    final theme = Theme.of(context);
    final muted = theme.colorScheme.onSurfaceVariant;
    final line = [for (final s in stats.take(2)) '${s.value} ${s.label[0].toLowerCase()}${s.label.substring(1)}'].join(' · ');
    final first = stats.first;
    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      AppCard(
        onTap: onToggle,
        padding: const EdgeInsets.fromLTRB(14, 12, 8, 12),
        child: Row(children: [
          Expanded(
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text(line, style: const TextStyle(fontWeight: FontWeight.w700)),
              if (first.note != null) ...[const SizedBox(height: 2), Text(first.note!, style: TextStyle(fontSize: 12, color: muted))],
              if (first.needsAction) ...[
                const SizedBox(height: 2),
                Text('Action required', style: TextStyle(fontSize: 12, fontWeight: FontWeight.w600, color: toneColors(context, Tone.warning).fg)),
              ],
            ]),
          ),
          Semantics(
            label: expanded ? 'Hide figures' : 'Show all figures',
            excludeSemantics: true,
            child: Icon(expanded ? Icons.expand_less_rounded : Icons.expand_more_rounded, color: muted),
          ),
        ]),
      ),
      if (expanded) ...[const SizedBox(height: 10), _StatGrid(stats: stats)],
    ]);
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
          // "Reject", the same word the dialog and the detail screen use (MOB-UX-014).
          Expanded(child: OutlinedButton(onPressed: onDecline, child: const Text('Reject'))),
          const SizedBox(width: 8),
          Expanded(child: FilledButton(onPressed: onApprove, child: Text(approveLabel))),
        ]),
        const SizedBox(height: 4),
      ],
      Align(alignment: Alignment.centerLeft, child: TextButton(onPressed: onDetails, child: Text(detailsLabel))),
    ]);
  }
}


/// A shortcut for the Reject and Approve buttons of a request card: swipe right to approve, left to
/// reject.
///
/// A swipe never decides anything by itself. It opens exactly what the button opens (the review
/// dialog, with its rules, its optional comment and the required reason for a rejection), and the
/// card springs back until that is confirmed. So an accidental swipe costs one dismissed dialog,
/// not a decision that moves a leave balance or a payroll input. The buttons stay on the card for
/// anyone who prefers them or uses a screen reader.
class SwipeToDecide extends StatelessWidget {
  const SwipeToDecide({super.key, required this.id, required this.enabled, required this.approveLabel, required this.onApprove, required this.onReject, required this.child});

  /// The request's id, so each card is its own swipe target.
  final String id;

  /// False when the viewer cannot decide this request (not pending, or their own).
  final bool enabled;
  final String approveLabel;
  final VoidCallback onApprove;
  final VoidCallback onReject;
  final Widget child;

  @override
  Widget build(BuildContext context) {
    if (!enabled) return child;
    final approve = toneColors(context, Tone.success);
    final reject = toneColors(context, Tone.danger);
    Widget hint(Color bg, Color fg, IconData icon, String label, Alignment align) => Container(
          alignment: align,
          padding: const EdgeInsets.symmetric(horizontal: 20),
          decoration: BoxDecoration(color: bg, borderRadius: BorderRadius.circular(AppRadii.card)),
          child: Row(mainAxisSize: MainAxisSize.min, children: [
            if (align == Alignment.centerLeft) Icon(icon, color: fg),
            const SizedBox(width: 8),
            Text(label, style: TextStyle(color: fg, fontWeight: FontWeight.w700)),
            const SizedBox(width: 8),
            if (align == Alignment.centerRight) Icon(icon, color: fg),
          ]),
        );
    return Dismissible(
      key: ValueKey('swipe-decide-$id'),
      background: hint(approve.bg, approve.fg, Icons.check_circle_outline_rounded, approveLabel, Alignment.centerLeft),
      secondaryBackground: hint(reject.bg, reject.fg, Icons.cancel_outlined, 'Reject', Alignment.centerRight),
      dismissThresholds: const {DismissDirection.startToEnd: 0.4, DismissDirection.endToStart: 0.4},
      confirmDismiss: (direction) async {
        HapticFeedback.selectionClick();
        // Open the same step the button opens, then let the card go back where it was.
        if (direction == DismissDirection.startToEnd) {
          onApprove();
        } else {
          onReject();
        }
        return false;
      },
      child: child,
    );
  }
}
