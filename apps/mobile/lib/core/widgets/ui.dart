import 'package:flutter/material.dart';

import '../theme/app_colors.dart';
import '../theme/app_theme.dart';

/// Shared building blocks for the redesigned screens. Everything here reads
/// the active [ThemeData], so light/dark stay in step with the rest of the app.

enum Tone { success, info, warning, danger, neutral, accent }

({Color fg, Color bg}) toneColors(BuildContext context, Tone tone) {
  final scheme = Theme.of(context).colorScheme;
  final status = Theme.of(context).extension<AppStatusColors>() ?? AppStatusColors.light;
  return switch (tone) {
    Tone.success => (fg: status.success, bg: status.successSubtle),
    Tone.info => (fg: status.info, bg: status.infoSubtle),
    Tone.warning => (fg: status.warning, bg: status.warningSubtle),
    Tone.danger => (fg: status.danger, bg: status.dangerSubtle),
    Tone.accent => (fg: scheme.primary, bg: scheme.primary.withValues(alpha: 0.10)),
    Tone.neutral => (fg: scheme.onSurfaceVariant, bg: scheme.surfaceContainerHigh),
  };
}

/// Maps the API's status codes onto a [Tone].
Tone toneForStatus(String status) => switch (status.toUpperCase()) {
      'ACTIVE' || 'APPROVED' || 'COMPLETE' || 'COMPLETED' || 'PRESENT' || 'PAID' || 'PUBLISHED' || 'LOCKED' => Tone.success,
      'PENDING' || 'PENDING_APPROVAL' || 'SUBMITTED' || 'DRAFT' || 'PAST_DUE' || 'GRACE' || 'HALF_DAY' => Tone.warning,
      'REJECTED' || 'CANCELLED' || 'CANCELED' || 'SUSPENDED' || 'EXPIRED' || 'ABSENT' || 'FAILED' => Tone.danger,
      'TRIAL' || 'TRIALING' || 'IN_PROGRESS' || 'PROCESSING' || 'OPEN' => Tone.info,
      _ => Tone.neutral,
    };

/// `PENDING_APPROVAL` → `Pending approval`.
String humanize(String code) {
  final words = code.replaceAll('_', ' ').replaceAll('.', ' ').toLowerCase().trim();
  return words.isEmpty ? code : words[0].toUpperCase() + words.substring(1);
}

String initialsOf(String name) {
  final parts = name.trim().split(RegExp(r'\s+')).where((p) => p.isNotEmpty).toList();
  if (parts.isEmpty) return '?';
  if (parts.length == 1) return parts.first.substring(0, parts.first.length >= 2 ? 2 : 1).toUpperCase();
  return (parts[0][0] + parts[1][0]).toUpperCase();
}

/// The standard elevated surface: white card, soft border, faint navy shadow.
class AppCard extends StatelessWidget {
  const AppCard({
    super.key,
    required this.child,
    this.padding = const EdgeInsets.all(16),
    this.onTap,
    this.margin,
  });

  final Widget child;
  final EdgeInsetsGeometry padding;
  final EdgeInsetsGeometry? margin;
  final VoidCallback? onTap;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final dark = scheme.brightness == Brightness.dark;
    final radius = BorderRadius.circular(AppRadii.card);
    return Container(
      margin: margin,
      decoration: BoxDecoration(
        color: dark ? scheme.surfaceContainer : scheme.surfaceContainerLowest,
        borderRadius: radius,
        border: Border.all(color: scheme.outlineVariant.withValues(alpha: 0.55)),
        boxShadow: [
          if (!dark) BoxShadow(color: AppBrand.navy.withValues(alpha: 0.05), blurRadius: 14, offset: const Offset(0, 3)),
        ],
      ),
      child: Material(
        color: Colors.transparent,
        borderRadius: radius,
        child: InkWell(
          borderRadius: radius,
          onTap: onTap,
          child: Padding(padding: padding, child: child),
        ),
      ),
    );
  }
}

