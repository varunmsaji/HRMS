import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../api/api_client.dart';
import '../api/api_error.dart';
import '../forms/choice_sources.dart';
import '../forms/form_spec.dart';
import '../forms/spec_form_screen.dart';
import '../providers.dart';
import '../../features/auth/state/auth_controller.dart';

typedef Rec = Map<String, dynamic>;

/// A list of child records under a parent record — holidays of a calendar, exceptions of a work
/// calendar, … Each child can be added, edited (PATCH with its `version`) and deactivated.
class SubResourceSection extends ConsumerStatefulWidget {
  const SubResourceSection({
    super.key,
    required this.title,
    required this.listPath,
    required this.itemPath,
    required this.spec,
    required this.rowTitle,
    this.rowSubtitle,
    this.manage,
    this.singular = 'item',
    this.choiceKeys = const [],
    this.createPath,
    this.hasActive = true,
    this.emptyLabel,
  });

  final String title;
  final String singular;

  /// GET list (and POST create unless [createPath] is given).
  final String listPath;
  final String? createPath;

  /// PATCH path of one child, from its row (`/holidays/{id}`).
  final String Function(Rec row) itemPath;
  final FormSpec spec;
  final String Function(Rec row) rowTitle;
  final String? Function(Rec row)? rowSubtitle;
  final String? manage;
  final List<String> choiceKeys;
  final bool hasActive;
  final String? emptyLabel;

  @override
  ConsumerState<SubResourceSection> createState() => _SubResourceSectionState();
}

class _SubResourceSectionState extends ConsumerState<SubResourceSection> {
  bool _loading = true;
  ApiError? _error;
  List<Rec> _rows = const [];

  ApiClient get _client => ref.read(apiClientProvider);

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void didUpdateWidget(covariant SubResourceSection old) {
    super.didUpdateWidget(old);
    if (old.listPath != widget.listPath) _load();
  }

  Future<void> _load() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final rows = <Rec>[];
      for (var page = 1; page <= 20; page++) {
        final env = await _client.getList<Rec>(widget.listPath, query: PageQuery(page: page, perPage: 100), parseItem: (d) => d as Rec);
        rows.addAll(env.data);
        if (!(env.pagination?.hasNext ?? false)) break;
      }
      if (mounted) setState(() => _rows = rows);
    } catch (e) {
      if (mounted) setState(() => _error = e is ApiError ? e : ApiError(status: 0, code: 'UNKNOWN_ERROR', message: 'Something went wrong.'));
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  void _toast(String m) => ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(m)));

  Future<void> _add() async {
    final saved = await openSpecForm(
      context,
      title: 'Add ${widget.singular}',
      spec: widget.spec,
      loadChoices: widget.choiceKeys.isEmpty ? null : () => loadChoices(_client, widget.choiceKeys),
      onSubmit: (payload, _) async => _client.post<Object?>(widget.createPath ?? widget.listPath, body: payload, parse: (_) => null),
    );
    if (saved && mounted) {
      _toast('${widget.singular[0].toUpperCase()}${widget.singular.substring(1)} added.');
      _load();
    }
  }

  Future<void> _edit(Rec row) async {
    final saved = await openSpecForm(
      context,
      title: 'Edit ${widget.singular}',
      spec: widget.spec,
      initial: row,
      loadChoices: widget.choiceKeys.isEmpty ? null : () => loadChoices(_client, widget.choiceKeys),
      onSubmit: (payload, changed) async => _client.patch<Object?>(widget.itemPath(row), body: changed, ifMatch: row['version'].toString(), parse: (_) => null),
    );
    if (saved && mounted) {
      _toast('Saved.');
      _load();
    }
  }

  Future<void> _toggle(Rec row) async {
    try {
      await _client.patch<Object?>(widget.itemPath(row), body: {'is_active': row['is_active'] == false}, ifMatch: row['version'].toString(), parse: (_) => null);
      _load();
    } catch (e) {
      _toast(e is ApiError ? (e.code == 'STALE_RESOURCE' ? 'This record was changed by someone else. Reloading.' : e.message) : 'Something went wrong.');
      _load();
    }
  }

  @override
  Widget build(BuildContext context) {
    final permissions = ref.watch(authControllerProvider).user?.permissions ?? const <String>[];
    final canManage = widget.manage == null || permissions.contains(widget.manage);
    final scheme = Theme.of(context).colorScheme;
    return Container(
      margin: const EdgeInsets.only(top: 16),
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(border: Border.all(color: scheme.outlineVariant), borderRadius: BorderRadius.circular(12)),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [
          Expanded(child: Text(widget.title, style: Theme.of(context).textTheme.titleSmall)),
          if (canManage) TextButton.icon(onPressed: _add, icon: const Icon(Icons.add, size: 18), label: const Text('Add')),
        ]),
        if (_loading)
          const Padding(padding: EdgeInsets.all(16), child: Center(child: CircularProgressIndicator()))
        else if (_error != null)
          Column(children: [Text(_error!.message), TextButton(onPressed: _load, child: const Text('Retry'))])
        else if (_rows.isEmpty)
          Text(widget.emptyLabel ?? 'Nothing here yet.', style: TextStyle(color: scheme.onSurfaceVariant))
        else
          for (final row in _rows)
            ListTile(
              contentPadding: EdgeInsets.zero,
              dense: true,
              title: Text(widget.rowTitle(row), style: TextStyle(decoration: widget.hasActive && row['is_active'] == false ? TextDecoration.lineThrough : null)),
              subtitle: widget.rowSubtitle == null || widget.rowSubtitle!(row) == null ? null : Text(widget.rowSubtitle!(row)!),
              trailing: canManage
                  ? PopupMenuButton<String>(
                      onSelected: (v) => v == 'edit' ? _edit(row) : _toggle(row),
                      itemBuilder: (_) => [
                        const PopupMenuItem(value: 'edit', child: Text('Edit')),
                        if (widget.hasActive) PopupMenuItem(value: 'toggle', child: Text(row['is_active'] == false ? 'Reactivate' : 'Deactivate')),
                      ],
                    )
                  : null,
            ),
      ]),
    );
  }
}
