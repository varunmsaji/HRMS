import 'package:flutter/material.dart';

/// One attendance figure for [AccentStatGrid].
class AccentStat {
  const AccentStat(this.label, this.value, {required this.icon, required this.accent, required this.accentSubtle, this.hint, this.tone, this.progress, this.showPercent = true});
  final String label;
  final String value;
  final IconData icon;
  final Color accent;
  final Color accentSubtle;
  final String? hint;

  /// Colour for the value itself, e.g. red when there are absences.
  final Color? tone;

  /// 0..100 for figures that are a share of something; draws a bar under the value.
  final double? progress;
  final bool showPercent;
}

/// Tinted icon chip and label, the value, a hint, and an optional bar (web `StatTile`).
class AccentStatTile extends StatelessWidget {
  const AccentStatTile({super.key, required this.stat});
  final AccentStat stat;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final s = stat;
    final pct = s.progress?.clamp(0, 100).round();
    return Container(
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: scheme.surface,
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: scheme.outlineVariant.withValues(alpha: 0.6)),
        boxShadow: [BoxShadow(color: Colors.black.withValues(alpha: 0.04), blurRadius: 8, offset: const Offset(0, 2))],
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Container(width: 32, height: 32, decoration: BoxDecoration(color: s.accentSubtle, borderRadius: BorderRadius.circular(9)), child: Icon(s.icon, size: 18, color: s.accent)),
              const SizedBox(width: 8),
              Expanded(child: Text(s.label, maxLines: 2, overflow: TextOverflow.ellipsis, style: TextStyle(fontSize: 12, fontWeight: FontWeight.w600, color: scheme.onSurfaceVariant, height: 1.2))),
            ],
          ),
          const SizedBox(height: 10),
          Text(
            s.value,
            maxLines: 2,
            overflow: TextOverflow.ellipsis,
            style: TextStyle(fontSize: 22, fontWeight: FontWeight.w700, letterSpacing: -0.3, height: 1.15, color: s.tone, fontFeatures: const [FontFeature.tabularFigures()]),
          ),
          if (s.hint != null) Text(s.hint!, maxLines: 1, overflow: TextOverflow.ellipsis, style: TextStyle(fontSize: 12, color: scheme.onSurfaceVariant)),
          if (pct != null) ...[
            const Spacer(),
            const SizedBox(height: 10),
            ExcludeSemantics(
              child: Row(
                children: [
                  Expanded(
                    child: ClipRRect(
                      borderRadius: BorderRadius.circular(99),
                      child: LinearProgressIndicator(value: pct / 100, minHeight: 5, color: s.accent, backgroundColor: scheme.surfaceContainerHighest),
                    ),
                  ),
                  if (s.showPercent) ...[
                    const SizedBox(width: 6),
                    Text('$pct%', style: TextStyle(fontSize: 11, fontWeight: FontWeight.w600, color: scheme.onSurfaceVariant, fontFeatures: const [FontFeature.tabularFigures()])),
                  ],
                ],
              ),
            ),
          ],
        ],
      ),
    );
  }
}

/// Two tiles a row; the pair shares a height so the cards line up. Each tile is keyed
/// `'$keyPrefix$label'` when [keyPrefix] is given. With [stretchLast], an odd last tile takes the
/// full row instead of half of it.
class AccentStatGrid extends StatelessWidget {
  const AccentStatGrid({super.key, required this.stats, this.keyPrefix, this.stretchLast = false});
  final List<AccentStat> stats;
  final String? keyPrefix;
  final bool stretchLast;

  Widget _tile(AccentStat s) => AccentStatTile(key: keyPrefix == null ? null : Key('$keyPrefix${s.label}'), stat: s);

  @override
  Widget build(BuildContext context) {
    return Column(
      children: [
        for (var i = 0; i < stats.length; i += 2) ...[
          if (i > 0) const SizedBox(height: 10),
          if (stretchLast && i + 1 == stats.length)
            SizedBox(width: double.infinity, child: _tile(stats[i]))
          else
            IntrinsicHeight(
              child: Row(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [Expanded(child: _tile(stats[i])), const SizedBox(width: 10), Expanded(child: i + 1 < stats.length ? _tile(stats[i + 1]) : const SizedBox.shrink())],
              ),
            ),
        ],
      ],
    );
  }
}
