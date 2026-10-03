import 'package:flutter/material.dart';

import '../api/api_error.dart';

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

  @override
  State<AsyncListScreen<T>> createState() => AsyncListScreenState<T>();
}

class AsyncListScreenState<T> extends State<AsyncListScreen<T>> {
  bool _loading = true;
  List<T> _items = const [];
  ApiError? _error;

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
    Widget body;
    if (_loading) {
      body = const Center(child: CircularProgressIndicator());
    } else if (_error != null) {
      body = Center(
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Text(
                _error!.status == 403 ? 'You do not have permission to view this.' : _error!.message,
                textAlign: TextAlign.center,
              ),
              const SizedBox(height: 16),
              FilledButton(onPressed: reload, child: const Text('Retry')),
            ],
          ),
        ),
      );
    } else if (_items.isEmpty) {
      body = Center(
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: Text(widget.emptyLabel, textAlign: TextAlign.center),
        ),
      );
    } else {
      body = ListView.separated(
        itemCount: _items.length,
        separatorBuilder: (_, __) => const Divider(height: 1),
        itemBuilder: (context, index) => widget.itemBuilder(context, _items[index]),
      );
    }

    return Scaffold(
      appBar: AppBar(title: Text(widget.title), actions: widget.actions),
      body: RefreshIndicator(onRefresh: reload, child: body),
      floatingActionButton: widget.onCreate == null
          ? null
          : FloatingActionButton.extended(
              onPressed: widget.onCreate,
              icon: const Icon(Icons.add),
              label: Text(widget.createLabel ?? 'New'),
            ),
    );
  }
}
