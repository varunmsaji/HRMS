import 'package:flutter/material.dart';

class ChartBar {
  const ChartBar(this.label, this.value, {this.reference});
  final String label;

  /// `null` renders as a gap (zero denominator).
  final double? value;

  /// Optional comparison value (e.g. scheduled vs worked), drawn as a tick.
  final double? reference;
}

/// A deliberately simple, horizontally scrollable column chart for phone widths — no chart
/// library. Heights are relative to the largest value (or [maxValue]).
class MiniColumnChart extends StatelessWidget {
  const MiniColumnChart({super.key, required this.bars, required this.format, this.maxValue, this.color, this.height = 120});
  final List<ChartBar> bars;
  final String Function(double) format;
  final double? maxValue;
  final Color? color;
  final double height;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final bar = color ?? scheme.primary;
    var max = maxValue ?? 0.0;
    if (maxValue == null) {
      for (final b in bars) {
        if ((b.value ?? 0) > max) max = b.value!;
        if ((b.reference ?? 0) > max) max = b.reference!;
      }
    }
    if (max <= 0) max = 1;
    const labelH = 28.0;
    final plot = height - labelH - 14;
    return SizedBox(
      height: height,
      child: ListView.separated(
        scrollDirection: Axis.horizontal,
        itemCount: bars.length,
        separatorBuilder: (_, __) => const SizedBox(width: 6),
        itemBuilder: (context, i) {
          final b = bars[i];
          final v = b.value;
          return SizedBox(
            width: 34,
            child: Column(mainAxisAlignment: MainAxisAlignment.end, children: [
              SizedBox(height: 14, child: Text(v == null ? '—' : format(v), style: const TextStyle(fontSize: 9), maxLines: 1, overflow: TextOverflow.clip)),
              SizedBox(
                height: plot,
                child: Stack(alignment: Alignment.bottomCenter, children: [
                  Container(width: 18, height: ((v ?? 0) / max * plot).clamp(0, plot).toDouble(), decoration: BoxDecoration(color: v == null ? scheme.outlineVariant : bar, borderRadius: const BorderRadius.vertical(top: Radius.circular(3)))),
                  if (b.reference != null && b.reference! > 0) Positioned(bottom: (b.reference! / max * plot).clamp(0, plot - 2).toDouble(), child: Container(width: 28, height: 2, color: scheme.error)),
                ]),
              ),
              SizedBox(height: labelH, child: Padding(padding: const EdgeInsets.only(top: 4), child: Text(b.label, textAlign: TextAlign.center, style: TextStyle(fontSize: 9, color: scheme.onSurfaceVariant), maxLines: 2))),
            ]),
          );
        },
      ),
    );
  }
}
