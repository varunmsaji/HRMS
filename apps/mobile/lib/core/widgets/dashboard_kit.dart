import 'dart:math' as math;

import 'package:flutter/material.dart';
import 'package:flutter/services.dart' show SystemUiOverlayStyle;

import '../theme/employee_tokens.dart';

/// Shared building blocks for the employee Home and the employer dashboard, so both read as one
/// product: navy header, stat tiles, white panels and two compact charts. Colours come from
/// [EmployeeTokens] (which falls back to the active scheme) except the brand accents below.
const dashNavy = Color(0xFF0B1D4D);
const dashBlue = Color(0xFF1E3A8A);
const dashCyan = Color(0xFF00C2FF);

/// Gradient header with a title, a subtitle line and an optional trailing widget.
class DashHeader extends StatelessWidget {
  const DashHeader({super.key, required this.title, this.subtitle, this.detail, this.trailing});

  final String title;
  final String? subtitle;
  final String? detail;
  final Widget? trailing;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return AnnotatedRegion<SystemUiOverlayStyle>(
      value: SystemUiOverlayStyle.light,
      child: DecoratedBox(
        decoration: const BoxDecoration(
          gradient: LinearGradient(begin: Alignment.topLeft, end: Alignment.bottomRight, colors: [dashNavy, dashBlue]),
          borderRadius: BorderRadius.vertical(bottom: Radius.circular(24)),
        ),
        child: SafeArea(
          bottom: false,
          child: Padding(
            padding: const EdgeInsets.fromLTRB(20, 16, 12, 20),
            child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Expanded(
                child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Text(title, style: theme.textTheme.headlineSmall?.copyWith(color: Colors.white, fontWeight: FontWeight.w700)),
                  if (subtitle != null) Padding(padding: const EdgeInsets.only(top: 4), child: Text(subtitle!, style: theme.textTheme.bodyMedium?.copyWith(color: Colors.white.withValues(alpha: 0.9)))),
                  if (detail != null) Padding(padding: const EdgeInsets.only(top: 2), child: Text(detail!, style: theme.textTheme.bodySmall?.copyWith(color: Colors.white.withValues(alpha: 0.7)))),
                ]),
              ),
              if (trailing != null) trailing!,
            ]),
          ),
        ),
      ),
    );
  }
}

/// One headline figure: icon disc, small caps label, large value, one-line hint.
class StatTile extends StatelessWidget {
  const StatTile({super.key, required this.icon, required this.label, required this.value, this.hint, this.accent = dashBlue});

  final IconData icon;
  final String label;
  final String value;
  final String? hint;
  final Color accent;

  @override
  Widget build(BuildContext context) {
    final t = EmployeeTokens.of(context);
    final theme = Theme.of(context);
    return Container(
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(color: t.sheet, borderRadius: BorderRadius.circular(16), border: Border.all(color: t.line)),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, mainAxisSize: MainAxisSize.min, children: [
        Container(
          width: 36,
          height: 36,
          decoration: BoxDecoration(color: accent.withValues(alpha: 0.12), shape: BoxShape.circle),
          child: Icon(icon, size: 18, color: accent),
        ),
        const SizedBox(height: 10),
        Text(label.toUpperCase(), maxLines: 1, overflow: TextOverflow.ellipsis, style: theme.textTheme.labelSmall?.copyWith(color: t.inkSecondary, letterSpacing: 0.6, fontWeight: FontWeight.w600)),
        const SizedBox(height: 2),
        FittedBox(fit: BoxFit.scaleDown, alignment: Alignment.centerLeft, child: Text(value, style: theme.textTheme.headlineSmall?.copyWith(color: t.ink, fontWeight: FontWeight.w800))),
        if (hint != null) Text(hint!, maxLines: 1, overflow: TextOverflow.ellipsis, style: theme.textTheme.bodySmall?.copyWith(color: t.inkSecondary)),
      ]),
    );
  }
}

/// Two columns of [StatTile]s.
class StatGrid extends StatelessWidget {
  const StatGrid({super.key, required this.tiles});
  final List<StatTile> tiles;

