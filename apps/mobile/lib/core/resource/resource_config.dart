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
    this.versions,
    this.editable = true,
    this.hardDelete = false,
    this.listActions,
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

  /// The record can be edited (a `*Update` schema exists). False for create-and-delete-only
  /// records (leave combination rules, statutory minimums).
  final bool editable;

  /// `DELETE` removes the record outright (204) instead of deactivating it.
  final bool hardDelete;

  /// Extra list-level actions (shown beside the create button for users who can manage), e.g. the
  /// salary structures' bulk assign. Receives the loaded rows.
  final List<Widget> Function(BuildContext context, List<Map<String, dynamic>> rows, VoidCallback reload)? listActions;

  /// Set for effective-dated, versioned resources (policies, shifts): the record is an identity
  /// and its configuration lives in versions (one editable DRAFT, then immutable PUBLISHED ones).
  final VersionsConfig? versions;
}

/// How a versioned resource's versions are edited — mirrors the web policy/shift `[id]` pages:
/// create a draft (the server seeds it), edit the draft in full, discard it, or publish it.
class VersionsConfig {
  const VersionsConfig({required this.spec, this.noun = 'version', this.manage, this.summary});

  /// The full version form (`*VersionCreate`/`*VersionUpdate`), nested lists as `FieldKind.rows`.
  final FormSpec spec;
  final String noun;

  /// Overrides [ResourceConfig.manage] for the version actions.
  final String? manage;

  /// One line under a version's status.
  final String? Function(Map<String, dynamic> version)? summary;
}