/// Small coloured dot + label pill.
class StatusChip extends StatelessWidget {
  const StatusChip({super.key, required this.label, this.tone = Tone.neutral, this.dot = true});

  /// Builds a chip straight from an API status code.
  StatusChip.status(String status, {Key? key})
      : this(key: key, label: humanize(status), tone: toneForStatus(status));

  final String label;
  final Tone tone;
  final bool dot;

  @override
  Widget build(BuildContext context) {
    final c = toneColors(context, tone);
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
      decoration: BoxDecoration(color: c.bg, borderRadius: BorderRadius.circular(AppRadii.full)),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          if (dot) ...[
            Container(width: 6, height: 6, decoration: BoxDecoration(color: c.fg, shape: BoxShape.circle)),
            const SizedBox(width: 6),
          ],
          Text(label, style: TextStyle(fontSize: 11.5, fontWeight: FontWeight.w700, color: c.fg)),
        ],
      ),
    );
  }
}

/// Tinted rounded-square icon badge — the leading element for rows and tiles.
class IconBadge extends StatelessWidget {
  const IconBadge({super.key, required this.icon, this.tone = Tone.accent, this.size = 42});

  final IconData icon;
  final Tone tone;
  final double size;

  @override
  Widget build(BuildContext context) {
    final c = toneColors(context, tone);
    return Container(
      width: size,
      height: size,
      decoration: BoxDecoration(color: c.bg, borderRadius: BorderRadius.circular(size * 0.32)),
      child: Icon(icon, size: size * 0.5, color: c.fg),
    );
  }
}

/// Initials avatar with a stable colour per name.
class InitialsAvatar extends StatelessWidget {
  const InitialsAvatar({super.key, required this.name, this.size = 44});

  final String name;
  final double size;

  static const _hues = [
    Color(0xFF2563EB), Color(0xFF0D9488), Color(0xFF8B5CF6), Color(0xFFD97706),
    Color(0xFFDB2777), Color(0xFF0891B2), Color(0xFF4F46E5), Color(0xFF16A34A),
  ];

  @override
  Widget build(BuildContext context) {
    final color = _hues[name.runes.fold<int>(0, (a, b) => a + b) % _hues.length];
    return Container(
      width: size,
      height: size,
      alignment: Alignment.center,
      decoration: BoxDecoration(
        shape: BoxShape.circle,
        gradient: LinearGradient(
          begin: Alignment.topLeft,
          end: Alignment.bottomRight,
          colors: [color, Color.lerp(color, Colors.black, 0.25)!],
        ),
      ),
      child: Text(
        initialsOf(name),
        style: TextStyle(color: Colors.white, fontWeight: FontWeight.w700, fontSize: size * 0.36),
      ),
    );
  }
}

class SectionHeader extends StatelessWidget {
  const SectionHeader(this.title, {super.key, this.action, this.onAction});

  final String title;
  final String? action;
  final VoidCallback? onAction;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Padding(
      padding: const EdgeInsets.fromLTRB(4, 8, 4, 10),
      child: Row(
        children: [
          Expanded(child: Text(title, style: theme.textTheme.headlineSmall?.copyWith(fontWeight: FontWeight.w700))),
          if (action != null)
            GestureDetector(
              onTap: onAction,
              child: Text(
                action!,
                style: theme.textTheme.bodyMedium?.copyWith(color: theme.colorScheme.primary, fontWeight: FontWeight.w600),
              ),
            ),
        ],
      ),
    );
  }
}

/// Friendly empty / error placeholder with an optional action.
class StateMessage extends StatelessWidget {
  const StateMessage({
    super.key,
    required this.icon,
    required this.title,
    this.message,
    this.actionLabel,
    this.onAction,
    this.tone = Tone.accent,
  });