  @override
  Widget build(BuildContext context) {
    final rows = <Widget>[];
    for (var i = 0; i < tiles.length; i += 2) {
      if (i > 0) rows.add(const SizedBox(height: 12));
      rows.add(IntrinsicHeight(
        child: Row(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          Expanded(child: tiles[i]),
          const SizedBox(width: 12),
          Expanded(child: i + 1 < tiles.length ? tiles[i + 1] : const SizedBox.shrink()),
        ]),
      ));
    }
    return Padding(padding: const EdgeInsets.symmetric(horizontal: 16), child: Column(children: rows));
  }
}

/// White rounded panel with a title and an optional trailing action.
class DashPanel extends StatelessWidget {
  const DashPanel({super.key, required this.title, required this.child, this.caption, this.actionLabel, this.onAction});

  final String title;
  final String? caption;
  final String? actionLabel;
  final VoidCallback? onAction;
  final Widget child;

  @override
  Widget build(BuildContext context) {
    final t = EmployeeTokens.of(context);
    final theme = Theme.of(context);
    return Padding(
      padding: const EdgeInsets.fromLTRB(16, 16, 16, 0),
      child: Container(
        width: double.infinity,
        padding: const EdgeInsets.all(16),
        decoration: BoxDecoration(color: t.sheet, borderRadius: BorderRadius.circular(16), border: Border.all(color: t.line)),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Row(children: [
            Expanded(
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Semantics(header: true, child: Text(title, style: theme.textTheme.titleMedium?.copyWith(color: t.ink, fontWeight: FontWeight.w700))),
                if (caption != null) Text(caption!, style: theme.textTheme.bodySmall?.copyWith(color: t.inkSecondary)),
              ]),
            ),
            if (actionLabel != null) TextButton(onPressed: onAction, child: Text(actionLabel!)),
          ]),
          const SizedBox(height: 12),
          child,
        ]),
      ),
    );
  }
}

/// One slice of a [DonutChart].
class DonutSegment {
  const DonutSegment(this.label, this.value, this.color);
  final String label;
  final num value;
  final Color color;
}

/// Ring chart with the total in the middle and a legend underneath (a legend, not side labels,
/// so it fits a phone width).
class DonutChart extends StatelessWidget {
  const DonutChart({super.key, required this.segments, required this.centerLabel, this.semanticLabel});

  final List<DonutSegment> segments;
  final String centerLabel;
  final String? semanticLabel;

  @override
  Widget build(BuildContext context) {
    final t = EmployeeTokens.of(context);
    final theme = Theme.of(context);
    final total = segments.fold<num>(0, (s, e) => s + e.value);
    final shown = segments.where((s) => s.value > 0).toList();
    return Semantics(
      label: semanticLabel ?? '$centerLabel ${_n(total)}: ${shown.map((s) => '${s.label} ${_n(s.value)}').join(', ')}',
      child: Column(children: [
        SizedBox(
          width: 150,
          height: 150,
          child: Stack(alignment: Alignment.center, children: [
            CustomPaint(size: const Size.square(150), painter: _DonutPainter(shown, t.line)),
            Column(mainAxisSize: MainAxisSize.min, children: [
              Text(_n(total), style: theme.textTheme.headlineSmall?.copyWith(color: t.ink, fontWeight: FontWeight.w800)),
              Text(centerLabel.toUpperCase(), style: theme.textTheme.labelSmall?.copyWith(color: t.inkSecondary, letterSpacing: 0.6)),
            ]),
          ]),
        ),
        const SizedBox(height: 12),
        Wrap(spacing: 16, runSpacing: 6, alignment: WrapAlignment.center, children: [
          for (final s in shown)
            Row(mainAxisSize: MainAxisSize.min, children: [
              Container(width: 8, height: 8, decoration: BoxDecoration(color: s.color, shape: BoxShape.circle)),
              const SizedBox(width: 6),
              Text('${s.label} ${_n(s.value)}', style: theme.textTheme.bodySmall?.copyWith(color: t.inkSecondary)),
            ]),
        ]),
      ]),
    );
  }
}

String _n(num v) => v == v.roundToDouble() ? v.toInt().toString() : v.toStringAsFixed(1);

class _DonutPainter extends CustomPainter {
  _DonutPainter(this.segments, this.track);
  final List<DonutSegment> segments;
  final Color track;

