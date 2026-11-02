import 'dart:async';

import 'package:flutter/material.dart';

import '../../../core/theme/employee_tokens.dart';
import '../domain/punch_warning.dart';

/// Warning card shown when the server refuses a punch that repeats the previous one. Nothing was
/// recorded, so the only action is to dismiss. For a too-soon punch it shows a live countdown to
/// the moment punching is allowed again.
Future<void> showPunchWarningCard(BuildContext context, PunchWarning warning) {
  return showDialog<void>(
    context: context,
    builder: (dialogContext) => Dialog(
      backgroundColor: Colors.transparent,
      insetPadding: const EdgeInsets.symmetric(horizontal: 24, vertical: 24),
      child: _PunchWarningCard(warning: warning, onClose: () => Navigator.of(dialogContext).pop()),
    ),
  );
}

class _PunchWarningCard extends StatefulWidget {
  const _PunchWarningCard({required this.warning, required this.onClose});

  final PunchWarning warning;
  final VoidCallback onClose;

  @override
  State<_PunchWarningCard> createState() => _PunchWarningCardState();
}

class _PunchWarningCardState extends State<_PunchWarningCard> {
  Timer? _timer;
  late int _secondsLeft = widget.warning.retryAfterSeconds ?? 0;

  @override
  void initState() {
    super.initState();
    if (_secondsLeft > 0) {
      _timer = Timer.periodic(const Duration(seconds: 1), (timer) {
        if (!mounted) return;
        setState(() => _secondsLeft = _secondsLeft > 0 ? _secondsLeft - 1 : 0);
        if (_secondsLeft == 0) timer.cancel();
      });
    }
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  String _clock(int seconds) => '${seconds ~/ 60}:${(seconds % 60).toString().padLeft(2, '0')}';

  @override
  Widget build(BuildContext context) {
    final t = EmployeeTokens.of(context);
    final theme = Theme.of(context);
    final warning = widget.warning;
    final amber = t.warningText;
    final localizations = MaterialLocalizations.of(context);
    final use24h = MediaQuery.alwaysUse24HourFormatOf(context);
    final lastTime = localizations.formatTimeOfDay(TimeOfDay.fromDateTime(warning.lastPunchTime), alwaysUse24HourFormat: use24h);
    final tooSoon = warning.kind == PunchWarningKind.tooSoon;

    return Container(
      constraints: const BoxConstraints(maxWidth: 400),
      decoration: BoxDecoration(
        color: t.sheet,
        borderRadius: BorderRadius.circular(EmployeeTokens.radiusSheet),
        border: Border.all(color: amber.withValues(alpha: 0.45)),
      ),
      clipBehavior: Clip.antiAlias,
      child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        Container(
          color: amber.withValues(alpha: 0.12),
          padding: const EdgeInsets.fromLTRB(20, 18, 20, 14),
          child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Icon(Icons.warning_amber_rounded, color: amber, size: 30),
            const SizedBox(width: 12),
            Expanded(child: Text(warning.title, style: theme.textTheme.titleLarge?.copyWith(color: t.ink, fontWeight: FontWeight.w700))),
          ]),
        ),
        Padding(
          padding: const EdgeInsets.fromLTRB(20, 16, 20, 4),
          child: Text(warning.explanation, style: theme.textTheme.bodyMedium?.copyWith(color: t.inkSecondary, height: 1.4)),
        ),
        Padding(
          padding: const EdgeInsets.fromLTRB(20, 12, 20, 4),
          child: Container(
            padding: const EdgeInsets.all(14),
            decoration: BoxDecoration(color: t.inset, borderRadius: BorderRadius.circular(EmployeeTokens.radiusSurface)),
            child: Column(children: [
              _Row(label: 'Your last punch', value: '${warning.lastWasIn ? 'Punch in' : 'Punch out'} at $lastTime'),
              if (tooSoon) ...[
                const SizedBox(height: 10),
                _Row(
                  label: 'You can punch again in',
                  value: _secondsLeft > 0 ? _clock(_secondsLeft) : 'now',
                  emphasize: true,
                  color: _secondsLeft > 0 ? amber : t.successText,
                ),
              ] else ...[
                const SizedBox(height: 10),
                _Row(label: 'Next punch', value: warning.lastWasIn ? 'Punch out' : 'Punch in', emphasize: true),
              ],
            ]),
          ),
        ),
        Padding(
          padding: const EdgeInsets.fromLTRB(20, 14, 20, 18),
          child: FilledButton(onPressed: widget.onClose, child: Text(tooSoon && _secondsLeft == 0 ? 'OK, got it' : 'Got it')),
        ),
      ]),
    );
  }
}

class _Row extends StatelessWidget {
  const _Row({required this.label, required this.value, this.emphasize = false, this.color});

  final String label;
  final String value;
  final bool emphasize;
  final Color? color;

  @override
  Widget build(BuildContext context) {
    final t = EmployeeTokens.of(context);
    final theme = Theme.of(context);
    return Row(mainAxisAlignment: MainAxisAlignment.spaceBetween, children: [
      Flexible(child: Text(label, style: theme.textTheme.bodyMedium?.copyWith(color: t.inkSecondary))),
      const SizedBox(width: 12),
      Text(value, style: theme.textTheme.bodyMedium?.copyWith(color: color ?? t.ink, fontWeight: emphasize ? FontWeight.w800 : FontWeight.w600, fontFeatures: const [FontFeature.tabularFigures()])),
    ]);
  }
}
