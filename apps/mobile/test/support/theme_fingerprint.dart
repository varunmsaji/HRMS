import 'package:flutter/material.dart';

/// A stable text rendering of a [ThemeData] used to prove two themes are identical.
/// Object identity hashes (`#1a2b3`) are stripped so equal themes give equal text.
String themeFingerprint(ThemeData theme) {
  final text = theme.toDiagnosticsNode().toStringDeep(minLevel: DiagnosticLevel.debug);
  return text.replaceAll(RegExp(r'#[0-9a-f]{5}'), '#xxxxx');
}
