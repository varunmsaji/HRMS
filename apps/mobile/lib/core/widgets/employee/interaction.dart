import 'package:flutter/material.dart';

import '../../theme/employee_tokens.dart';

/// Confirm before something that cannot be undone. Returns true only on the destructive choice.
Future<bool> confirmDestructive(
  BuildContext context, {
  required String title,
  required String body,
  required String confirmLabel,
  String cancelLabel = 'Cancel',
  bool filled = false,
}) async {
  final result = await showDialog<bool>(
    context: context,
    builder: (ctx) {
      final t = EmployeeTokens.of(ctx);
      return AlertDialog(
        title: Text(title),
        content: Text(body),
        insetPadding: const EdgeInsets.all(24),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx, false), child: Text(cancelLabel)),
          filled
              ? FilledButton(
                  style: FilledButton.styleFrom(backgroundColor: t.dangerText, foregroundColor: Colors.white),
                  onPressed: () => Navigator.pop(ctx, true),
                  child: Text(confirmLabel),
                )
              : TextButton(
                  style: TextButton.styleFrom(foregroundColor: t.dangerText),
                  onPressed: () => Navigator.pop(ctx, true),
                  child: Text(confirmLabel),
                ),
        ],
      );
    },
  );
  return result == true;
}

/// A bar fixed below a screen's scrolling body (punch, submit, cancel). It sits *in* a column, so
/// the body above is never covered and needs no extra bottom padding.
class StickyActionBar extends StatelessWidget {
  const StickyActionBar({super.key, required this.child});

  final Widget child;

  @override
  Widget build(BuildContext context) {
    final t = EmployeeTokens.of(context);
    return DecoratedBox(
      decoration: BoxDecoration(color: t.sheet, border: Border(top: BorderSide(color: t.line))),
      child: SafeArea(
        top: false,
        child: Padding(padding: const EdgeInsets.all(16), child: child),
      ),
    );
  }
}

/// [body] fills the space, [bar] is pinned below it.
class WithStickyBar extends StatelessWidget {
  const WithStickyBar({super.key, required this.body, required this.bar});

  final Widget body;
  final Widget bar;

  @override
  Widget build(BuildContext context) => Column(children: [Expanded(child: body), StickyActionBar(child: bar)]);
}

/// 4 px linear progress with a "Step n of m" caption (onboarding wizard).
class ProgressTrack extends StatelessWidget {
  const ProgressTrack({super.key, required this.step, required this.total});

  /// Zero-based current step.
  final int step;
  final int total;

  @override
  Widget build(BuildContext context) {
    final t = EmployeeTokens.of(context);
    final theme = Theme.of(context);
    final last = total <= 1 ? 1 : total - 1;
    return Padding(
      padding: const EdgeInsets.fromLTRB(16, 8, 16, 8),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          LinearProgressIndicator(value: (step / last).clamp(0.0, 1.0), semanticsLabel: 'Progress'),
          const SizedBox(height: 6),
          Text('Step ${step + 1} of $total', style: theme.textTheme.bodySmall?.copyWith(color: t.inkSecondary)),
        ],
      ),
    );
  }
}

/// A form screen's chrome: app bar, scrolling fields, pinned submit, and a discard confirmation
/// when the form is dirty. Wraps field content; `SpecFormScreen` adopts it in T2-03.
class EmployeeFormScaffold extends StatelessWidget {
  const EmployeeFormScaffold({
    super.key,
    required this.title,
    required this.children,
    required this.submitLabel,
    required this.onSubmit,
    this.busy = false,
    this.busyLabel,
    this.dirty = false,
    this.discardTitle = 'Discard changes?',
    this.discardBody = 'Your changes will be lost.',
  });

  final String title;
  final List<Widget> children;
  final String submitLabel;
  final VoidCallback? onSubmit;
  final bool busy;
  final String? busyLabel;
  final bool dirty;
  final String discardTitle;
  final String discardBody;

  @override
  Widget build(BuildContext context) {
    return PopScope(
      canPop: !dirty,
      onPopInvokedWithResult: (didPop, _) async {
        if (didPop) return;
        final navigator = Navigator.of(context);
        final discard = await confirmDestructive(context, title: discardTitle, body: discardBody, confirmLabel: 'Discard', cancelLabel: 'Keep editing');
        if (discard) navigator.pop();
      },
      child: Scaffold(
        appBar: AppBar(title: Text(title)),
        body: WithStickyBar(
          body: ListView(
            padding: const EdgeInsets.all(16),
            keyboardDismissBehavior: ScrollViewKeyboardDismissBehavior.onDrag,
            children: children,
          ),
          bar: SizedBox(
            width: double.infinity,
            child: FilledButton(onPressed: busy ? null : onSubmit, child: Text(busy ? (busyLabel ?? '$submitLabel…') : submitLabel)),
          ),
        ),
      ),
    );
  }
}
