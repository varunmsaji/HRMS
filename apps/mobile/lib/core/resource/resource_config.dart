import 'package:flutter/widgets.dart';

import '../forms/form_spec.dart';

/// Describes one CRUD resource so a single pair of screens ([ResourceListScreen] /
/// [ResourceDetailScreen]) can serve branches, departments, calendars, … — list, create, view,
/// edit (PATCH with `If-Match`), and deactivate/reactivate (soft `DELETE`, as on the web).
class ResourceConfig {
  const ResourceConfig({
    required this.title,
    required this.singular,
    required this.path,
    required this.spec,
    required this.rowTitle,
    this.rowSubtitle,
    this.manage,
    this.hasActive = true,
    this.canDeactivate = true,
    this.detailExtras,
    this.emptyLabel,
    this.listFilters = const {},
  });

  /// Screen title / list heading ("Branches").
  final String title;

  /// "Branch" — used in titles and messages.
  final String singular;

  /// List endpoint; a record lives at `$path/{id}`.
  final String path;

  /// The create/edit form. Mark the active flag `editOnly` — it only exists once the record does.
  final FormSpec spec;

  final String Function(Map<String, dynamic> row) rowTitle;
  final String? Function(Map<String, dynamic> row)? rowSubtitle;

  /// Permission needed to create, edit or deactivate. Null = no client-side gate (the server decides).
  final String? manage;

  /// The record has an `is_active` flag.
  final bool hasActive;

  /// `DELETE` deactivates it.
  final bool canDeactivate;

  /// Sub-resources shown under the record's fields (holidays of a calendar, versions of a shift…).
  final Widget Function(BuildContext context, Map<String, dynamic> row, VoidCallback reload)? detailExtras;

  final String? emptyLabel;

  /// Extra query params for the list call.
  final Map<String, dynamic> listFilters;
}