  final IconData icon;
  final String title;
  final String? message;
  final String? actionLabel;
  final VoidCallback? onAction;
  final Tone tone;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Center(
      child: SingleChildScrollView(
        physics: const AlwaysScrollableScrollPhysics(),
        padding: const EdgeInsets.symmetric(horizontal: 32, vertical: 24),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            IconBadge(icon: icon, tone: tone, size: 72),
            const SizedBox(height: 20),
            Text(title, style: theme.textTheme.headlineSmall?.copyWith(fontWeight: FontWeight.w700), textAlign: TextAlign.center),
            if (message != null) ...[
              const SizedBox(height: 6),
              Text(
                message!,
                style: theme.textTheme.bodyLarge?.copyWith(color: theme.colorScheme.onSurfaceVariant),
                textAlign: TextAlign.center,
              ),
            ],
            if (actionLabel != null) ...[
              const SizedBox(height: 20),
              FilledButton(onPressed: onAction, child: Text(actionLabel!)),
            ],
          ],
        ),
      ),
    );
  }
}

/// Pulsing placeholder rows shown while a list loads (replaces the bare spinner).
class ListSkeleton extends StatefulWidget {
  const ListSkeleton({super.key, this.count = 6});

  final int count;

  @override
  State<ListSkeleton> createState() => _ListSkeletonState();
}

class _ListSkeletonState extends State<ListSkeleton> with SingleTickerProviderStateMixin {
  late final AnimationController _controller =
      AnimationController(vsync: this, duration: const Duration(milliseconds: 1100))..repeat(reverse: true);

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    return ListView.separated(
      physics: const NeverScrollableScrollPhysics(),
      padding: const EdgeInsets.all(16),
      itemCount: widget.count,
      separatorBuilder: (_, __) => const SizedBox(height: 12),
      itemBuilder: (context, _) => AnimatedBuilder(
        animation: _controller,
        builder: (context, _) {
          final block = Color.lerp(scheme.surfaceContainerHigh, scheme.surfaceContainerHighest, _controller.value)!;
          Widget bar(double w, double h) => Container(
                width: w,
                height: h,
                decoration: BoxDecoration(color: block, borderRadius: BorderRadius.circular(6)),
              );
          return AppCard(
            child: Row(
              children: [
                Container(width: 44, height: 44, decoration: BoxDecoration(color: block, shape: BoxShape.circle)),
                const SizedBox(width: 14),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [bar(160, 13), const SizedBox(height: 8), bar(100, 10)],
                  ),
                ),
              ],
            ),
          );
        },
      ),
    );
  }
}

/// A rounded search field used on list screens and the More hub.
class AppSearchField extends StatelessWidget {
  const AppSearchField({super.key, required this.onChanged, this.hint = 'Search', this.controller});

  final ValueChanged<String> onChanged;
  final String hint;
  final TextEditingController? controller;

  @override
  Widget build(BuildContext context) {
    return TextField(
      controller: controller,
      onChanged: onChanged,
      textInputAction: TextInputAction.search,
      decoration: InputDecoration(
        hintText: hint,
        prefixIcon: const Icon(Icons.search_rounded),
        contentPadding: const EdgeInsets.symmetric(vertical: 12),
      ),
    );
  }
}

/// Card-shaped list row: leading + title/subtitle + trailing (chevron by default).
class ListRowCard extends StatelessWidget {
  const ListRowCard({
    super.key,
    required this.title,
    this.subtitle,
    this.leading,
    this.trailing,
    this.onTap,
    this.showChevron = true,
  });