  @override
  void paint(Canvas canvas, Size size) {
    const stroke = 16.0;
    final rect = Offset.zero & size;
    final arc = rect.deflate(stroke / 2);
    final paint = Paint()
      ..style = PaintingStyle.stroke
      ..strokeWidth = stroke;
    canvas.drawArc(arc, 0, math.pi * 2, false, paint..color = track);
    final total = segments.fold<num>(0, (s, e) => s + e.value);
    if (total <= 0) return;
    var start = -math.pi / 2;
    for (final s in segments) {
      final sweep = (s.value / total) * math.pi * 2;
      canvas.drawArc(arc, start, math.max(sweep - (segments.length > 1 ? 0.03 : 0), 0.001), false, paint..color = s.color);
      start += sweep;
    }
  }

  @override
  bool shouldRepaint(_DonutPainter old) => old.segments != segments || old.track != track;
}

/// One bar of a [BarChart].
class BarDatum {
  const BarDatum(this.label, this.value, {this.highlight = false});
  final String label;
  final double value;
  final bool highlight;
}

/// Simple vertical bars with the value above each non-zero bar; the highlighted one is cyan.
class BarChart extends StatelessWidget {
  const BarChart({super.key, required this.bars, this.height = 150, this.unit = 'h', this.semanticLabel});

  final List<BarDatum> bars;
  final double height;
  final String unit;
  final String? semanticLabel;

  @override
  Widget build(BuildContext context) {
    final t = EmployeeTokens.of(context);
    final theme = Theme.of(context);
    final max = bars.fold<double>(8, (m, b) => math.max(m, b.value));
    return Semantics(
      label: semanticLabel ?? bars.map((b) => '${b.label} ${_n(b.value)}$unit').join(', '),
      child: SizedBox(
        height: height + 22,
        child: Row(crossAxisAlignment: CrossAxisAlignment.end, children: [
          for (final b in bars)
            Expanded(
              child: Column(mainAxisAlignment: MainAxisAlignment.end, children: [
                if (b.value > 0) Text('${_n(b.value)}$unit', maxLines: 1, style: theme.textTheme.labelSmall?.copyWith(color: t.inkSecondary, fontSize: 10)),
                const SizedBox(height: 2),
                Container(
                  width: 18,
                  height: math.max(b.value / max * (height - 16), b.value > 0 ? 3 : 2),
                  decoration: BoxDecoration(
                    color: b.value == 0 ? t.line : (b.highlight ? dashCyan : dashBlue),
                    borderRadius: const BorderRadius.vertical(top: Radius.circular(5)),
                  ),
                ),
                const SizedBox(height: 4),
                Text(b.label, style: theme.textTheme.labelSmall?.copyWith(color: b.highlight ? t.ink : t.inkSecondary, fontWeight: b.highlight ? FontWeight.w700 : FontWeight.w400)),
              ]),
            ),
        ]),
      ),
    );
  }
}

/// Compact row for short lists inside a [DashPanel] (needs-attention, activity, approvals).
class DashListRow extends StatelessWidget {
  const DashListRow({super.key, required this.icon, required this.title, this.caption, this.trailing, this.onTap});

  final IconData icon;
  final String title;
  final String? caption;
  final Widget? trailing;
  final VoidCallback? onTap;

  @override
  Widget build(BuildContext context) {
    final t = EmployeeTokens.of(context);
    final theme = Theme.of(context);
    return InkWell(
      onTap: onTap,
      borderRadius: BorderRadius.circular(12),
      child: ConstrainedBox(
        constraints: const BoxConstraints(minHeight: 48),
        child: Padding(
          padding: const EdgeInsets.symmetric(vertical: 8),
          child: Row(children: [
            Container(width: 36, height: 36, decoration: BoxDecoration(color: t.actionSubtle, shape: BoxShape.circle), child: Icon(icon, size: 18, color: t.action)),
            const SizedBox(width: 12),
            Expanded(
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Text(title, maxLines: 2, overflow: TextOverflow.ellipsis, style: theme.textTheme.bodyMedium?.copyWith(color: t.ink, fontWeight: FontWeight.w600)),
                if (caption != null) Text(caption!, maxLines: 1, overflow: TextOverflow.ellipsis, style: theme.textTheme.bodySmall?.copyWith(color: t.inkSecondary)),
              ]),
            ),
            if (trailing != null) trailing! else if (onTap != null) Icon(Icons.chevron_right, color: t.inkTertiary),
          ]),
        ),
      ),
    );
  }
}
