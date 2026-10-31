import 'package:flutter/material.dart';

import '../../theme/employee_tokens.dart';
import 'employee_status_chip.dart';
import 'status_map.dart';

/// Section title: `label` style, optional trailing text button. 24 above, 8 below.
class EmployeeSectionHeader extends StatelessWidget {
  const EmployeeSectionHeader(this.title, {super.key, this.actionLabel, this.onAction, this.prominent = false, this.count, this.caption});

  /// Home's headings: sentence case in the primary ink at title size, instead of the small caps label.
  final bool prominent;

  final String title;
  final String? actionLabel;
  final VoidCallback? onAction;

  /// A small count badge after the title (e.g. requests awaiting a decision).
  final int? count;

  /// Quiet trailing text when there is no action ("Frequently used", "Last 7 days").
  final String? caption;

  /// A long action label ("View detailed ledger") is capped so it ellipsises on a narrow screen
  /// instead of overflowing the row; short ones are left exactly as laid out.
  Widget _capped(BuildContext context, Widget action) => actionLabel!.length <= 14
      ? action
      : ConstrainedBox(constraints: BoxConstraints(maxWidth: MediaQuery.sizeOf(context).width * 0.6), child: action);

  @override
  Widget build(BuildContext context) {
    final t = EmployeeTokens.of(context);
    final theme = Theme.of(context);
    final text = prominent
        ? Text(title, style: theme.textTheme.titleMedium?.copyWith(fontWeight: FontWeight.w700, color: t.ink))
        : Text(title.toUpperCase(), style: theme.textTheme.labelMedium?.copyWith(color: t.inkSecondary));
    final title_ = Semantics(
      header: true,
      child: count == null
          ? text
          : Row(mainAxisSize: MainAxisSize.min, children: [
              Flexible(child: text),
              const SizedBox(width: 8),
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 7, vertical: 1),
                decoration: BoxDecoration(color: t.actionSubtle, borderRadius: BorderRadius.circular(10)),
                child: Text('$count', style: theme.textTheme.labelSmall?.copyWith(color: t.action, fontWeight: FontWeight.w700)),
              ),
            ]),
    );
    final action = actionLabel != null
        ? TextButton(onPressed: onAction, child: Text(actionLabel!, maxLines: 1, overflow: TextOverflow.ellipsis))
        : caption != null
            ? Text(caption!, style: theme.textTheme.bodySmall?.copyWith(color: t.inkSecondary))
            : null;
    final large = MediaQuery.textScalerOf(context).scale(16) / 16 >= 1.4;
    return Padding(
      padding: const EdgeInsets.fromLTRB(16, 24, 16, 8),
      child: large && action != null
          ? Column(crossAxisAlignment: CrossAxisAlignment.start, children: [title_, action])
          : Row(children: [Expanded(child: title_), if (action != null) (actionLabel != null ? _capped(context, action) : action)]),
    );
  }
}

/// One white group on the canvas; rows inside are separated by inset hairlines, not wrapped in cards.
class EmployeeListGroup extends StatelessWidget {
  const EmployeeListGroup({super.key, required this.children, this.margin = const EdgeInsets.symmetric(horizontal: 16)});

  final List<Widget> children;
  final EdgeInsetsGeometry margin;

  @override
  Widget build(BuildContext context) {
    final t = EmployeeTokens.of(context);
    return Container(
      margin: margin,
      clipBehavior: Clip.antiAlias,
      decoration: BoxDecoration(
        color: t.sheet,
        borderRadius: BorderRadius.circular(EmployeeTokens.radiusSurface),
        border: Border.all(color: t.line),
      ),
      child: Column(
        children: [
          for (var i = 0; i < children.length; i++) ...[
            if (i > 0) Divider(height: 1, indent: 16, color: t.line),
            children[i],
          ],
        ],
      ),
    );
  }
}

/// A row: title, optional caption, optional trailing widget, chevron when tappable. Min height 64.
class EmployeeListRow extends StatelessWidget {
  const EmployeeListRow({super.key, required this.title, this.caption, this.leading, this.trailing, this.onTap, this.chevron});