  final String title;
  final String? subtitle;
  final Widget? leading;
  final Widget? trailing;
  final VoidCallback? onTap;
  final bool showChevron;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return AppCard(
      onTap: onTap,
      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
      child: Row(
        children: [
          if (leading != null) ...[leading!, const SizedBox(width: 14)],
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(title, style: theme.textTheme.bodyLarge?.copyWith(fontWeight: FontWeight.w600), maxLines: 1, overflow: TextOverflow.ellipsis),
                if (subtitle != null && subtitle!.isNotEmpty) ...[
                  const SizedBox(height: 2),
                  Text(
                    subtitle!,
                    style: theme.textTheme.bodyMedium?.copyWith(color: theme.colorScheme.onSurfaceVariant),
                    maxLines: 2,
                    overflow: TextOverflow.ellipsis,
                  ),
                ],
              ],
            ),
          ),
          if (trailing != null) ...[const SizedBox(width: 8), trailing!],
          if (showChevron && onTap != null) Icon(Icons.chevron_right_rounded, size: 22, color: theme.colorScheme.outline),
        ],
      ),
    );
  }
}

/// Titled card for detail screens: a section title above a stack of rows.
class DetailSection extends StatelessWidget {
  const DetailSection({super.key, required this.title, required this.children, this.icon, this.trailing});

  final String title;
  final List<Widget> children;
  final IconData? icon;
  final Widget? trailing;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Padding(
      padding: const EdgeInsets.only(top: 14),
      child: AppCard(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(children: [
              if (icon != null) ...[IconBadge(icon: icon!, size: 30), const SizedBox(width: 10)],
              Expanded(child: Text(title, style: theme.textTheme.titleMedium?.copyWith(fontWeight: FontWeight.w700))),
              if (trailing != null) trailing!,
            ]),
            const SizedBox(height: 8),
            ...children,
          ],
        ),
      ),
    );
  }
}

/// Label on the left, value on the right — the row used inside [DetailSection].
class KeyValueRow extends StatelessWidget {
  const KeyValueRow(this.label, this.value, {super.key, this.emphasize = false});

  final String label;
  final String? value;
  final bool emphasize;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final text = (value == null || value!.isEmpty) ? '—' : value!;
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 5),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Expanded(flex: 4, child: Text(label, style: TextStyle(color: scheme.onSurfaceVariant))),
          Expanded(
            flex: 5,
            child: Text(text, textAlign: TextAlign.end, style: TextStyle(fontWeight: emphasize ? FontWeight.w800 : FontWeight.w600)),
          ),
        ],
      ),
    );
  }
}

/// Navy gradient summary card at the top of a detail screen.
class HeroCard extends StatelessWidget {
  const HeroCard({super.key, required this.child, this.padding = const EdgeInsets.all(18)});

  final Widget child;
  final EdgeInsetsGeometry padding;

  @override
  Widget build(BuildContext context) {
    return Container(
      width: double.infinity,
      padding: padding,
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(20),
        gradient: const LinearGradient(
          begin: Alignment.topLeft,
          end: Alignment.bottomRight,
          colors: [AppBrand.navy, Color(0xFF1E3A8A)],
        ),
      ),
      child: child,
    );
  }
}

/// One step in a vertical timeline (history lists).
class TimelineEntry extends StatelessWidget {
  const TimelineEntry({super.key, required this.title, this.subtitle, this.body, this.last = false});

  final String title;
  final String? subtitle;
  final String? body;
  final bool last;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    return IntrinsicHeight(
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          SizedBox(
            width: 20,
            child: Column(children: [
              const SizedBox(height: 5),
              Container(width: 10, height: 10, decoration: BoxDecoration(color: scheme.primary, shape: BoxShape.circle)),
              if (!last) Expanded(child: Container(width: 2, color: scheme.outlineVariant)),
            ]),
          ),
          Expanded(
            child: Padding(
              padding: EdgeInsets.only(bottom: last ? 0 : 14),
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Text(title, style: const TextStyle(fontWeight: FontWeight.w600)),
                if (subtitle != null) Text(subtitle!, style: TextStyle(fontSize: 12, color: scheme.onSurfaceVariant)),
                if (body != null) Padding(padding: const EdgeInsets.only(top: 2), child: Text(body!)),
              ]),
            ),
          ),
        ],
      ),
    );
  }
}
