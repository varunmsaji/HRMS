import 'dart:io';

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:path_provider/path_provider.dart';
import 'package:share_plus/share_plus.dart';

/// One CSV cell, quoted only when it has to be — the same rule as web's `csvCell`
/// (`apps/web/src/lib/employee/directory.ts`), so both apps write identical files.
String csvCell(String? value) {
  final v = value ?? '';
  return RegExp(r'[",\n]').hasMatch(v) ? '"${v.replaceAll('"', '""')}"' : v;
}

/// A CSV document: the header line, then one line per row, joined with `\n` (as on web).
String toCsv(List<String> header, Iterable<List<String?>> rows) => [header.map(csvCell).join(','), for (final r in rows) r.map(csvCell).join(',')].join('\n');

/// Hands a finished CSV to the phone's share sheet (save to Files, mail, chat…). Behind a provider
/// so tests can record the export instead of opening a platform sheet.
typedef CsvSharer = Future<void> Function(String filename, String csv);

Future<void> _shareCsv(String filename, String csv) async {
  final dir = await getTemporaryDirectory();
  final file = File('${dir.path}/$filename');
  await file.writeAsString(csv);
  await SharePlus.instance.share(ShareParams(files: [XFile(file.path, mimeType: 'text/csv')], subject: filename));
}

final csvSharerProvider = Provider<CsvSharer>((ref) => _shareCsv);
