import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../../../../core/theme/app_theme.dart';

/// Shared chrome for every public/unauthenticated screen (login, register,
/// forgot/reset password, verify email, accept invite): a navy brand header
/// with a rounded form sheet over it — the common native sign-in layout. Same
/// content as `apps/web/src/components/layout/auth-layout.tsx`, laid out for phones.
class AuthScaffold extends StatelessWidget {
  const AuthScaffold({
    super.key,
    required this.title,
    this.description,
    required this.child,
    this.footer,
  });

  final String title;
  final String? description;
  final Widget child;
  final Widget? footer;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final scheme = theme.colorScheme;
    return AnnotatedRegion<SystemUiOverlayStyle>(
      value: SystemUiOverlayStyle.light.copyWith(statusBarColor: Colors.transparent),
      child: Scaffold(
        backgroundColor: AppBrand.navy,
        body: CustomScrollView(
          keyboardDismissBehavior: ScrollViewKeyboardDismissBehavior.onDrag,
          slivers: [
            const SliverToBoxAdapter(child: _BrandHeader()),
            SliverFillRemaining(
              hasScrollBody: false,
              child: Container(
                decoration: BoxDecoration(
                  color: scheme.surface,
                  borderRadius: const BorderRadius.vertical(top: Radius.circular(28)),
                ),
                child: SafeArea(
                  top: false,
                  child: Align(
                    alignment: Alignment.topCenter,
                    child: ConstrainedBox(
                      constraints: const BoxConstraints(maxWidth: 440),
                      child: Padding(
                        padding: const EdgeInsets.fromLTRB(24, 28, 24, 16),
                        child: Theme(
                          data: _authFormTheme(theme),
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.stretch,
                            children: [
                              Text(title, style: theme.textTheme.headlineLarge?.copyWith(fontSize: 26, height: 34 / 26)),
                              if (description != null) ...[
                                const SizedBox(height: 6),
                                Text(
                                  description!,
                                  style: theme.textTheme.bodyLarge?.copyWith(color: scheme.onSurfaceVariant, fontSize: 15),
                                ),
                              ],
                              const SizedBox(height: 28),
                              child,
                              if (footer != null) ...[
                                const SizedBox(height: 24),
                                DefaultTextStyle(
                                  style: theme.textTheme.bodyLarge!.copyWith(color: scheme.onSurfaceVariant),
                                  textAlign: TextAlign.center,
                                  child: footer!,
                                ),
                              ],
                              const Spacer(),
                              const SizedBox(height: 32),
                              const _TrustFooter(),
                            ],
                          ),
                        ),
                      ),
                    ),
                  ),
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

/// Larger touch targets for the auth forms than the dense in-app theme:
/// 52px inputs and buttons, softer corners.
ThemeData _authFormTheme(ThemeData base) {
  final scheme = base.colorScheme;
  final radius = BorderRadius.circular(AppRadii.xl);
  OutlineInputBorder border(Color color, [double width = 1]) =>
      OutlineInputBorder(borderRadius: radius, borderSide: BorderSide(color: color, width: width));
  const buttonSize = Size.fromHeight(52);
  final buttonShape = RoundedRectangleBorder(borderRadius: radius);
  final buttonText = base.textTheme.bodyLarge?.copyWith(fontSize: 15, fontWeight: FontWeight.w600);
  return base.copyWith(
    inputDecorationTheme: base.inputDecorationTheme.copyWith(
      fillColor: scheme.surfaceContainerLowest,
      contentPadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 16),
      prefixIconColor: scheme.onSurfaceVariant,
      suffixIconColor: scheme.onSurfaceVariant,
      border: border(scheme.outline),
      enabledBorder: border(scheme.outline),
      disabledBorder: border(scheme.outline.withValues(alpha: 0.5)),
      focusedBorder: border(scheme.primary, 2),
      errorBorder: border(scheme.error),
      focusedErrorBorder: border(scheme.error, 2),
      hintStyle: base.textTheme.bodyLarge?.copyWith(color: scheme.onSurfaceVariant.withValues(alpha: 0.7), fontSize: 15),
    ),
    elevatedButtonTheme: ElevatedButtonThemeData(
      style: ElevatedButton.styleFrom(
        backgroundColor: scheme.primary,
        foregroundColor: scheme.onPrimary,
        disabledBackgroundColor: scheme.primary.withValues(alpha: 0.5),
        disabledForegroundColor: scheme.onPrimary,
        minimumSize: buttonSize,
        elevation: 0,
        shape: buttonShape,
        textStyle: buttonText,
      ),
    ),
    outlinedButtonTheme: OutlinedButtonThemeData(
      style: OutlinedButton.styleFrom(
        foregroundColor: scheme.onSurface,
        minimumSize: buttonSize,
        side: BorderSide(color: scheme.outline),
        shape: buttonShape,
        textStyle: buttonText,
      ),
    ),
    textButtonTheme: TextButtonThemeData(
      style: TextButton.styleFrom(
        foregroundColor: scheme.primary,
        textStyle: base.textTheme.bodyLarge?.copyWith(fontWeight: FontWeight.w600),
      ),
    ),
  );
}

class _BrandHeader extends StatelessWidget {
  const _BrandHeader();

  @override
  Widget build(BuildContext context) {
    final textTheme = Theme.of(context).textTheme;
    return Container(
      decoration: const BoxDecoration(
        gradient: LinearGradient(
          begin: Alignment.topLeft,
          end: Alignment.bottomRight,
          colors: [AppBrand.navy, AppBrand.navyDeep],
        ),
      ),
      child: Stack(
        clipBehavior: Clip.hardEdge,
        children: [
          // Soft decorative rings, echoing the landing page hero.
          Positioned(right: -60, top: -40, child: _Ring(size: 220, color: AppBrand.blue.withValues(alpha: 0.28))),
          Positioned(right: 40, bottom: -70, child: _Ring(size: 140, color: Colors.white.withValues(alpha: 0.08))),
          SafeArea(
            bottom: false,
            child: Padding(
              padding: const EdgeInsets.fromLTRB(24, 12, 24, 36),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(
                    children: [
                      const Image(image: AssetImage('assets/brand/krewoxa-mark.png'), height: 34),
                      const SizedBox(width: 10),
                      const Image(image: AssetImage('assets/brand/krewoxa-wordmark-white.png'), height: 20),
                      const SizedBox(width: 10),
                      Container(
                        padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
                        decoration: BoxDecoration(
                          color: Colors.white.withValues(alpha: 0.1),
                          borderRadius: BorderRadius.circular(AppRadii.full),
                          border: Border.all(color: Colors.white.withValues(alpha: 0.2)),
                        ),
                        child: Text('HRMS', style: textTheme.labelSmall?.copyWith(color: Colors.white.withValues(alpha: 0.85))),
                      ),
                    ],
                  ),
                  const SizedBox(height: 20),
                  Text(
                    'Your people, organized.',
                    style: textTheme.headlineMedium?.copyWith(color: Colors.white, fontSize: 22, height: 30 / 22),
                  ),
                  const SizedBox(height: 6),
                  Text(
                    'Attendance, leave, payroll and onboarding in one workspace.',
                    style: textTheme.bodyLarge?.copyWith(color: Colors.white.withValues(alpha: 0.72)),
                  ),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _Ring extends StatelessWidget {
  const _Ring({required this.size, required this.color});

  final double size;
  final Color color;

  @override
  Widget build(BuildContext context) {
    return Container(
      width: size,
      height: size,
      decoration: BoxDecoration(shape: BoxShape.circle, border: Border.all(color: color, width: 28)),
    );
  }
}

class _TrustFooter extends StatelessWidget {
  const _TrustFooter();

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final muted = theme.textTheme.bodySmall?.copyWith(color: theme.colorScheme.onSurfaceVariant);
    return Column(
      children: [
        Row(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            Icon(Icons.verified_user_outlined, size: 14, color: theme.colorScheme.onSurfaceVariant),
            const SizedBox(width: 6),
            Flexible(child: Text('Protected by enterprise grade 256-bit encryption', style: muted)),
          ],
        ),
        const SizedBox(height: 4),
        Text('© ${DateTime.now().year} Krewoxa. All rights reserved.', style: muted, textAlign: TextAlign.center),
      ],
    );
  }
}
