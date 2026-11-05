import 'package:flutter/material.dart';

import '../api/api_error.dart';
import 'ui.dart';

/// Shared list-screen shell (loading / error-with-retry / empty / pull-to-
/// refresh) used by every simple resource list in the app (branches,
/// departments, shifts, leave types, …) so each one only has to supply how
/// to fetch and how to render a row.
class AsyncListScreen<T> extends StatefulWidget {
  const AsyncListScreen({
    super.key,
    required this.title,
    required this.fetch,
    required this.itemBuilder,
    this.onCreate,
    this.createLabel,
    this.emptyLabel = 'Nothing here yet.',
    this.actions,
    this.searchText,
    this.header,
  });

  final String title;
  final Future<List<T>> Function() fetch;
  final Widget Function(BuildContext context, T item) itemBuilder;

  /// Pushes a create form when set; the FAB is omitted otherwise (read-only
  /// resource, or the caller lacks the manage permission).
  final VoidCallback? onCreate;
  final String? createLabel;
  final String emptyLabel;
  final List<Widget>? actions;

  /// Enables the search bar; returns the text a row is matched against.
  final String Function(T item)? searchText;

  /// Shown above the search bar, whatever the list's state (status tabs, say).
  final Widget? header;

  @override
  State<AsyncListScreen<T>> createState() => AsyncListScreenState<T>();
}

class AsyncListScreenState<T> extends State<AsyncListScreen<T>> {
  bool _loading = true;
  List<T> _items = const [];
  ApiError? _error;
  String _query = '';

  @override
  void initState() {
    super.initState();
    reload();
  }

  Future<void> reload() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final items = await widget.fetch();
      if (mounted) setState(() => _items = items);
    } catch (error) {
      if (mounted) {
        setState(() => _error = error is ApiError ? error : ApiError(status: 0, code: 'UNKNOWN_ERROR', message: 'Something went wrong.'));
      }
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final query = _query.trim().toLowerCase();
    final search = widget.searchText;
    final visible = query.isEmpty || search == null
        ? _items
        : _items.where((item) => search(item).toLowerCase().contains(query)).toList();

    Widget body;
    if (_loading) {
      body = const ListSkeleton();
    } else if (_error != null) {
      final forbidden = _error!.status == 403;
      body = StateMessage(
        icon: forbidden ? Icons.lock_outline_rounded : Icons.cloud_off_rounded,
        tone: forbidden ? Tone.warning : Tone.danger,
        title: forbidden ? 'No access' : 'Couldn\'t load this',
        message: forbidden ? 'You do not have permission to view this.' : _error!.message,
        actionLabel: forbidden ? null : 'Try again',
        onAction: reload,
      );
    } else if (visible.isEmpty) {
      body = StateMessage(
        icon: query.isEmpty ? Icons.inbox_outlined : Icons.search_off_rounded,
        title: query.isEmpty ? widget.emptyLabel : 'No matches',
        message: query.isEmpty
            ? (widget.onCreate != null ? 'Tap "${widget.createLabel ?? 'New'}" to add the first one.' : null)
            : 'Nothing matches "$_query".',
      );
    } else {
      body = ListView.separated(
        padding: const EdgeInsets.fromLTRB(16, 4, 16, 96),
        itemCount: visible.length,
        separatorBuilder: (_, __) => const SizedBox(height: 10),
        itemBuilder: (context, index) => _RowShell(child: widget.itemBuilder(context, visible[index])),
      );
    }

    return Scaffold(
      appBar: AppBar(title: Text(widget.title), actions: widget.actions),
      body: Column(
        children: [
          if (widget.header != null) widget.header!,
          if (search != null && !_loading && _error == null && _items.isNotEmpty)
            Padding(
              padding: const EdgeInsets.fromLTRB(16, 4, 16, 10),
              child: AppSearchField(hint: 'Search ${widget.title.toLowerCase()}', onChanged: (v) => setState(() => _query = v)),
            ),
          Expanded(child: RefreshIndicator(onRefresh: reload, child: body)),
        ],
      ),
      floatingActionButton: widget.onCreate == null
          ? null
          : FloatingActionButton.extended(
              onPressed: widget.onCreate,
              icon: const Icon(Icons.add_rounded),
              label: Text(widget.createLabel ?? 'New'),
            ),
    );
  }
}

/// Gives a plain row (a bare ListTile, say) the same card surface as [AppCard].
/// Rows that already draw their own card (like [ListRowCard]) pass through untouched.
class _RowShell extends StatelessWidget {
  const _RowShell({required this.child});

  final Widget child;

  @override
  Widget build(BuildContext context) {
    if (child is AppCard || child is ListRowCard) return child;
    final scheme = Theme.of(context).colorScheme;
    return Material(
      color: scheme.brightness == Brightness.dark ? scheme.surfaceContainer : scheme.surfaceContainerLowest,
      clipBehavior: Clip.antiAlias,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(16),
        side: BorderSide(color: scheme.outlineVariant.withValues(alpha: 0.55)),
      ),
      child: child,
    );
  }
}