  final String title;
  final String? caption;
  final Widget? leading;
  final Widget? trailing;
  final VoidCallback? onTap;

  /// Defaults to true when [onTap] is set.
  final bool? chevron;

  @override
  Widget build(BuildContext context) {
    final t = EmployeeTokens.of(context);
    final theme = Theme.of(context);
    final showChevron = chevron ?? onTap != null;
    return InkWell(
      onTap: onTap,
      child: ConstrainedBox(
        constraints: const BoxConstraints(minHeight: 64),
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
          child: _stack(context)
              ? Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Row(children: [
                      if (leading != null) ...[leading!, const SizedBox(width: 12)],
                      Expanded(child: _text(theme, t)),
                      if (showChevron) ExcludeSemantics(child: Icon(Icons.chevron_right_rounded, color: t.inkTertiary)),
                    ]),
                    if (trailing != null) ...[const SizedBox(height: 8), trailing!],
                  ],
                )
              : Row(
                  children: [
                    if (leading != null) ...[leading!, const SizedBox(width: 12)],
                    Expanded(child: _text(theme, t)),
                    if (trailing != null) ...[const SizedBox(width: 12), trailing!],
                    if (showChevron) ...[
                      const SizedBox(width: 4),
                      ExcludeSemantics(child: Icon(Icons.chevron_right_rounded, color: t.inkTertiary)),
                    ],
                  ],
                ),
        ),
      ),
    );
  }

  /// At large text sizes the trailing widget (a chip, an amount) moves under the text instead of
  /// squeezing it.
  bool _stack(BuildContext context) => trailing != null && MediaQuery.textScalerOf(context).scale(16) / 16 >= 1.4;

  Widget _text(ThemeData theme, EmployeeTokens t) => Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        mainAxisSize: MainAxisSize.min,
        children: [
          Text(title, style: theme.textTheme.bodyLarge?.copyWith(fontWeight: FontWeight.w600)),
          if (caption != null) ...[
            const SizedBox(height: 2),
            Text(caption!, style: theme.textTheme.bodySmall?.copyWith(color: t.inkSecondary)),
          ],
        ],
      );
}

/// Replaces the gradient hero: white sheet, 3 px left border in the status colour, the status
/// chip and one key figure.
class EmployeeStatusHeader extends StatelessWidget {
  const EmployeeStatusHeader({super.key, required this.status, required this.title, this.subtitle, this.figure, this.figureCaption, this.margin = const EdgeInsets.symmetric(horizontal: 16)});

  final EmployeeStatus status;
  final String title;
  final String? subtitle;
  final String? figure;
  final String? figureCaption;
  final EdgeInsetsGeometry margin;

  @override
  Widget build(BuildContext context) {
    final t = EmployeeTokens.of(context);
    final theme = Theme.of(context);
    final c = statusColors(context, status.kind);
    return Container(
      margin: margin,
      clipBehavior: Clip.antiAlias,
      decoration: BoxDecoration(
        color: t.sheet,
        borderRadius: BorderRadius.circular(EmployeeTokens.radiusSurface),
        border: Border.all(color: t.line),
      ),
      child: IntrinsicHeight(
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Container(width: 3, color: c.glyph),
            Expanded(
              child: Padding(
                padding: const EdgeInsets.all(16),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    EmployeeStatusChip(status: status),
                    const SizedBox(height: 12),
                    Text(title, style: theme.textTheme.headlineSmall),
                    if (subtitle != null) ...[
                      const SizedBox(height: 2),
                      Text(subtitle!, style: theme.textTheme.bodySmall?.copyWith(color: t.inkSecondary)),
                    ],
                    if (figure != null) ...[
                      const SizedBox(height: 12),
                      Text(figure!, style: theme.textTheme.headlineLarge),
                      if (figureCaption != null) Text(figureCaption!, style: theme.textTheme.bodySmall?.copyWith(color: t.inkSecondary)),
                    ] else if (figureCaption != null) ...[
                      const SizedBox(height: 8),
                      Text(figureCaption!, style: theme.textTheme.bodySmall?.copyWith(color: t.inkSecondary)),
                    ],
                  ],
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

/// Empty/error state: small icon, heading, caption, at most one button. No icon circle.
class EmployeeEmptyState extends StatelessWidget {
  const EmployeeEmptyState({super.key, required this.icon, required this.title, this.message, this.actionLabel, this.onAction});

  final IconData icon;
  final String title;
  final String? message;
  final String? actionLabel;
  final VoidCallback? onAction;

  @override
  Widget build(BuildContext context) {
    final t = EmployeeTokens.of(context);
    final theme = Theme.of(context);
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 32, vertical: 32),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          ExcludeSemantics(child: Icon(icon, size: 28, color: t.inkTertiary)),
          const SizedBox(height: 12),
          Text(title, style: theme.textTheme.headlineSmall, textAlign: TextAlign.center),
          if (message != null) ...[
            const SizedBox(height: 4),
            Text(message!, style: theme.textTheme.bodySmall?.copyWith(color: t.inkSecondary), textAlign: TextAlign.center),
          ],
          if (actionLabel != null) ...[
            const SizedBox(height: 16),
            FilledButton(onPressed: onAction, child: Text(actionLabel!)),
          ],
        ],
      ),
    );
  }
}

/// A grey bar standing in for text or a button while content loads.
class SkeletonBlock extends StatelessWidget {
  const SkeletonBlock({super.key, this.width, this.height = 14, this.radius = 6});

