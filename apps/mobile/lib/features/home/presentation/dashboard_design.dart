import 'dart:math' as math;

import 'package:flutter/material.dart';

/// Visual building blocks of the employee dashboard design. Presentation only: every value
/// shown is passed in by the screen, which reads it from the API.
abstract final class Dd {
  static const navy = Color(0xFF0A1F5C);
  static const blue = Color(0xFF1668E3);
  static const cyan = Color(0xFF0EA5E9);
  static const canvas = Color(0xFFF5F7FB);
  static const ink = Color(0xFF111827);
  static const muted = Color(0xFF6B7280);
  static const line = Color(0xFFE5E9F2);
  static const green = Color(0xFF16A34A);
  static const red = Color(0xFFB91C1C);
  static const amberBg = Color(0xFFFEF3C7);
  static const amberFg = Color(0xFFB45309);
}

class DdCard extends StatelessWidget {
  const DdCard({super.key, required this.child, this.padding = const EdgeInsets.all(16), this.gradient});
  final Widget child;
  final EdgeInsets padding;
  final Gradient? gradient;

  @override
  Widget build(BuildContext context) => Container(
        padding: padding,
        decoration: BoxDecoration(
          color: Colors.white,
          gradient: gradient,
          borderRadius: BorderRadius.circular(18),
          boxShadow: const [BoxShadow(color: Color(0x0F0A1F5C), blurRadius: 14, offset: Offset(0, 4))],
        ),
        child: child,
      );
}

class DdPill extends StatelessWidget {
  const DdPill({super.key, required this.label, required this.background, required this.foreground, this.icon, this.size = 11});
  final String label;
  final Color background;
  final Color foreground;
  final IconData? icon;
  final double size;

  @override
  Widget build(BuildContext context) => Container(
        padding: const EdgeInsets.symmetric(horizontal: 9, vertical: 4),
        decoration: BoxDecoration(color: background, borderRadius: BorderRadius.circular(20)),
        child: Row(mainAxisSize: MainAxisSize.min, children: [
          if (icon != null) ...[Icon(icon, size: size + 2, color: foreground), const SizedBox(width: 4)],
          Flexible(child: Text(label, overflow: TextOverflow.ellipsis, style: TextStyle(fontSize: size, fontWeight: FontWeight.w600, color: foreground))),
        ]),
      );
}

/// One of the four summary tiles: icon chip + badge on top, big value, caption.
class DdStatTile extends StatelessWidget {
  const DdStatTile({
    super.key,
    required this.icon,
    required this.iconColor,
    required this.iconBackground,
    required this.badge,
    required this.badgeColor,
    required this.badgeBackground,
    required this.value,
    this.unit,
    required this.caption,
    this.captionColor = Dd.muted,
    this.action,
    this.onTap,
  });

  final IconData icon;
  final Color iconColor;
  final Color iconBackground;
  final String badge;
  final Color badgeColor;
  final Color badgeBackground;
  final String value;
  final String? unit;
  final String caption;
  final Color captionColor;
  final String? action;
  final VoidCallback? onTap;

  @override
  Widget build(BuildContext context) => GestureDetector(
        behavior: HitTestBehavior.opaque,
        onTap: onTap,
        child: DdCard(
          padding: const EdgeInsets.all(14),
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Row(mainAxisAlignment: MainAxisAlignment.spaceBetween, children: [
              Container(
                width: 34,
                height: 34,
                decoration: BoxDecoration(color: iconBackground, borderRadius: BorderRadius.circular(10)),
                child: Icon(icon, size: 18, color: iconColor),
              ),
              Flexible(child: DdPill(label: badge, background: badgeBackground, foreground: badgeColor, size: 10.5)),
            ]),
            const SizedBox(height: 14),
            Row(crossAxisAlignment: CrossAxisAlignment.baseline, textBaseline: TextBaseline.alphabetic, children: [
              Flexible(child: FittedBox(fit: BoxFit.scaleDown, alignment: Alignment.centerLeft, child: Text(value, style: const TextStyle(fontSize: 26, fontWeight: FontWeight.w700, color: Dd.ink)))),
              if (unit != null) ...[const SizedBox(width: 4), Flexible(child: Text(unit!, maxLines: 1, overflow: TextOverflow.ellipsis, style: const TextStyle(fontSize: 12, color: Dd.muted)))],
            ]),
            const SizedBox(height: 6),
            Row(children: [
              Expanded(child: Text(caption, maxLines: 2, overflow: TextOverflow.ellipsis, style: TextStyle(fontSize: 11.5, color: captionColor))),
              if (action != null) Text(action!, style: const TextStyle(fontSize: 12, fontWeight: FontWeight.w700, color: Dd.navy)),
            ]),
          ]),
        ),
      );
}

