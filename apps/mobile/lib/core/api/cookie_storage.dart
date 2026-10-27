import 'dart:io';

import 'package:flutter/services.dart';

/// Keeps the persisted refresh-token cookie out of device backups. That cookie is a 30-day
/// session credential, so a restored backup must not carry it (docs/api/AUTHENTICATION.md).
///
/// Android is handled in the manifest (`allowBackup="false"` + `data_extraction_rules.xml`).
/// iOS backs up Application Support unless the item is flagged, which needs a native call.
const _channel = MethodChannel('hrms/backup_exclusion');

/// Creates [directory] if needed and excludes it from backups. Best effort: a failure leaves the
/// cookie usable (the user still signs in), it just stays backup-eligible.
Future<void> prepareCookieDirectory(Directory directory) async {
  await directory.create(recursive: true);
  if (!Platform.isIOS) return;
  try {
    await _channel.invokeMethod<bool>('exclude', directory.path);
  } on PlatformException {
    // Excluding failed — keep going; see the doc comment above.
  } on MissingPluginException {
    // Not running in the Runner (e.g. a test host).
  }
}
