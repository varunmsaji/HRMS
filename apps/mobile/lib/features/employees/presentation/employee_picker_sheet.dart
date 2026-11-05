import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api/api_error.dart';
import '../../../core/widgets/ui.dart';
import '../../profile/data/employee_repository.dart';
import '../../profile/presentation/profile_screen.dart' show employeeRepositoryProvider;

/// Lets the user find any employee with the server's search, a page at a time. Resolves to the
/// chosen employee, or null if dismissed.
Future<Employee?> pickEmployee(BuildContext context) => showModalBottomSheet<Employee>(
      context: context,
      isScrollControlled: true,
      showDragHandle: true,
      builder: (_) => const EmployeePickerSheet(),
    );

class EmployeePickerSheet extends ConsumerStatefulWidget {
  const EmployeePickerSheet({super.key});

  @override
  ConsumerState<EmployeePickerSheet> createState() => _EmployeePickerSheetState();
}

class _EmployeePickerSheetState extends ConsumerState<EmployeePickerSheet> {
  final _search = TextEditingController();
  Timer? _debounce;
  List<Employee> _items = const [];
  bool _hasNext = false;
  int _page = 1;
  bool _loading = true;
  bool _loadingMore = false;
  String? _error;
  int _request = 0;

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void dispose() {
    _debounce?.cancel();
    _search.dispose();
    super.dispose();
  }

  String _describe(Object e) => e is ApiError ? e.message : 'Something went wrong.';

  /// A slower, older answer never overwrites a newer one.
  Future<void> _load() async {
    final mine = ++_request;
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final page = await ref.read(employeeRepositoryProvider).listEmployeesPage(search: _search.text);
      if (!mounted || mine != _request) return;
      setState(() {
        _items = page.rows;
        _hasNext = page.hasNext;
        _page = 1;
      });
    } catch (e) {
      if (mounted && mine == _request) setState(() => _error = _describe(e));
    } finally {
      if (mounted && mine == _request) setState(() => _loading = false);
    }
  }

  Future<void> _loadMore() async {
    if (_loadingMore || !_hasNext) return;
    final mine = _request;
    setState(() => _loadingMore = true);
    try {
      final page = await ref.read(employeeRepositoryProvider).listEmployeesPage(search: _search.text, page: _page + 1);
      if (!mounted || mine != _request) return;
      setState(() {
        _items = [..._items, ...page.rows];
        _hasNext = page.hasNext;
        _page += 1;
      });
    } catch (e) {
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(_describe(e))));
    } finally {
      if (mounted) setState(() => _loadingMore = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      height: MediaQuery.of(context).size.height * 0.8,
      child: Padding(
        padding: EdgeInsets.fromLTRB(16, 0, 16, MediaQuery.of(context).viewInsets.bottom),
        child: Column(children: [
          AppSearchField(
            controller: _search,
            hint: 'Search by name or code',
            onChanged: (_) {
              _debounce?.cancel();
              _debounce = Timer(const Duration(milliseconds: 300), _load);
            },
          ),
          const SizedBox(height: 8),
          Expanded(
            child: _loading
                ? const ListSkeleton(count: 5)
                : _error != null
                    ? StateMessage(icon: Icons.error_outline_rounded, tone: Tone.danger, title: "Couldn't load employees", message: _error, actionLabel: 'Retry', onAction: _load)
                    : _items.isEmpty
                        ? const StateMessage(icon: Icons.people_outline, title: 'No employees found')
                        : ListView(children: [
                            for (final e in _items)
                              ListTile(
                                contentPadding: EdgeInsets.zero,
                                title: Text(e.fullName.isEmpty ? e.employeeCode : e.fullName),
                                subtitle: e.fullName.isEmpty ? null : Text(e.employeeCode),
                                onTap: () => Navigator.of(context).pop(e),
                              ),
                            if (_hasNext) TextButton(onPressed: _loadingMore ? null : _loadMore, child: Text(_loadingMore ? 'Loading…' : 'Load more')),
                          ]),
          ),
        ]),
      ),
    );
  }
}
