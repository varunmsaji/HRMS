import 'dart:io';

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:path_provider/path_provider.dart';
import 'package:share_plus/share_plus.dart';

/// Hands a downloaded file (PDF, Excel, CSV) to the phone's share sheet. Behind a provider so
/// tests can record the share instead of opening a platform sheet.
typedef FileSharer = Future<void> Function(String filename, List<int> bytes, String mimeType);

Future<void> _shareFile(String filename, List<int> bytes, String mimeType) async {
  final dir = await getTemporaryDirectory();
  final file = File('${dir.path}/$filename');
  await file.writeAsBytes(bytes, flush: true);
  await SharePlus.instance.share(ShareParams(files: [XFile(file.path, mimeType: mimeType)], subject: filename));
}

final fileSharerProvider = Provider<FileSharer>((ref) => _shareFile);