class DdSegment {
  const DdSegment(this.label, this.count, this.color);
  final String label;
  final int count;
  final Color color;
}

class DdDonut extends StatelessWidget {
  const DdDonut({super.key, required this.segments, required this.total});
  final List<DdSegment> segments;
  final int total;

  @override
  Widget build(BuildContext context) => SizedBox(
        width: 92,
        height: 92,
        child: CustomPaint(
          painter: _DonutPainter(segments),
          child: Center(
            child: Column(mainAxisSize: MainAxisSize.min, children: [
              Text('$total', style: const TextStyle(fontSize: 18, fontWeight: FontWeight.w700, color: Dd.ink)),
              const Text('Total', style: TextStyle(fontSize: 11, color: Dd.muted)),
            ]),
          ),
        ),
      );
}

class _DonutPainter extends CustomPainter {
  _DonutPainter(this.segments);
  final List<DdSegment> segments;

  @override
  void paint(Canvas canvas, Size size) {
    const stroke = 10.0;
    final rect = Rect.fromLTWH(stroke / 2, stroke / 2, size.width - stroke, size.height - stroke);
    final paint = Paint()
      ..style = PaintingStyle.stroke
      ..strokeWidth = stroke
      ..strokeCap = StrokeCap.butt;
    final sum = segments.fold<int>(0, (a, s) => a + s.count);
    if (sum == 0) {
      canvas.drawArc(rect, 0, math.pi * 2, false, paint..color = Dd.line);
      return;
    }
    var start = -math.pi / 2;
    const gap = 0.04;
    for (final s in segments) {
      if (s.count == 0) continue;
      final sweep = s.count / sum * math.pi * 2;
      canvas.drawArc(rect, start, math.max(sweep - (segments.where((e) => e.count > 0).length > 1 ? gap : 0), 0.01), false, paint..color = s.color);
      start += sweep;
    }
  }

  @override
  bool shouldRepaint(_DonutPainter old) => old.segments != segments;
}

/// A row in "Needs attention".
class DdAttentionRow extends StatelessWidget {
  const DdAttentionRow({super.key, required this.icon, required this.iconColor, required this.iconBackground, required this.title, required this.badge, required this.badgeColor, required this.badgeBackground, required this.caption, required this.onTap});
  final IconData icon;
  final Color iconColor;
  final Color iconBackground;
  final String title;
  final String badge;
  final Color badgeColor;
  final Color badgeBackground;
  final String caption;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) => GestureDetector(
        onTap: onTap,
        behavior: HitTestBehavior.opaque,
        child: DdCard(
          padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 14),
          child: Row(children: [
            Container(
              width: 38,
              height: 38,
              decoration: BoxDecoration(color: iconBackground, borderRadius: BorderRadius.circular(11)),
              child: Icon(icon, size: 20, color: iconColor),
            ),
            const SizedBox(width: 12),
            Expanded(
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Wrap(spacing: 8, runSpacing: 4, crossAxisAlignment: WrapCrossAlignment.center, children: [
                  Text(title, style: const TextStyle(fontSize: 14.5, fontWeight: FontWeight.w700, color: Dd.ink)),
                  DdPill(label: badge, background: badgeBackground, foreground: badgeColor, size: 10),
                ]),
                const SizedBox(height: 4),
                Text(caption, maxLines: 1, overflow: TextOverflow.ellipsis, style: const TextStyle(fontSize: 12, color: Dd.muted)),
              ]),
            ),
            const Icon(Icons.chevron_right, color: Dd.ink, size: 22),
          ]),
        ),
      );
}

class DdQuickAction extends StatelessWidget {
  const DdQuickAction({super.key, required this.icon, required this.iconColor, required this.iconBackground, required this.title, required this.subtitle, required this.onTap});
  final IconData icon;
  final Color iconColor;
  final Color iconBackground;
  final String title;
  final String subtitle;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) => GestureDetector(
        onTap: onTap,
        behavior: HitTestBehavior.opaque,
        child: DdCard(
          padding: const EdgeInsets.all(12),
          child: Row(children: [
            Container(
              width: 40,
              height: 40,
              decoration: BoxDecoration(color: iconBackground, borderRadius: BorderRadius.circular(12)),
              child: Icon(icon, size: 21, color: iconColor),
            ),
            const SizedBox(width: 10),
            Expanded(
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Text(title, maxLines: 1, overflow: TextOverflow.ellipsis, style: const TextStyle(fontSize: 14, fontWeight: FontWeight.w700, color: Dd.ink)),
                const SizedBox(height: 2),
                Text(subtitle, maxLines: 1, overflow: TextOverflow.ellipsis, style: const TextStyle(fontSize: 11, color: Dd.muted, fontWeight: FontWeight.w500)),
              ]),
            ),
          ]),
        ),
      );
}
