import 'package:flutter/material.dart';

/// Mirrors `apps/web/src/components/common/form-field.tsx` — label, optional
/// "required"/description hint, and an inline error line below the field.
class AuthFormField extends StatelessWidget {
  const AuthFormField({
    super.key,
    required this.label,
    this.required = false,
    this.description,
    this.errorText,
    required this.child,
  });

  final String label;
  final bool required;
  final String? description;
  final String? errorText;
  final Widget child;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final scheme = theme.colorScheme;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        RichText(
          text: TextSpan(
            style: theme.textTheme.labelMedium?.copyWith(color: scheme.onSurface),
            children: [
              TextSpan(text: label),
              if (required) TextSpan(text: ' *', style: TextStyle(color: scheme.error)),
            ],
          ),
        ),
        const SizedBox(height: 6),
        child,
        if (errorText != null) ...[
          const SizedBox(height: 4),
          Text(errorText!, style: theme.textTheme.bodySmall?.copyWith(color: scheme.error)),
        ] else if (description != null) ...[
          const SizedBox(height: 4),
          Text(description!, style: theme.textTheme.bodySmall?.copyWith(color: scheme.onSurfaceVariant)),
        ],
      ],
    );
  }
}

/// Mirrors `apps/web/src/components/common/password-input.tsx` — a text field
/// with a show/hide toggle.
class AuthPasswordField extends StatefulWidget {
  const AuthPasswordField({
    super.key,
    required this.controller,
    this.enabled = true,
    this.autofillHints,
    this.onChanged,
    this.onSubmitted,
  });

  final TextEditingController controller;
  final bool enabled;
  final Iterable<String>? autofillHints;
  final ValueChanged<String>? onChanged;
  final ValueChanged<String>? onSubmitted;

  @override
  State<AuthPasswordField> createState() => _AuthPasswordFieldState();
}

class _AuthPasswordFieldState extends State<AuthPasswordField> {
  bool _obscured = true;

  @override
  Widget build(BuildContext context) {
    return TextField(
      controller: widget.controller,
      enabled: widget.enabled,
      obscureText: _obscured,
      autofillHints: widget.autofillHints,
      onChanged: widget.onChanged,
      onSubmitted: widget.onSubmitted,
      decoration: InputDecoration(
        suffixIcon: IconButton(
          icon: Icon(_obscured ? Icons.visibility_outlined : Icons.visibility_off_outlined),
          onPressed: () => setState(() => _obscured = !_obscured),
        ),
      ),
    );
  }
}

/// Mirrors the `role="alert"` danger banner used for form-level errors across
/// every auth screen.
class InlineAlert extends StatelessWidget {
  const InlineAlert({super.key, required this.message, this.trailing});

  final String message;
  final Widget? trailing;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    return Semantics(
      liveRegion: true,
      child: Container(
        width: double.infinity,
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
        decoration: BoxDecoration(
          color: scheme.errorContainer,
          borderRadius: BorderRadius.circular(6),
          border: Border.all(color: scheme.error.withValues(alpha: 0.3)),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(message, style: TextStyle(color: scheme.onErrorContainer, fontSize: 13)),
            if (trailing != null) trailing!,
          ],
        ),
      ),
    );
  }
}

/// Mirrors `apps/web/src/components/ui/button.tsx`'s loading/disabled state —
/// full-width primary action button used at the bottom of every auth form.
class PrimaryButton extends StatelessWidget {
  const PrimaryButton({super.key, required this.label, required this.loading, this.onPressed});

  final String label;
  final bool loading;
  final VoidCallback? onPressed;

  @override
  Widget build(BuildContext context) {
    return ElevatedButton(
      onPressed: loading ? null : onPressed,
      child: loading
          ? SizedBox(
              height: 18,
              width: 18,
              child: CircularProgressIndicator(
                strokeWidth: 2,
                color: Theme.of(context).colorScheme.onPrimary,
              ),
            )
          : Text(label),
    );
  }
}