  final double? width;
  final double height;
  final double radius;

  @override
  Widget build(BuildContext context) {
    final t = EmployeeTokens.of(context);
    return Semantics(
      label: 'Loading',
      child: ExcludeSemantics(
        child: Container(
          width: width,
          height: height,
          decoration: BoxDecoration(color: t.line, borderRadius: BorderRadius.circular(radius)),
        ),
      ),
    );
  }
}

/// A label on the left and its value on the right, for a read-only fact. Stacks at large text.
class EmployeeFactRow extends StatelessWidget {
  const EmployeeFactRow({super.key, required this.label, required this.value});

  final String label;
  final String value;

  @override
  Widget build(BuildContext context) {
    final t = EmployeeTokens.of(context);
    final theme = Theme.of(context);
    final large = MediaQuery.textScalerOf(context).scale(16) / 16 >= 1.4;
    final l = Text(label, style: theme.textTheme.bodyMedium?.copyWith(color: t.inkSecondary));
    final v = Text(value, textAlign: large ? TextAlign.start : TextAlign.end, style: theme.textTheme.bodyMedium?.copyWith(fontWeight: FontWeight.w600));
    return ConstrainedBox(
      constraints: const BoxConstraints(minHeight: 48),
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
        child: Semantics(
          container: true,
          label: '$label, $value',
          excludeSemantics: true,
          child: large
              ? Column(crossAxisAlignment: CrossAxisAlignment.start, children: [l, const SizedBox(height: 2), v])
              : Row(crossAxisAlignment: CrossAxisAlignment.start, children: [Expanded(flex: 4, child: l), const SizedBox(width: 12), Expanded(flex: 5, child: v)]),
        ),
      ),
    );
  }
}

/// The audit detail (versions, timestamps) behind one collapsed tile: never the answer, always
/// reachable.
class EmployeeCalculationDetails extends StatelessWidget {
  const EmployeeCalculationDetails({super.key, required this.rows});

  final List<(String, String)> rows;

  @override
  Widget build(BuildContext context) {
    final t = EmployeeTokens.of(context);
    return Container(
      clipBehavior: Clip.antiAlias,
      decoration: BoxDecoration(color: t.sheet, borderRadius: BorderRadius.circular(EmployeeTokens.radiusSurface), border: Border.all(color: t.line)),
      child: Theme(
        data: Theme.of(context).copyWith(dividerColor: Colors.transparent),
        child: ExpansionTile(
          title: const Text('Calculation details', style: TextStyle(fontWeight: FontWeight.w600)),
          children: [for (final r in rows) if (r.$2 != '—') EmployeeFactRow(label: r.$1, value: r.$2)],
        ),
      ),
    );
  }
}
